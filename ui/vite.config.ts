import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const fixtures = fileURLToPath(new URL("../fixtures", import.meta.url));
const outDir = fileURLToPath(new URL("../src/nabu/server/ui_dist", import.meta.url));

// Everything is bundled locally: no CDN, no remote fonts (FR-6.14, API-3).
export default defineConfig({
  base: "/",
  resolve: { alias: { "@fixtures": fixtures } },
  server: { host: "127.0.0.1", port: 5173, fs: { allow: [".."] } },
  build: {
    outDir,
    emptyOutDir: true,
    assetsInlineLimit: 0, // no data: URLs for scripts; CSP keeps script-src 'self'
    modulePreload: { polyfill: false }, // the polyfill is an inline script, which CSP blocks
    sourcemap: false,
  },
});
