import type { NextApiRequest, NextApiResponse } from 'next';

const BACKEND = process.env.BACKEND_API_URL ?? 'http://localhost:8000';

export const config = {
    api: {
        // SSE must not be buffered by the framework, or events arrive in a
        // single burst when the connection finally closes.
        responseLimit: false,
    },
};

/**
 * Proxies /api/news/<path> to the Flask API so the browser only ever talks to
 * the Next origin (no CORS setup, and the backend host stays server-side).
 */
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
    if (req.method !== 'GET') {
        res.setHeader('Allow', ['GET']);
        return res.status(405).end(`Method ${req.method} Not Allowed`);
    }

    const { path, ...query } = req.query;
    const segments = Array.isArray(path) ? path.join('/') : path ?? '';
    const qs = new URLSearchParams(query as Record<string, string>).toString();
    const url = `${BACKEND}/api/${segments}${qs ? `?${qs}` : ''}`;

    // The client going away must abort the upstream request too, or the API
    // keeps generating events for a stream nobody is reading. Listen on the
    // *response*: req's 'close' fires as soon as the request body ends, which
    // for a GET is immediately, and would abort the stream before it started.
    const controller = new AbortController();
    res.on('close', () => controller.abort());

    try {
        const upstream = await fetch(url, { signal: controller.signal });
        const contentType = upstream.headers.get('content-type') ?? 'application/json';

        if (contentType.includes('text/event-stream') && upstream.body) {
            res.writeHead(upstream.status, {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache, no-transform',
                Connection: 'keep-alive',
                'X-Accel-Buffering': 'no',
            });
            // Read the web stream and write chunks straight through. Going via
            // Readable.fromWeb looked tidier but is undefined once Next bundles
            // the route, and buffering with .text() would defeat streaming.
            const reader = upstream.body.getReader();
            try {
                for (;;) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    res.write(value);
                }
            } catch {
                // Client hung up or upstream died; either way the stream is over.
            } finally {
                reader.cancel().catch(() => {});
                res.end();
            }
            return;
        }

        const body = await upstream.text();
        // Forward the upstream status instead of flattening everything to 200,
        // so the page can distinguish "backend down" from "no articles yet".
        res.status(upstream.status).setHeader('Content-Type', contentType).send(body);
    } catch (err) {
        const error = err as Error;
        if (error.name === 'AbortError') return res.end();
        // Carry the reason: "unreachable" alone sent me chasing networking for
        // a bug that was in this handler.
        console.error(`proxy error for ${url}:`, error);
        res.status(502).json({
            error: 'backend unreachable',
            target: url,
            reason: `${error.name}: ${error.message}`,
        });
    }
}
