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
export function formatDate(iso: string): string {
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
export function byline(author: string, publishDate: string): string {
    const when = formatDate(publishDate);
    const who = author?.trim();
    if (who && when) return `${who} · ${when}`;
    return who || when;
}
