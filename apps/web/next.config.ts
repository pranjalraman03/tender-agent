import type { NextConfig } from "next";

// Classic request-time rendering (no Cache Components): pages fetch from the FastAPI
// backend on each request. Simpler to reason about for this app; see
// node_modules/next/dist/docs/01-app/02-guides/caching-without-cache-components.md
const nextConfig: NextConfig = {
  // Self-contained server for the Docker image (infra/Dockerfile.web).
  output: "standalone",
  serverExternalPackages: ["pg"],
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
