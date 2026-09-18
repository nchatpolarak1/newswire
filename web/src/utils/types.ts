/** One article as the API returns it. */
export interface Article {
    id: number;
    url: string;
    title: string;
    body: string;
    author: string;
    source: string;
    image_url: string;
    /** ISO-8601 string: this crosses the wire as JSON, never as a Date. */
    published_at: string | null;
    enrichment: Enrichment | null;
}

/** A story: one cluster, represented by its canonical article. */
export interface Story extends Article {
    cluster_id: number;
    /** How many articles are in the cluster. */
    cluster_size: number;
    /**
     * How many distinct outlets. Not the same as cluster_size -- a cluster can
     * hold several articles from one masthead -- so "covered by N outlets"
     * must use this, or it overstates reach.
     */
    outlet_count: number;
    sources: string[];
}

export interface Entity {
    name: string;
    type: "person" | "organization" | "location" | "other";
    sentiment: "positive" | "negative" | "neutral";
}

export interface Enrichment {
    summary: string;
    topics: string[];
    entities: Entity[];
    tickers: string[];
    importance: number;
    provider: string;
}

export interface FeedResponse {
    stories: Story[];
    next_cursor: string | null;
}

export interface ClusterResponse {
    cluster_id: number;
    member_count: number;
    first_seen: string | null;
    last_seen: string | null;
    articles: Article[];
}
