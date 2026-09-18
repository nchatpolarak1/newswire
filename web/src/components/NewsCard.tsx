import Link from "next/link";

import ArticleImage from "@/components/ArticleImage";
import StoryMeta from "@/components/StoryMeta";
import { Story } from "@/utils/types";
import { byline, outletName, truncate } from "@/utils/format";

interface NewsCardProps {
    story: Story;
    compact?: boolean;
}

function NewsCard({ story, compact }: NewsCardProps) {
    const summary = story.enrichment?.summary || story.body;

    return (
        <div className="news-card">
            <div className="news-img-div">
                <ArticleImage src={story.image_url} alt={story.title} className="news-img w-full" />
            </div>
            <div className="news-info">
                <Link href={story.url} target="_blank" rel="noopener noreferrer">
                    <h3 className="story-title hover:underline">{story.title}</h3>
                </Link>
                <p className="story-summary">{truncate(summary, 220)}</p>
                <StoryMeta
                    outletCount={story.outlet_count}
                    sources={story.sources}
                    enrichment={story.enrichment}
                    compact={compact}
                />
                <span className="story-author">
                    {byline(story.author, story.published_at)} · {outletName(story.source)}
                </span>
            </div>
        </div>
    );
}

export default NewsCard;
