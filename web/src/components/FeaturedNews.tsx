import Link from "next/link";

import ArticleImage from "@/components/ArticleImage";
import { Article } from "@/utils/types";
import { byline, truncate } from "@/utils/format";

interface FeaturedNewsCardProps {
    article: Article;
}

function FeaturedNewsCard({ article }: FeaturedNewsCardProps) {
    return (
        <div className="featured-news-card">
            <div className="featured-news-img-div">
                <ArticleImage
                    src={article.image_url}
                    alt={article.title}
                    className="featured-news-img w-full"
                />
            </div>
            <div className="featured-news-info">
                <Link href={article.url} target="_blank" rel="noopener noreferrer">
                    <h2 className="featured-story-title hover:underline">{article.title}</h2>
                </Link>
                <p className="featured-story-summary">{truncate(article.body, 500)}</p>
                <span className="featured-story-author">{byline(article.author, article.publish_date)}</span>
            </div>
        </div>
    );
}

export default FeaturedNewsCard;
