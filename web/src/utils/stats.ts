export interface Stats {
    totals: { articles: number; clusters: number; enriched: number; clustered: number; sources: number };
    throughput: { window_minutes: number; ingested: number; per_hour: number };
    dedup: { articles: number; clusters: number; collapsed: number; rate_pct: number };
    latency_ms: Record<string, { calls: number; p50: number | null; p95: number | null }>;
    spend: {
        tokens_in: number;
        tokens_out: number;
        cache_read_tokens: number;
        calls: number;
        cached_calls: number;
    };
    failures: Record<string, number>;
    cluster_sizes: Record<string, number>;
    queue: Record<string, { messages: number; consumers: number }> | { error: string };
}

/** Claude Sonnet 5 rates, $/1M tokens. Cache reads bill at ~1/10 of input. */
const RATE_IN = 2.0;
const RATE_OUT = 10.0;
const RATE_CACHE_READ = 0.2;

export function actualCost(spend: Stats["spend"]): number {
    return (
        (spend.tokens_in * RATE_IN +
            spend.tokens_out * RATE_OUT +
            spend.cache_read_tokens * RATE_CACHE_READ) /
        1e6
    );
}

/** What the same work would have cost with no prompt caching. */
export function uncachedCost(spend: Stats["spend"]): number {
    return (
        ((spend.tokens_in + spend.cache_read_tokens) * RATE_IN + spend.tokens_out * RATE_OUT) / 1e6
    );
}

export function formatDuration(ms: number | null): string {
    if (ms === null || ms === undefined) return "—";
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

export function formatCount(n: number): string {
    if (n >= 1_000_000) return `${(n / 1e6).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1e3).toFixed(1)}k`;
    return String(n);
}

/** Stage names as written to pipeline_events, in pipeline order. */
export const STAGE_LABELS: Record<string, string> = {
    ingest: "Ingest",
    cluster_new: "Cluster (new)",
    cluster_join: "Cluster (join)",
    enrich: "Enrich",
};
