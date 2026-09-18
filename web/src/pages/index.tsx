import { useEffect, useState } from "react";

import FeaturedNewsCard from "@/components/FeaturedNews";
import NewsCard from "@/components/NewsCard";
import NewsFeed from "@/components/NewsFeed";
import { Article } from "@/utils/types";

export default function Feed() {
    const [articles, setArticles] = useState<Article[]>([]);
    const [featured, setFeatured] = useState<Article | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const controller = new AbortController();

        fetch("/api/news/feed", { signal: controller.signal })
            .then((res) => {
                if (!res.ok) throw new Error(`feed responded ${res.status}`);
                return res.json();
            })
            .then((data: Article[]) => {
                setArticles(data);
                setFeatured(data[0] ?? null);
            })
            .catch((err) => {
                if (err.name !== "AbortError") setError(err.message);
            })
            .finally(() => setLoading(false));

        return () => controller.abort();
    }, []);

    if (loading) {
        return <p className="p-8 text-center">Loading feed…</p>;
    }

    // The pipeline is the source of truth; an empty feed means nothing has been
    // ingested yet rather than an error worth shouting about.
    if (error || articles.length === 0) {
        return (
            <div className="p-8 text-center">
                <p className="text-xl font-semibold">No stories yet</p>
                <p className="pt-2 text-sm">
                    {error
                        ? `Could not reach the API (${error}).`
                        : "The poller has not ingested anything yet."}{" "}
                    Start the pipeline with <code>docker compose up</code>.
                </p>
            </div>
        );
    }

    return (
        <div className="grid grid-cols-4 space-x-2 space-y-2 pt-2">
            <div className="col-span-4 lg:col-span-3">
                {featured && <FeaturedNewsCard article={featured} />}
                <NewsFeed articles={articles.slice(1)} />
            </div>
            <aside className="hidden overflow-hidden border-l border-slate-300 lg:col-span-1 lg:block">
                <div className="flex flex-col gap-4 space-x-2 divide-y divide-slate-300">
                    {articles.slice(-6).map((article) => (
                        <NewsCard key={article.url} article={article} />
                    ))}
                </div>
            </aside>
        </div>
    );
}
