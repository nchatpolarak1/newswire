export interface Article {
    author: string;
    title: string;
    body: string;
    image_url: string;
    url: string;
    /** ISO-8601 string: this crosses the wire as JSON, never as a Date. */
    publish_date: string;
}
