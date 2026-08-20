import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // Enables React's <ViewTransition>. The component ships with React; this
    // flag is what wires Next's own transitions up to it.
    viewTransition: true,
  },
};

export default nextConfig;
