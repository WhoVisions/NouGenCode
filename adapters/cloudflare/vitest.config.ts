import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [cloudflareTest({ wrangler: { configPath: "./wrangler.jsonc" } })],
  server: {
    // The shared canonical-JSON vectors live in the repo's Python test tree.
    fs: { allow: ["../.."] },
  },
});
