"""Generic consume loop with at-least-once semantics and a retry budget.

Separated from the article handling so the delivery semantics -- the part that
is easy to get subtly wrong -- can be read and reasoned about on their own.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Protocol

from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from pipeline import config, queue

log = logging.getLogger(__name__)


class PermanentError(Exception):
    """Failure that retrying cannot fix: malformed payload, missing fields.

    Goes straight to the DLQ without consuming the retry budget, because
    replaying it would fail identically three more times.
    """


Handler = Callable[[dict], None]


class _Stoppable(Protocol):
    def is_running(self) -> bool: ...


def _dispatch(
    ch: BlockingChannel,
    method: Basic.Deliver,
    props: BasicProperties,
    body: bytes,
    handler: Handler,
) -> None:
    """Run the handler for one delivery and settle the message exactly once.

    Ack happens only after the handler returns, so a crash mid-handler leaves
    the message unacked and the broker redelivers it. That is what makes the
    handler's own idempotency load-bearing rather than decorative.
    """
    attempts = queue.retry_count(props)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        log.error("undecodable payload, routing to DLQ: %s", exc)
        ch.basic_nack(method.delivery_tag, requeue=False)
        return

    try:
        handler(payload)
    except PermanentError as exc:
        log.error("permanent failure, routing to DLQ: %s", exc)
        ch.basic_nack(method.delivery_tag, requeue=False)
        return
    except Exception as exc:
        if attempts >= config.MAX_RETRIES:
            log.error("retry budget spent after %d attempts, routing to DLQ: %s", attempts, exc)
            ch.basic_nack(method.delivery_tag, requeue=False)
            return

        log.warning("attempt %d/%d failed, republishing: %s", attempts + 1, config.MAX_RETRIES, exc)
        queue.republish_for_retry(ch, method.routing_key, body, attempts + 1)
        # Ack the original only after the replacement is published; if the
        # publish fails we fall through unacked and the broker redelivers.
        ch.basic_ack(method.delivery_tag)
        return

    ch.basic_ack(method.delivery_tag)


def consume(handler: Handler, should_continue: Callable[[], bool]) -> None:
    """Consume until should_continue() goes false or the connection drops."""
    with queue.channel() as ch:
        # Bounded prefetch is what lets `--scale enricher=N` actually spread
        # work: unbounded, the first consumer buffers the queue and the rest idle.
        ch.basic_qos(prefetch_count=config.PREFETCH_COUNT)
        log.info("consuming %s (prefetch=%d)", config.RAW_QUEUE, config.PREFETCH_COUNT)

        for method, props, body in ch.consume(config.RAW_QUEUE, inactivity_timeout=1.0, auto_ack=False):
            if not should_continue():
                break
            if method is None:  # inactivity tick, lets us re-check the flag
                continue
            _dispatch(ch, method, props, body, handler)

        ch.cancel()
