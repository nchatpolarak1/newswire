import { useState } from "react";

interface ArticleImageProps {
    src: string;
    alt: string;
    className: string;
}

/**
 * Article images come from arbitrary outlets, so a missing or broken URL is
 * normal rather than exceptional.
 *
 * Renders nothing at all in that case, rather than an empty placeholder: the
 * card's image column previously used `md:h-max`, which is height: max-content
 * and therefore zero for an empty div, so a story with no art left half the
 * featured card blank. Callers check for an image and drop the column instead.
 *
 * Plain <img> on purpose: next/image would need every outlet's hostname in
 * remotePatterns up front, which the poller cannot know.
 */
export default function ArticleImage({ src, alt, className }: ArticleImageProps) {
    const [failed, setFailed] = useState(false);

    if (!src || failed) return null;

    return (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={alt} className={className} loading="lazy" onError={() => setFailed(true)} />
    );
}
