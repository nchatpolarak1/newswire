import { useState } from "react";

interface ClusterSizeChartProps {
    /** cluster size -> how many clusters have that many articles */
    distribution: Record<string, number>;
}

/**
 * Magnitude comparison across an ordered scale, so: bars, one hue, no legend.
 * A single series needs no legend box -- the heading names it.
 *
 * The y-axis is log-scaled because size-1 clusters outnumber the rest by two
 * orders of magnitude; on a linear axis every bar past the first is a
 * indistinguishable sliver, which is the thing worth seeing.
 */
const MAX_BARS = 12;

export default function ClusterSizeChart({ distribution }: ClusterSizeChartProps) {
    const [hovered, setHovered] = useState<string | null>(null);

    // Fill gaps in the scale. Cluster sizes are ordinal, so plotting only the
    // sizes that occur would space 1,2,4,5 evenly and read as consecutive --
    // hiding that no cluster has exactly three articles.
    const present = Object.entries(distribution).map(([size, count]) => ({
        size: Number(size),
        count,
    }));
    const largest = present.length ? Math.max(...present.map((e) => e.size)) : 0;
    const bySize = new Map(present.map((e) => [e.size, e.count]));

    // One bar per size works while sizes stay small, but a single heavily
    // covered story would put 30 bars and 30 axis labels in a fixed-width
    // panel. Past MAX_BARS the tail folds into one bucket rather than
    // shrinking every bar toward invisibility.
    const head = Array.from({ length: Math.min(largest, MAX_BARS) }, (_, i) => ({
        size: i + 1,
        label: String(i + 1),
        count: bySize.get(i + 1) ?? 0,
    }));
    const tailCount = present
        .filter((e) => e.size > MAX_BARS)
        .reduce((sum, e) => sum + e.count, 0);
    const entries =
        tailCount > 0
            ? [...head, { size: MAX_BARS + 1, label: `${MAX_BARS + 1}+`, count: tailCount }]
            : head;

    if (entries.length === 0) {
        return <p className="text-sm text-[--viz-secondary]">No clusters yet.</p>;
    }

    const max = Math.max(...entries.map((e) => e.count));
    const scale = (n: number) => (Math.log10(n + 1) / Math.log10(max + 1)) * 100;
    const total = entries.reduce((sum, e) => sum + e.count, 0);

    return (
        <div>
            <div className="flex h-44 items-end gap-[2px]" role="img"
                 aria-label={`Cluster size distribution across ${total} clusters`}>
                {entries.map((entry) => {
                    const pct = scale(entry.count);
                    const isHovered = hovered === String(entry.size);
                    return (
                        <div
                            key={entry.size}
                            className="relative flex flex-1 flex-col items-center justify-end"
                            style={{ height: "100%" }}
                            onMouseEnter={() => setHovered(String(entry.size))}
                            onMouseLeave={() => setHovered(null)}
                        >
                            {isHovered && (
                                <div className="absolute bottom-full z-10 mb-1 whitespace-nowrap rounded border border-[--viz-border] bg-[--viz-surface] px-2 py-1 text-xs text-[--viz-ink] shadow-sm">
                                    <strong>{entry.count}</strong> cluster{entry.count === 1 ? "" : "s"} of{" "}
                                    {entry.label} article{entry.count === 1 && entry.size === 1 ? "" : "s"}
                                </div>
                            )}
                            {/* Direct label: selective -- only where the bar is tall
                                enough to host one without collision. */}
                            {pct > 22 && (
                                <span className="pb-1 text-[10px] tabular-nums text-[--viz-secondary]">
                                    {entry.count}
                                </span>
                            )}
                            <div
                                className="w-full max-w-[24px] rounded-t bg-[--viz-series-1] transition-opacity"
                                style={{ height: entry.count === 0 ? "0%" : `${Math.max(pct, 1.5)}%`, opacity: isHovered ? 0.8 : 1 }}
                            />
                        </div>
                    );
                })}
            </div>

            <div className="flex gap-[2px] border-t border-[--viz-border] pt-1">
                {entries.map((entry) => (
                    <div key={entry.size} className="flex-1 text-center text-[10px] text-[--viz-muted]">
                        {entry.label}
                    </div>
                ))}
            </div>
            <p className="pt-1 text-xs text-[--viz-muted]">
                articles per cluster · log scale · {total} clusters
            </p>
        </div>
    );
}
