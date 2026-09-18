interface StatTileProps {
    label: string;
    value: string;
    /** Secondary line: the context that stops the number being read alone. */
    note?: string;
    /** Status carries an explicit word too -- never colour alone. */
    status?: "good" | "warn" | "bad";
    statusLabel?: string;
}

const STATUS_CLASS: Record<string, string> = {
    good: "text-[--stat-good]",
    warn: "text-[--stat-warn]",
    bad: "text-[--stat-bad]",
};

/**
 * A headline number. Deliberately not a one-bar chart: a single current value
 * reads faster as text, and the chart would add ink without adding meaning.
 */
export default function StatTile({ label, value, note, status, statusLabel }: StatTileProps) {
    return (
        <div className="rounded border border-[--viz-border] bg-[--viz-surface] p-3">
            <div className="text-xs uppercase tracking-wide text-[--viz-muted]">{label}</div>
            <div className="pt-1 text-2xl font-semibold tabular-nums text-[--viz-ink]">{value}</div>
            {(note || statusLabel) && (
                <div className="pt-0.5 text-xs text-[--viz-secondary]">
                    {statusLabel && (
                        <span className={`font-medium ${status ? STATUS_CLASS[status] : ""}`}>
                            {statusLabel}
                        </span>
                    )}
                    {statusLabel && note ? " · " : ""}
                    {note}
                </div>
            )}
        </div>
    );
}
