import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces .next/standalone: a server bundle with only the modules it actually imports,
  // which is what the runtime stage of the Dockerfile copies instead of node_modules.
  output: "standalone",
};

export default nextConfig;
