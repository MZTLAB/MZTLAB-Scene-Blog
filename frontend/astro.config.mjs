import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

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

// Provisioning is single-layer: in production the operator-maintained nginx
// routes /api and /media to FastAPI and everything else to this Astro process
// (see docs/EDGE.md). Astro itself no longer proxies API/media traffic.
//
// Local development is the one exception: the Vite dev server forwards /api and
// /media to FastAPI so the browser keeps one same-origin address. The proxy is
// dev-only (`apply: 'serve'` semantics of vite.server) and `xfwd: false` keeps
// client-supplied forwarding headers out of the request.
const apiInternalUrl = process.env.BLOG_API_INTERNAL_URL || 'http://127.0.0.1:8000';

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
    // `BLOG_CSS_UNMINIFIED=1` keeps CSS unminified for the cascade-equivalence
    // snapshot (`scripts/css/snapshot.mjs`): lightningcss merges shorthand and
    // longhand declarations, which makes declaration-level comparison noisy.
    build: process.env.BLOG_CSS_UNMINIFIED === '1' ? { cssMinify: false } : {},
    server: {
      host: process.env.HOST || '127.0.0.1',
      fs: {
        strict: true,
        // Never serve dotfiles or private keys from the dev server.
        deny: ['.env', '.env.*', '*.pem', '**/.git/**'],
      },
      proxy: {
        '/api': { target: apiInternalUrl, changeOrigin: false, xfwd: false },
        '/media': { target: apiInternalUrl, changeOrigin: false, xfwd: false },
      },
    },
    plugins: [blockSensitiveDevFiles],
  },
});
