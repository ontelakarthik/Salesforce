import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone server output for the production Docker image (Dockerfile
  // copies .next/standalone rather than shipping node_modules).
  output: "standalone",
};

export default nextConfig;
