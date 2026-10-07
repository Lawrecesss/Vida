import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Traces the server's real imports into .next/standalone so the Docker
  // runtime stage can ship without a node_modules of its own. Harmless
  // outside Docker: `next dev` and `next start` ignore it.
  output: "standalone",
  experimental: {
    // Enables React's <ViewTransition>. The component ships with React; this
    // flag is what wires Next's own transitions up to it.
    viewTransition: true,
  },
};

export default nextConfig;
