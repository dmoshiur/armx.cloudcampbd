/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // The root Docker image copies the traced standalone server and its minimal
  // runtime dependencies. Normal `make dev` / component builds are unchanged.
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  // The browser only ever talks to this origin: /api/* is proxied to FastAPI,
  // so no client-side code needs to know where the backend lives.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
