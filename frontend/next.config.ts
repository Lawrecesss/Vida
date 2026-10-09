import type { NextConfig } from "next";

const config: NextConfig = {
  // Self-contained server output, so the runtime image needs no node_modules.
  output: "standalone",
};

export default config;
