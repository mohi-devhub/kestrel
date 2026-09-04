import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Traced standalone output so the container image carries only the modules the
  // app actually imports, instead of the whole node_modules tree.
  output: "standalone",
};

export default nextConfig;
