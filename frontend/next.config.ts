import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'export',
  // API calls go to the same origin (FastAPI backend)
  // In dev mode, proxy to the deployed backend
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.NODE_ENV === 'production'
          ? '/api/:path*'
          : 'https://ai-shopkeeper-kk.fly.dev/api/:path*',
      },
    ];
  },
};

export default nextConfig;
