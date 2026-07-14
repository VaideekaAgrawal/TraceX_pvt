import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A stray lockfile in the user's home directory otherwise makes Next.js
  // infer the wrong workspace root (see the build warning this silences).
  // This repo's frontend root is always this directory.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
