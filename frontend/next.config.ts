import type { NextConfig } from "next";

// When NEXT_PUBLIC_API_URL is set, we're in standalone server mode (e.g. 192.144.227.205:8000)
// and can use Next.js rewrites for API proxying.
// When unset (fly.io deployment), use static export; API proxy is handled by vercel.json.
const isStandaloneDeployment = !!process.env.NEXT_PUBLIC_API_URL;

const nextConfig: NextConfig = {
  ...(isStandaloneDeployment
    ? {
        // Standalone server mode: enable rewrites for API proxying
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${process.env.NEXT_PUBLIC_API_URL}/api/:path*`,
            },
          ];
        },
      }
    : {
        // fly.io static export mode: rewrites handled by vercel.json
        output: "export",
      }),
};

export default nextConfig;
