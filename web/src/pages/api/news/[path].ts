import type { NextApiRequest, NextApiResponse } from 'next';

const BACKEND = process.env.BACKEND_API_URL ?? 'http://localhost:8000';

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

    try {
        const upstream = await fetch(url);
        const body = await upstream.text();
        // Forward the upstream status instead of flattening everything to 200,
        // so the page can distinguish "backend down" from "no articles yet".
        res.status(upstream.status)
            .setHeader('Content-Type', upstream.headers.get('content-type') ?? 'application/json')
            .send(body);
    } catch {
        res.status(502).json({ error: 'backend unreachable', target: url });
    }
}
