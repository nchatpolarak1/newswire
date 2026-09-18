"""RabbitMQ topology and connection helpers.

Both the poller and the enricher declare the same topology on startup. The
declarations are idempotent, so whichever process starts first wins and the
other is a no-op -- no ordering requirement between services.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel

from pipeline import config

log = logging.getLogger(__name__)

# A message that fails MAX_RETRIES times carries this header so the DLQ shows
# why it landed there rather than just that it did.
RETRY_HEADER = "x-retry-count"

# Backoff tiers. A retry queue holds the message for its TTL and then
# dead-letters it back to the news exchange, so the wait costs no consumer
# time -- the broker does the waiting. One queue per tier rather than
# per-message TTL, which expires strictly in publish order and would let a
# long delay at the head block shorter ones behind it.
RETRY_DELAYS_MS = (2_000, 8_000, 32_000)
RETRY_QUEUE = "articles.retry.{}"

# Dead-lettering preserves the original routing key, which for a retry queue
# would be the queue name and would not match article.raw.#. Pin it instead.
RETRY_RETURN_KEY = "article.raw.retry"


def connection_params() -> pika.ConnectionParameters:
    params = pika.URLParameters(config.RABBITMQ_URL)
    # Survive a broker restart during a long run instead of dying on it.
    params.heartbeat = 60
    params.blocked_connection_timeout = 30
    params.connection_attempts = 10
    params.retry_delay = 3.0
    return params


@contextmanager
def channel() -> Iterator[BlockingChannel]:
    """Open a connection and channel with the topology declared."""
    conn = pika.BlockingConnection(connection_params())
    try:
        ch = conn.channel()
        declare_topology(ch)
        yield ch
    finally:
        if conn.is_open:
            conn.close()


def declare_topology(ch: BlockingChannel) -> None:
    """Declare exchanges, queues and bindings. Idempotent.

    Raw articles land on `articles.raw`. A message rejected without requeue --
    or one that exceeds the retry budget -- is routed by the broker to
    `news.dlx` and parked on `articles.dead` for inspection, rather than being
    dropped or redelivered forever.
    """
    ch.exchange_declare(config.DLX_EXCHANGE, exchange_type="fanout", durable=True)
    ch.queue_declare(config.DEAD_QUEUE, durable=True)
    ch.queue_bind(config.DEAD_QUEUE, config.DLX_EXCHANGE)

    ch.exchange_declare(config.EXCHANGE, exchange_type="topic", durable=True)
    ch.queue_declare(
        config.RAW_QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": config.DLX_EXCHANGE},
    )
    ch.queue_bind(config.RAW_QUEUE, config.EXCHANGE, routing_key=config.RAW_ROUTING_PATTERN)

    for tier, delay_ms in enumerate(RETRY_DELAYS_MS, start=1):
        ch.queue_declare(
            RETRY_QUEUE.format(tier),
            durable=True,
            arguments={
                "x-message-ttl": delay_ms,
                "x-dead-letter-exchange": config.EXCHANGE,
                "x-dead-letter-routing-key": RETRY_RETURN_KEY,
            },
        )


def publish(ch: BlockingChannel, routing_key: str, payload: dict[str, Any]) -> None:
    """Publish a durable JSON message to the news exchange."""
    ch.basic_publish(
        exchange=config.EXCHANGE,
        routing_key=routing_key,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
        ),
    )


def retry_count(properties: pika.BasicProperties) -> int:
    """How many times this message has already been retried."""
    headers = properties.headers or {}
    try:
        return int(headers.get(RETRY_HEADER, 0))
    except (TypeError, ValueError):
        return 0


def schedule_retry(ch: BlockingChannel, body: bytes, attempts: int) -> int:
    """Park a failed message in the retry queue for its backoff tier.

    Re-publishing rather than nack(requeue=True) is deliberate: requeue returns
    the message to the head of the queue carrying no counter, so a poison
    message spins forever. Here the budget rides on the message and the broker
    holds it for the delay, so waiting costs no consumer capacity.

    Returns the delay in milliseconds that was applied.
    """
    tier = min(attempts, len(RETRY_DELAYS_MS))
    delay_ms = RETRY_DELAYS_MS[tier - 1]

    # The default exchange routes by queue name, straight to that one queue.
    ch.basic_publish(
        exchange="",
        routing_key=RETRY_QUEUE.format(tier),
        body=body,
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
            headers={RETRY_HEADER: attempts},
        ),
    )
    return delay_ms


def queue_depth(ch: BlockingChannel, queue: Optional[str] = None) -> int:
    """Current message count, via a passive declare (does not mutate state)."""
    result = ch.queue_declare(queue or config.RAW_QUEUE, passive=True)
    return int(result.method.message_count)
