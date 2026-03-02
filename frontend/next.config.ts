import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
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
