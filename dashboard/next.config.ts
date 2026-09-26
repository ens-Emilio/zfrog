import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dashboard Dockerfile copies .next/standalone, which Next only emits with
  // this flag — without it the image build fails at that COPY.
  output: "standalone",
  // Pin the Turbopack root to this app so Next does not walk up to $HOME
  // looking for lockfiles (which triggers a "would include your home
  // directory" warning on every dev start).
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
