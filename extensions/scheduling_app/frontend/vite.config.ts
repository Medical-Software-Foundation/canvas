import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `base` makes the built index.html reference assets at the plugin's asset
// route, e.g. <script src="/plugin-io/api/scheduling_app/app/assets/app.js">.
// Output is flattened to fixed, unhashed names (app.js, app.css) at the dist
// root so the single-segment `/app/assets/<filename>` route can serve them.
export default defineConfig({
  plugins: [react()],
  base: "/plugin-io/api/scheduling_app/app/assets/",
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "dist",
    assetsDir: ".",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "app.js",
        assetFileNames: "[name][extname]",
      },
    },
  },
});
