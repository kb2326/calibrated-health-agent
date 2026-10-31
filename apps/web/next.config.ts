import type { NextConfig } from "next";

// Static export: the FastAPI app (packages/health_web) serves apps/web/out from the same
// origin as /api, so there is no CORS and no separate web server.
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
};

export default config;
