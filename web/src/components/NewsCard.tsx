import Link from "next/link";

import ArticleImage from "@/components/ArticleImage";
import { Article } from "@/utils/types";
import { byline, truncate } from "@/utils/format";

interface NewsCardProps {
    article: Article;
}

function NewsCard({ article }: NewsCardProps) {
    return (
        <div className="news-card">
            <div className="news-img-div">
                <ArticleImage
                    src={article.image_url}
                    alt={article.title}
                    className="news-img w-full"
                />
            </div>
            <div className="news-info">
                <Link href={article.url} target="_blank" rel="noopener noreferrer">
                    <h3 className="story-title hover:underline">{article.title}</h3>
                </Link>
                <p className="story-summary">{truncate(article.body, 220)}</p>
                <span className="story-author">{byline(article.author, article.publish_date)}</span>
            </div>
        </div>
    );
}

export default NewsCard;
