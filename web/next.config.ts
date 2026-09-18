import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Article images come from whatever outlets the poller ingests, so the host
  // list is not knowable ahead of time. next/image is therefore not used for
  // them; plain <img> keeps the component free of a remotePatterns allowlist.
};

export default nextConfig;
