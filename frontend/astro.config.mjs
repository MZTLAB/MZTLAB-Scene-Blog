import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import { fileURLToPath } from 'node:url';

// Astro 7's Vite 8 dev SSR runner evaluates some CommonJS-only dependencies
// inline, which breaks because `require` is unavailable in that context. In
// development only, route those few packages through Node's native require()
// with tiny ESM bridges. Production bundling uses the real packages.
const cjsBridges = {
  picomatch: fileURLToPath(new URL('./src/lib/picomatch-esm.mjs', import.meta.url)),
  yaml: fileURLToPath(new URL('./src/lib/yaml-esm.mjs', import.meta.url)),
  eventemitter3: fileURLToPath(new URL('./src/lib/eventemitter3-esm.mjs', import.meta.url)),
};

const cjsBridgePlugin = {
  name: 'mztlab-cjs-dev-bridges',
  apply: 'serve',
  enforce: 'pre',
  resolveId(source) {
    return cjsBridges[source] || null;
  },
};

// The Astro server is the single public entry point. It renders pages and
// proxies /api and /media to FastAPI (see src/pages/api and src/pages/media).
export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  server: {
    host: process.env.HOST || '127.0.0.1',
    port: Number(process.env.PORT || 4321),
  },
  devToolbar: { enabled: false },
  compressHTML: true,
  build: {
    inlineStylesheets: 'auto',
  },
  vite: {
    server: {
      host: process.env.HOST || '127.0.0.1',
    },
    plugins: [cjsBridgePlugin],
  },
});
