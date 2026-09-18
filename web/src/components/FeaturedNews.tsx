import Link from "next/link";

import ArticleImage from "@/components/ArticleImage";
import StoryMeta from "@/components/StoryMeta";
import { Story } from "@/utils/types";
import { byline, outletName, truncate } from "@/utils/format";

interface FeaturedNewsCardProps {
    story: Story;
}

function FeaturedNewsCard({ story }: FeaturedNewsCardProps) {
    // Prefer the model's summary: it is two clean sentences about the event,
    // where the body opens with whatever the extractor kept.
    const summary = story.enrichment?.summary || truncate(story.body, 500);
    // No art means no image column: reserving one leaves half the card blank.
    const hasImage = Boolean(story.image_url);

    return (
        <div className={hasImage ? "featured-news-card" : "grid grid-cols-1 gap-4"}>
            {hasImage && (
                <div className="featured-news-img-div">
                    <ArticleImage src={story.image_url} alt={story.title} className="featured-news-img w-full" />
                </div>
            )}
            <div className="featured-news-info">
                <Link href={story.url} target="_blank" rel="noopener noreferrer">
                    <h2 className="featured-story-title hover:underline">{story.title}</h2>
                </Link>
                <p className="featured-story-summary">{summary}</p>
                <StoryMeta
                    outletCount={story.outlet_count}
                    sources={story.sources}
                    enrichment={story.enrichment}
                />
                <span className="featured-story-author">
                    {byline(story.author, story.published_at)} · {outletName(story.source)}
                </span>
            </div>
        </div>
    );
}

export default FeaturedNewsCard;
