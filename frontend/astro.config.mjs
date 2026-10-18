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

// Astro/Vite's dev server intentionally exposes source files. The audit report
// showed /src/*, /astro.config.mjs and /package.json were downloadable. These
// files are only reachable while running `astro dev`, so production must use
// the built server; in development we at least refuse the configuration files
// that are not needed by the browser at all.
const SENSITIVE_DEV_PATHS = [
  /^\/package-lock\.json$/,
  /^\/package\.json$/,
  /^\/astro\.config\.mjs$/,
  /^\/tsconfig\.json$/,
  /^\/\.env(\..*)?$/,
  /\/\.env(\..*)?$/,
];

const blockSensitiveDevFiles = {
  name: 'mztlab-block-sensitive-dev-files',
  apply: 'serve',
  configureServer(server) {
    server.middlewares.use((request, response, next) => {
      const path = (request.url || '').split('?')[0];
      if (SENSITIVE_DEV_PATHS.some((pattern) => pattern.test(path))) {
        response.statusCode = 404;
        response.setHeader('content-type', 'text/plain; charset=utf-8');
        response.end('Not found');
        return;
      }
      next();
    });
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
    // Source maps would make the production bundle as readable as the source.
    sourcemap: false,
  },
  vite: {
    server: {
      host: process.env.HOST || '127.0.0.1',
      fs: {
        strict: true,
        // Never serve dotfiles or private keys from the dev server.
        deny: ['.env', '.env.*', '*.pem', '**/.git/**'],
      },
    },
    plugins: [cjsBridgePlugin, blockSensitiveDevFiles],
  },
});
