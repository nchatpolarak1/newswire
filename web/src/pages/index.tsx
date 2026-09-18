import { useCallback, useEffect, useRef, useState } from "react";

import FeaturedNewsCard from "@/components/FeaturedNews";
import NewsCard from "@/components/NewsCard";
import NewsFeed from "@/components/NewsFeed";
import { FeedResponse, Story } from "@/utils/types";

export default function Feed() {
    const [stories, setStories] = useState<Story[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [liveCount, setLiveCount] = useState(0);

    // Read inside the SSE handler without making the effect depend on it --
    // otherwise every arriving story would tear down and reopen the stream.
    const seenIds = useRef<Set<number>>(new Set());

    const loadPage = useCallback(async (nextCursor: string | null) => {
        const query = nextCursor ? `?limit=30&cursor=${encodeURIComponent(nextCursor)}` : "?limit=30";
        const res = await fetch(`/api/news/feed${query}`);
        if (!res.ok) throw new Error(`feed responded ${res.status}`);
        return (await res.json()) as FeedResponse;
    }, []);

    useEffect(() => {
        let cancelled = false;

        loadPage(null)
            .then((data) => {
                if (cancelled) return;
                data.stories.forEach((s) => seenIds.current.add(s.cluster_id));
                setStories(data.stories);
                setCursor(data.next_cursor);
            })
            .catch((err) => !cancelled && setError(err.message))
            .finally(() => !cancelled && setLoading(false));

        return () => {
            cancelled = true;
        };
    }, [loadPage]);

    // Live updates. EventSource reconnects on its own, so there is no retry
    // logic here beyond closing it on unmount.
    useEffect(() => {
        const source = new EventSource("/api/news/stream");

        source.addEventListener("story", (event) => {
            const story: Story = JSON.parse((event as MessageEvent).data);
            if (seenIds.current.has(story.cluster_id)) return;
            seenIds.current.add(story.cluster_id);
            setStories((current) => [story, ...current]);
            setLiveCount((n) => n + 1);
        });

        return () => source.close();
    }, []);

    const loadMore = async () => {
        if (!cursor || loadingMore) return;
        setLoadingMore(true);
        try {
            const data = await loadPage(cursor);
            const fresh = data.stories.filter((s) => !seenIds.current.has(s.cluster_id));
            fresh.forEach((s) => seenIds.current.add(s.cluster_id));
            setStories((current) => [...current, ...fresh]);
            setCursor(data.next_cursor);
        } catch (err) {
            setError((err as Error).message);
        } finally {
            setLoadingMore(false);
        }
    };

    if (loading) return <p className="p-8 text-center">Loading feed…</p>;

    if (error && stories.length === 0) {
        return (
            <div className="p-8 text-center">
                <p className="text-xl font-semibold">No stories yet</p>
                <p className="pt-2 text-sm">
                    Could not reach the API ({error}). Start the pipeline with{" "}
                    <code>docker compose up</code>.
                </p>
            </div>
        );
    }

    if (stories.length === 0) {
        return (
            <div className="p-8 text-center">
                <p className="text-xl font-semibold">No stories yet</p>
                <p className="pt-2 text-sm">The poller has not ingested anything yet.</p>
            </div>
        );
    }

    const [featured, ...rest] = stories;

    return (
        <div>
            {liveCount > 0 && (
                <p className="py-1 text-center text-xs text-amber-900">
                    {liveCount} new {liveCount === 1 ? "story" : "stories"} arrived live
                </p>
            )}

            <div className="grid grid-cols-4 space-x-2 space-y-2 pt-2">
                <div className="col-span-4 lg:col-span-3">
                    <FeaturedNewsCard story={featured} />
                    <NewsFeed stories={rest.slice(0, 12)} />

                    {cursor && (
                        <div className="flex justify-center py-4">
                            <button
                                onClick={loadMore}
                                disabled={loadingMore}
                                className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
                            >
                                {loadingMore ? "Loading…" : "Load more stories"}
                            </button>
                        </div>
                    )}
                </div>

                <aside className="hidden overflow-hidden border-l border-slate-300 lg:col-span-1 lg:block">
                    <div className="flex flex-col gap-4 space-x-2 divide-y divide-slate-300">
                        {rest.slice(12, 18).map((story) => (
                            <NewsCard key={story.cluster_id} story={story} compact />
                        ))}
                    </div>
                </aside>
            </div>
        </div>
    );
}
