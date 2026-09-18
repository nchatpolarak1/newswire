import NewsCard from "@/components/NewsCard";
import { Article } from "@/utils/types";

interface NewsFeedProps {
    articles: Article[];
}

function NewsFeed({ articles }: NewsFeedProps) {
    if (articles.length === 0) return null;

    return (
        <div className="stories-container">
            <div className="stories-grid">
                {articles.map((article) => (
                    <NewsCard key={article.url} article={article} />
                ))}
            </div>
        </div>
    );
}

export default NewsFeed;
