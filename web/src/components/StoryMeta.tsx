import { Enrichment } from "@/utils/types";
import { coverageLabel, outletName } from "@/utils/format";

interface StoryMetaProps {
    outletCount: number;
    sources: string[];
    enrichment: Enrichment | null;
    compact?: boolean;
}

const SENTIMENT_STYLES: Record<string, string> = {
    positive: "bg-emerald-50 text-emerald-800 border-emerald-200",
    negative: "bg-rose-50 text-rose-800 border-rose-200",
    neutral: "bg-slate-50 text-slate-700 border-slate-200",
};

/**
 * The pipeline's work made visible: which outlets carried the story, what the
 * model pulled out of it, and how each named entity was treated.
 */
export default function StoryMeta({ outletCount, sources, enrichment, compact }: StoryMetaProps) {
    const coverage = coverageLabel(outletCount);
    const topics = enrichment?.topics ?? [];
    const entities = enrichment?.entities ?? [];
    const tickers = enrichment?.tickers ?? [];

    if (!coverage && topics.length === 0 && entities.length === 0) return null;

    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-2 text-xs">
            {coverage && (
                <span
                    className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-semibold text-amber-900"
                    title={sources.map(outletName).join(", ")}
                >
                    {coverage}
                </span>
            )}

            {topics.map((topic) => (
                <span key={topic} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700">
                    {topic}
                </span>
            ))}

            {tickers.map((ticker) => (
                <span
                    key={ticker}
                    className="rounded border border-slate-300 px-1.5 py-0.5 font-mono text-slate-800"
                >
                    {ticker}
                </span>
            ))}

            {!compact &&
                entities.slice(0, 5).map((entity) => (
                    <span
                        key={entity.name}
                        className={`rounded border px-1.5 py-0.5 ${SENTIMENT_STYLES[entity.sentiment] ?? SENTIMENT_STYLES.neutral}`}
                        title={`${entity.type} · ${entity.sentiment}`}
                    >
                        {entity.name}
                    </span>
                ))}
        </div>
    );
}
