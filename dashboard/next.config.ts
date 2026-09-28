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
  // `zfrog dev` prints both `localhost` and `127.0.0.1`, and Next blocks its dev
  // resources (including the HMR socket, and hydration with it) for any other
  // origin by default. Both are listed so opening either one works.
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};

export default nextConfig;
