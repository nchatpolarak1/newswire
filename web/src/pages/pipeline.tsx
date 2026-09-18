import { useEffect, useState } from "react";

import ClusterSizeChart from "@/components/ClusterSizeChart";
import StatTile from "@/components/StatTile";
import {
    STAGE_LABELS,
    Stats,
    actualCost,
    formatCount,
    formatDuration,
    uncachedCost,
} from "@/utils/stats";

const REFRESH_MS = 4000;

export default function Pipeline() {
    const [stats, setStats] = useState<Stats | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

    useEffect(() => {
        let cancelled = false;

        const poll = async () => {
            try {
                const res = await fetch("/api/news/stats");
                if (!res.ok) throw new Error(`stats responded ${res.status}`);
                const data = (await res.json()) as Stats;
                if (cancelled) return;
                setStats(data);
                setUpdatedAt(new Date());
                setError(null);
            } catch (err) {
                if (!cancelled) setError((err as Error).message);
            }
        };

        poll();
        const timer = setInterval(poll, REFRESH_MS);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, []);

    if (error && !stats) {
        return (
            <div className="p-8 text-center">
                <p className="text-xl font-semibold">Pipeline metrics unavailable</p>
                <p className="pt-2 text-sm">Could not reach the API ({error}).</p>
            </div>
        );
    }

    if (!stats) return <p className="p-8 text-center">Loading metrics…</p>;

    const cost = actualCost(stats.spend);
    const wouldHaveCost = uncachedCost(stats.spend);
    const saved = wouldHaveCost > 0 ? ((wouldHaveCost - cost) / wouldHaveCost) * 100 : 0;
    const cacheHitRate =
        stats.spend.calls > 0 ? (stats.spend.cached_calls / stats.spend.calls) * 100 : 0;
    const failures = Object.entries(stats.failures).filter(([stage]) => stage !== "duplicate");
    const failureCount = failures.reduce((sum, [, n]) => sum + n, 0);
    const queues = "error" in stats.queue ? null : stats.queue;
    const backlog = queues ? (queues["articles.raw"]?.messages ?? 0) : null;

    return (
        <div className="viz-root px-2 py-4">
            <div className="flex items-baseline justify-between pb-3">
                <h1 className="text-2xl font-semibold text-[--viz-ink]">Pipeline</h1>
                <span className="text-xs text-[--viz-muted]">
                    {updatedAt ? `updated ${updatedAt.toLocaleTimeString()}` : ""}
                    {error ? " · reconnecting…" : ""}
                </span>
            </div>

            {/* Headline numbers. Stat tiles, not charts: a single current value
                reads faster as text than as a one-bar chart. */}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
                <StatTile
                    label="Articles"
                    value={formatCount(stats.totals.articles)}
                    note={`${stats.totals.sources} sources`}
                />
                <StatTile
                    label="Stories"
                    value={formatCount(stats.totals.clusters)}
                    note="after clustering"
                />
                <StatTile
                    label="Collapsed"
                    value={`${stats.dedup.rate_pct}%`}
                    note={`${stats.dedup.collapsed} of ${stats.dedup.articles} articles`}
                />
                <StatTile
                    label="Enriched"
                    value={formatCount(stats.totals.enriched)}
                    note={`${stats.spend.calls} model calls`}
                />
                <StatTile
                    label="Spend"
                    value={`$${cost.toFixed(2)}`}
                    status="good"
                    statusLabel={`${saved.toFixed(0)}% saved`}
                    note={`vs $${wouldHaveCost.toFixed(2)} uncached`}
                />
                <StatTile
                    label="Backlog"
                    value={backlog === null ? "—" : formatCount(backlog)}
                    status={backlog === null ? "warn" : backlog > 200 ? "warn" : "good"}
                    statusLabel={
                        backlog === null
                            ? "broker unreachable"
                            : backlog > 200
                              ? "backing up"
                              : "keeping up"
                    }
                    note={queues ? `${queues["articles.raw"]?.consumers ?? 0} consumers` : undefined}
                />
            </div>

            <div className="grid grid-cols-1 gap-4 pt-4 lg:grid-cols-2">
                <section className="rounded border border-[--viz-border] p-3">
                    <h2 className="pb-2 text-sm font-semibold text-[--viz-ink]">
                        Clusters by article count
                    </h2>
                    <ClusterSizeChart distribution={stats.cluster_sizes} />
                </section>

                <section className="rounded border border-[--viz-border] p-3">
                    <h2 className="pb-2 text-sm font-semibold text-[--viz-ink]">Stage latency</h2>
                    {/* A table, not a chart: these span 6ms to 6s, and on any
                        shared axis the fast stages become invisible slivers. */}
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-[--viz-border] text-left text-xs uppercase tracking-wide text-[--viz-muted]">
                                <th className="pb-1 font-medium">Stage</th>
                                <th className="pb-1 text-right font-medium">Calls</th>
                                <th className="pb-1 text-right font-medium">p50</th>
                                <th className="pb-1 text-right font-medium">p95</th>
                            </tr>
                        </thead>
                        <tbody className="tabular-nums">
                            {Object.entries(stats.latency_ms).map(([stage, m]) => (
                                <tr key={stage} className="border-b border-[--viz-border] last:border-0">
                                    <td className="py-1 text-[--viz-ink]">{STAGE_LABELS[stage] ?? stage}</td>
                                    <td className="py-1 text-right text-[--viz-secondary]">{m.calls}</td>
                                    <td className="py-1 text-right text-[--viz-ink]">{formatDuration(m.p50)}</td>
                                    <td className="py-1 text-right text-[--viz-secondary]">{formatDuration(m.p95)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>

                <section className="rounded border border-[--viz-border] p-3">
                    <h2 className="pb-2 text-sm font-semibold text-[--viz-ink]">Queues</h2>
                    {queues ? (
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-[--viz-border] text-left text-xs uppercase tracking-wide text-[--viz-muted]">
                                    <th className="pb-1 font-medium">Queue</th>
                                    <th className="pb-1 text-right font-medium">Messages</th>
                                    <th className="pb-1 text-right font-medium">Consumers</th>
                                </tr>
                            </thead>
                            <tbody className="tabular-nums">
                                {Object.entries(queues).map(([name, q]) => (
                                    <tr key={name} className="border-b border-[--viz-border] last:border-0">
                                        <td className="py-1 font-mono text-xs text-[--viz-ink]">{name}</td>
                                        <td className="py-1 text-right text-[--viz-ink]">{q.messages}</td>
                                        <td className="py-1 text-right text-[--viz-secondary]">{q.consumers}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <p className="text-sm text-[--stat-warn]">
                            Broker unreachable — other figures come from Postgres and are unaffected.
                        </p>
                    )}
                </section>

                <section className="rounded border border-[--viz-border] p-3">
                    <h2 className="pb-2 text-sm font-semibold text-[--viz-ink]">Model usage</h2>
                    <dl className="grid grid-cols-2 gap-y-1 text-sm tabular-nums">
                        <dt className="text-[--viz-secondary]">Input tokens</dt>
                        <dd className="text-right text-[--viz-ink]">{formatCount(stats.spend.tokens_in)}</dd>
                        <dt className="text-[--viz-secondary]">Output tokens</dt>
                        <dd className="text-right text-[--viz-ink]">{formatCount(stats.spend.tokens_out)}</dd>
                        <dt className="text-[--viz-secondary]">Served from cache</dt>
                        <dd className="text-right text-[--viz-ink]">
                            {formatCount(stats.spend.cache_read_tokens)}
                        </dd>
                        <dt className="text-[--viz-secondary]">Calls hitting cache</dt>
                        <dd className="text-right text-[--viz-ink]">
                            {stats.spend.cached_calls}/{stats.spend.calls} ({cacheHitRate.toFixed(0)}%)
                        </dd>
                        <dt className="text-[--viz-secondary]">Enrichment failures</dt>
                        <dd className={`text-right ${failureCount > 0 ? "text-[--stat-bad]" : "text-[--viz-ink]"}`}>
                            {failureCount}
                        </dd>
                        <dt className="text-[--viz-secondary]">Throughput</dt>
                        <dd className="text-right text-[--viz-ink]">
                            {stats.throughput.per_hour}/hr
                        </dd>
                    </dl>
                </section>
            </div>
        </div>
    );
}
