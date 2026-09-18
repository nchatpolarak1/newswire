import NewsCard from "@/components/NewsCard";
import { Story } from "@/utils/types";

interface NewsFeedProps {
    stories: Story[];
}

function NewsFeed({ stories }: NewsFeedProps) {
    if (stories.length === 0) return null;

    return (
        <div className="stories-container">
            <div className="stories-grid">
                {stories.map((story) => (
                    <NewsCard key={story.cluster_id} story={story} />
                ))}
            </div>
        </div>
    );
}

export default NewsFeed;
