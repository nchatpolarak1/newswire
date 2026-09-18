interface ArticleImageProps {
    src: string;
    alt: string;
    className: string;
}

/**
 * Article images come from arbitrary outlets, so a missing or broken URL is
 * normal rather than exceptional. Renders a neutral placeholder instead of a
 * broken-image icon. Plain <img> on purpose: next/image would need every
 * outlet's hostname in remotePatterns up front, which the poller cannot know.
 */
export default function ArticleImage({ src, alt, className }: ArticleImageProps) {
    if (!src) {
        return <div className={`${className} bg-slate-200`} aria-hidden />;
    }

    return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
            src={src}
            alt={alt}
            className={className}
            loading="lazy"
            onError={(event) => {
                const img = event.currentTarget;
                img.style.display = "none";
                img.parentElement?.classList.add("bg-slate-200");
            }}
        />
    );
}
