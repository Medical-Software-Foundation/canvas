import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

// Kept separate from vite.config.ts so the production build's `tsc --noEmit`
// (which type-checks vite.config.ts) isn't exposed to vitest's bundled Vite
// types. vitest loads this file in preference to vite.config.ts and inherits
// its `@` alias / plugins via mergeConfig.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      // A fixed UTC+1 zone (no DST) keeps the timezone-sensitive date tests
      // deterministic — this is the zone that reproduced the launch off-by-one.
      env: { TZ: "Etc/GMT-1" },
    },
  }),
);
