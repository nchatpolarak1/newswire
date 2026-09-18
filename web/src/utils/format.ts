/** Truncate on a word boundary so cards do not cut mid-word. */
export function truncate(text: string, maxChars: number): string {
    if (!text) return "";
    const trimmed = text.trim();
    if (trimmed.length <= maxChars) return trimmed;
    const cut = trimmed.slice(0, maxChars);
    const lastSpace = cut.lastIndexOf(" ");
    return `${(lastSpace > 0 ? cut.slice(0, lastSpace) : cut).replace(/[.,;:]$/, "")}…`;
}

/** Render a publish date, tolerating missing or unparseable values. */
export function formatDate(iso: string | null): string {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
    });
}

/** Byline that stays sensible when the feed gives us no author. */
export function byline(author: string, publishedAt: string | null): string {
    const when = formatDate(publishedAt);
    const who = author?.trim();
    if (who && when) return `${who} · ${when}`;
    return who || when;
}

/** Outlet slugs like "bbc-business" read better as "BBC Business". */
const ACRONYMS = new Set(["bbc", "npr", "cbs", "cnbc", "ft", "ap"]);

export function outletName(slug: string): string {
    return slug
        .split("-")
        .map((part) =>
            ACRONYMS.has(part) ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1),
        )
        .join(" ");
}

/** "covered by 4 outlets" — only meaningful above one. */
export function coverageLabel(outletCount: number): string | null {
    if (outletCount <= 1) return null;
    return `Covered by ${outletCount} outlets`;
}
