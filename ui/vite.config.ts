import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const at = (path: string) => fileURLToPath(new URL(path, import.meta.url));
const fixtures = at("../fixtures");

// Everything is bundled locally: no CDN, no remote fonts (FR-6.14, API-3).
// `--mode demo` builds the M5 demo: the synthetic licence sample, relative paths, written next to
// the product page (install/build_site.py). Any other mode builds the window the server serves.
// A static host sends none of the server's headers (nabu/server/app.py), so the demo carries the
// same policy as a meta tag. frame-ancestors is left out: it is ignored in a meta tag, and the
// product page frames the demo.
const DEMO_CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; " +
  "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'";

export default defineConfig(({ mode }) => {
  const demo = mode === "demo";
  return {
    base: demo ? "./" : "/",
    plugins: demo
      ? [
          {
            name: "nabu-demo-csp",
            transformIndexHtml: (html: string) =>
              html.replace(
                '<meta charset="utf-8" />',
                `<meta charset="utf-8" />\n    <meta http-equiv="Content-Security-Policy" content="${DEMO_CSP}" />`,
              ),
          },
        ]
      : [],
    publicDir: demo ? at("../fixtures/demo/public") : false,
    resolve: {
      alias: {
        "@fixtures": fixtures,
        "@sample": demo ? at("../fixtures/demo/working_result.licence.json") : at("../fixtures/working_result.sample.json"),
      },
    },
    server: { host: "127.0.0.1", port: 5173, fs: { allow: [".."] } },
    build: {
      outDir: demo ? at("../dist/site/demo") : at("../src/nabu/server/ui_dist"),
      emptyOutDir: true,
      assetsInlineLimit: 0, // no data: URLs for scripts; CSP keeps script-src 'self'
      modulePreload: { polyfill: false }, // the polyfill is an inline script, which CSP blocks
      sourcemap: false,
    },
  };
});
