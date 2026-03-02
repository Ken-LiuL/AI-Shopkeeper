import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'export',
  // Static export doesn't support rewrites
  // API base URL is handled in lib/api.ts
};

export default nextConfig;
