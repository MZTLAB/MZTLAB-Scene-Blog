#!/usr/bin/env node
/**
 * CSS cascade snapshot.
 *
 * Renders every representative route from a running Astro server, collects the
 * stylesheets that page actually links, and computes 鈥?for each element and
 * CSS property 鈥?which declaration wins (layer / specificity / order /
 * !important). Snapshots are gzipped JSON and compared with `diff.mjs`.
 *
 * This is the safety net for the CSS refactor: if a snapshot diff is empty the
 * rendered cascade is byte-for-byte identical for every probed element.
 *
 * Usage:
 *   node scripts/css/snapshot.mjs --out .tmp/css-snap/baseline.json.gz
 *     [--base http://127.0.0.1:4322] [--api http://127.0.0.1:18123]
 *     [--admin-user smoke-admin --admin-password '...']
 *     [--routes routes.txt] [--widths 1440,390] [--no-admin]
 */

import { gzipSync } from 'node:zlib';
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { parseStylesheet, createParseState } from './lib/css.mjs';
import { parseHtml, walkElements, isTag, getAttribute } from './lib/html.mjs';
import {
  prepareSelector,
  mediaMatches,
  priorityOf,
  comparePriority,
  makeLayerRankLookup,
} from './lib/cascade.mjs';

const SKIP_TAGS = new Set([
  'head',
  'meta',
  'title',
  'link',
  'script',
  'style',
  'base',
  'template',
  'noscript',
]);

// Generated token files (`tokens/colors.css`, `tokens/typography.css`) hold
// literal values; resolve `var(--token)` references to them here so the cascade
// snapshot compares rendered values (13px, rgba()) rather than token names.
const LITERAL_TOKENS = (() => {
  const map = new Map();
  for (const relativePath of [
    '../../src/styles/tokens/colors.css',
    '../../src/styles/tokens/typography.css',
  ]) {
    try {
      const text = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
      for (const match of text.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) {
        const value = match[2].trim();
        if (/^(#[0-9a-f]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[0-9.]+(px|rem|em|%))$/i.test(value))
          map.set(match[1], value);
      }
    } catch {
      // token files are optional for other checkouts
    }
  }
  return map;
})();

function resolveTokenValues(value, depth = 0) {
  if (!LITERAL_TOKENS.size || typeof value !== 'string' || depth > 4) return value;
  const next = value.replace(
    /var\((--[a-z0-9-]+)\)/g,
    (whole, name) => LITERAL_TOKENS.get(name) ?? whole,
  );
  return next === value ? next : resolveTokenValues(next, depth + 1);
}

const DEFAULT_ENVS = [
  { id: 'desktop', width: 1440, reducedMotion: false, dark: false },
  { id: 'mobile', width: 390, reducedMotion: false, dark: false },
  { id: 'desktop-reduced-motion', width: 1440, reducedMotion: true, dark: false },
];

const THEME_VARIANTS = [
  {
    id: 'scene-light',
    attrs: { 'data-palette': 'scene', 'data-color-mode': 'light', 'data-font': 'mono' },
  },
  {
    id: 'scene-dark',
    attrs: { 'data-palette': 'scene', 'data-color-mode': 'dark', 'data-font': 'mono' },
  },
  {
    id: 'stone-light',
    attrs: { 'data-palette': 'stone', 'data-color-mode': 'light', 'data-font': 'mono' },
  },
  {
    id: 'sand-light',
    attrs: { 'data-palette': 'sand', 'data-color-mode': 'light', 'data-font': 'mono' },
  },
  {
    id: 'night',
    attrs: { 'data-palette': 'night', 'data-color-mode': 'light', 'data-font': 'mono' },
  },
  {
    id: 'serif',
    attrs: { 'data-palette': 'scene', 'data-color-mode': 'light', 'data-font': 'serif' },
  },
];

function parseArgs(argv) {
  const args = {
    base: 'http://127.0.0.1:4322',
    api: 'http://127.0.0.1:18123',
    out: '.tmp/css-snap/snapshot.json.gz',
    routesFile: null,
    widths: '1440,390',
    adminUser: process.env.CSS_ADMIN_USER ?? 'smoke-admin',
    adminPassword: process.env.CSS_ADMIN_PASSWORD ?? 'Sm0ke-Test-Passphrase!',
    includeAdmin: true,
    maxRoutes: Infinity,
  };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => argv[++i];
    if (arg === '--base') args.base = next();
    else if (arg === '--api') args.api = next();
    else if (arg === '--out') args.out = next();
    else if (arg === '--routes') args.routesFile = next();
    else if (arg === '--widths') args.widths = next();
    else if (arg === '--admin-user') args.adminUser = next();
    else if (arg === '--admin-password') args.adminPassword = next();
    else if (arg === '--no-admin') args.includeAdmin = false;
    else if (arg === '--max-routes') args.maxRoutes = Number(next());
    else throw new Error(`unknown argument: ${arg}`);
  }
  args.base = args.base.replace(/\/$/, '');
  args.api = args.api.replace(/\/$/, '');
  return args;
}

function splitDeclarations(text) {
  const out = [];
  let depth = 0;
  let quote = null;
  let current = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      current += ch;
      if (ch === quote && text[i - 1] !== '\\') quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth--;
    if (ch === ';' && depth === 0) {
      out.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  if (current.trim()) out.push(current);
  return out;
}

function parseInlineStyle(text) {
  const result = [];
  for (const decl of splitDeclarations(text || '')) {
    const colon = decl.indexOf(':');
    if (colon === -1) continue;
    const prop = decl.slice(0, colon).trim();
    let value = decl.slice(colon + 1).trim();
    if (!prop || !value) continue;
    const important = /!\s*important\s*$/i.test(value);
    if (important) value = value.replace(/!\s*important\s*$/i, '').trim();
    result.push({ prop: prop.startsWith('--') ? prop : prop.toLowerCase(), value, important });
  }
  return result;
}

function elementPath(element, parentPath, elementIndex) {
  const tag = element.name;
  if (!parentPath) return tag;
  return `${parentPath}>${tag}:${elementIndex}`;
}

function walkWithPaths(node, parentPath, visit) {
  let index = 0;
  for (const child of node.children ?? []) {
    if (!isTag(child)) continue;
    index += 1;
    const path = elementPath(child, parentPath, index);
    visit(child, path);
    walkWithPaths(child, path, visit);
  }
}

async function fetchText(url, options) {
  const response = await fetch(url, options);
  const body = await response.text();
  return { response, body };
}

async function login(api, username, password) {
  const response = await fetch(`${api}/api/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'X-Blog-Request': '1' },
    body: JSON.stringify({ username, password }),
    redirect: 'manual',
  });
  if (!response.ok) {
    throw new Error(`login failed: ${response.status} ${await response.text()}`);
  }
  const cookies = response.headers.getSetCookie?.() ?? [];
  return cookies.map((entry) => entry.split(';')[0]).join('; ');
}

function collectStyles(document) {
  const styles = [];
  const visit = (node) => {
    for (const child of node.children ?? []) {
      if (!isTag(child)) continue;
      if (child.name === 'link' && /(^|\s)stylesheet(\s|$)/i.test(getAttribute(child, 'rel'))) {
        const href = getAttribute(child, 'href');
        if (href) styles.push({ type: 'link', href });
        continue;
      }
      if (child.name === 'style') {
        const text = (child.children ?? [])
          .filter((n) => n.type === 'text')
          .map((n) => n.data)
          .join('');
        styles.push({ type: 'inline', text });
        continue;
      }
      visit(child);
    }
  };
  visit(document);
  return styles;
}

function deepestHtml(document) {
  let found = null;
  const visit = (node) => {
    for (const child of node.children ?? []) {
      if (!isTag(child)) continue;
      if (child.name === 'html') found = child;
      else visit(child);
    }
  };
  visit(document);
  return found;
}

function applyTheme(htmlElement, attrs) {
  for (const [key, value] of Object.entries(attrs)) htmlElement.attribs[key] = value;
}

function serializeWinners(winners) {
  const entries = [...winners.entries()]
    .filter(([, winner]) => winner && typeof winner === 'object' && winner.value !== undefined)
    .map(([prop, winner]) => [prop, resolveTokenValues(winner.value)])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return entries.map(([prop, value]) => `${prop}=${value}`).join(';');
}

function buildCandidates(declarations, env, layerRank, unsupportedSelectors) {
  const byClass = new Map();
  const byId = new Map();
  const byTag = new Map();
  const generic = [];
  let activeCount = 0;
  let removedByMedia = 0;
  const push = (map, key, item) => {
    let list = map.get(key);
    if (!list) {
      list = [];
      map.set(key, list);
    }
    list.push(item);
  };
  for (const declaration of declarations) {
    if (!mediaMatches(declaration.media, env, unsupportedSelectors.media)) {
      removedByMedia += 1;
      continue;
    }
    const prepared = declaration.prepared;
    if (!prepared || prepared.error || !prepared.compiled) {
      unsupportedSelectors.selectors?.add(prepared?.raw ?? declaration.selectorText);
      continue;
    }
    activeCount += 1;
    const item = {
      ...declaration,
      compiled: prepared.compiled,
      pseudo: prepared.pseudo,
      stateful: prepared.stateful,
      specificity: prepared.specificity,
      priority: null,
    };
    item.priority = priorityOf(item, layerRank);
    if (prepared.bucket.type === 'class') push(byClass, prepared.bucket.value, item);
    else if (prepared.bucket.type === 'id') push(byId, prepared.bucket.value, item);
    else if (prepared.bucket.type === 'tag') push(byTag, prepared.bucket.value, item);
    else generic.push(item);
  }
  return { byClass, byId, byTag, generic, activeCount, removedByMedia };
}

function computeStyleForElement(element, candidates, env, layerRank, sinks) {
  const seen = new Set();
  const consider = [];
  const id = element.attribs.id;
  const classes = (element.attribs.class ?? '').split(/\s+/).filter(Boolean);
  if (id && candidates.byId.has(id))
    for (const item of candidates.byId.get(id)) consider.push(item);
  if (candidates.byTag.has(element.name))
    for (const item of candidates.byTag.get(element.name)) consider.push(item);
  for (const cls of classes) {
    const list = candidates.byClass.get(cls);
    if (list) for (const item of list) consider.push(item);
  }
  for (const item of candidates.generic) consider.push(item);

  const inline = parseInlineStyle(element.attribs.style);
  if (inline.length) {
    for (const decl of inline) {
      const item = {
        ...decl,
        inline: true,
        layer: [],
        media: [],
        specificity: 0,
        order: 0,
        stateful: false,
        pseudo: null,
        compiled: () => true,
      };
      item.priority = priorityOf(item, layerRank);
      consider.push(item);
    }
  }

  for (const item of consider) {
    if (seen.has(item)) continue;
    seen.add(item);
    if (!item.inline && !item.compiled(element)) continue;
    const key = item.pseudo
      ? `${item.stateful ? 'state:' : ''}pseudo:${item.pseudo}`
      : item.stateful
        ? 'state'
        : 'normal';
    const sink = sinks.get(key) ?? new Map();
    if (!sinks.has(key)) sinks.set(key, sink);
    const previous = sink.get(item.prop);
    if (!previous || comparePriority(item.priority, previous.priority) >= 0) {
      sink.set(item.prop, {
        priority: item.priority,
        value: `${item.value}${item.important ? ' !imp' : ''}`,
      });
    }
  }
}

function deepRoute(url) {
  return url;
}

function buildRoutesFromBootstrap(bootstrap, adminIds) {
  const urls = new Set();
  const walk = (value) => {
    if (typeof value === 'string') {
      if (/^\/(posts|galleries|projects)\/[^/]+$/.test(value)) urls.add(value);
      return;
    }
    if (value && typeof value === 'object') for (const child of Object.values(value)) walk(child);
  };
  walk(bootstrap);
  const pick = (prefix) => [...urls].filter((u) => u.startsWith(prefix));
  const routes = new Set(['/', '/photos', '/archive', '/search', '/projects', '/404']);
  const post = pick('/posts/')[0];
  const gallery = pick('/galleries/')[0];
  const project = pick('/projects/')[0];
  if (post) routes.add(post);
  if (gallery) routes.add(gallery);
  if (project) routes.add(project);
  const tags = new Set();
  for (const item of bootstrap?.page?.posts ?? [])
    for (const tag of item.tags ?? []) tags.add(`/tags/${encodeURIComponent(tag.slug)}`);
  const categories = new Set();
  for (const item of bootstrap?.page?.posts ?? [])
    for (const category of item.categories ?? [])
      categories.add(`/categories/${encodeURIComponent(category.slug)}`);
  if (tags.size) routes.add([...tags].sort()[0]);
  if (categories.size) routes.add([...categories].sort()[0]);
  routes.add('/about');
  if (adminIds?.postId) {
    for (const route of [
      '/admin',
      '/admin/posts',
      `/admin/posts/${adminIds.postId}`,
      '/admin/projects',
      adminIds.projectId ? `/admin/projects/${adminIds.projectId}` : null,
      '/admin/pages',
      '/admin/galleries',
      adminIds.galleryId ? `/admin/galleries/${adminIds.galleryId}` : null,
      '/admin/media',
      '/admin/taxonomy',
      '/admin/appearance',
      '/admin/settings',
      '/admin/users',
      '/admin/profile',
      '/admin/login',
    ]) {
      if (route) routes.add(route);
    }
  }
  return [...routes].sort();
}

function encodeUrl(url) {
  return url.replace(/[^\x20-\x7e]/g, (ch) => encodeURIComponent(ch));
}

async function main() {
  const args = parseArgs(process.argv);
  const envs = args.widths
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value))
    .map((width, index) => ({
      id: index === 0 ? `${width}` : `${width}`,
      width,
      reducedMotion: false,
      dark: false,
    }));
  envs.push({ id: 'reduced-motion', width: envs[0].width, reducedMotion: true, dark: false });

  let cookie = '';
  let adminIds = null;
  if (args.includeAdmin) {
    try {
      cookie = await login(args.api, args.adminUser, args.adminPassword);
      const authFetch = (url) =>
        fetch(url, { headers: { cookie } }).then((response) => {
          if (!response.ok) throw new Error(`${response.status} ${url}`);
          return response.json();
        });
      const [posts, galleries] = await Promise.all([
        authFetch(`${args.api}/api/admin/posts?page=1&page_size=3`).catch(() => null),
        authFetch(`${args.api}/api/admin/galleries?page=1&page_size=3`).catch(() => null),
      ]);
      adminIds = {
        postId: posts?.items?.[0]?.id ?? 1,
        galleryId: galleries?.items?.[0]?.id ?? 1,
        projectId: 4,
      };
    } catch (error) {
      console.log(`[snapshot] admin login failed, admin routes skipped: ${error.message}`);
    }
  }

  let routes;
  if (args.routesFile) {
    routes = readFileSync(args.routesFile, 'utf8')
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#'));
  } else {
    const response = await fetch(`${args.api}/api/bootstrap`);
    const bootstrap = await response.json();
    routes = buildRoutesFromBootstrap(bootstrap, adminIds);
  }
  if (Number.isFinite(args.maxRoutes)) routes = routes.slice(0, args.maxRoutes);

  const cssCache = new Map();
  const cssFileInfo = {};
  const pageResults = {};
  const cacheBust = `fit=${Date.now()}`;

  for (const route of routes) {
    const started = Date.now();
    const url = args.base + encodeUrl(route);
    const headers = { 'cache-control': 'no-cache' };
    // The login page is only reachable signed-out; request it anonymously.
    if (cookie && route !== '/admin/login') headers.cookie = cookie;
    const { response, body } = await fetchText(url, { headers, redirect: 'manual' });
    if (response.status >= 300 && response.status < 400) {
      pageResults[route] = { status: response.status, redirect: response.headers.get('location') };
      console.log(`[snapshot] ${route} -> ${response.status} ${response.headers.get('location')}`);
      continue;
    }

    const document = parseHtml(body);
    const styles = collectStyles(document);
    const state = createParseState();
    const declarations = [];
    const stylesheetList = [];
    let rawBytes = 0;
    let gzipBytes = 0;

    for (const style of styles) {
      if (style.type === 'inline') {
        declarations.push(...parseStylesheet(style.text, state));
        stylesheetList.push({ type: 'inline', bytes: Buffer.byteLength(style.text) });
        continue;
      }
      const href = new URL(style.href, args.base).toString();
      let entry = cssCache.get(href);
      if (!entry) {
        const cssResponse = await fetch(href, { headers });
        const text = await cssResponse.text();
        entry = { text, bytes: Buffer.byteLength(text), gzip: gzipSync(Buffer.from(text)).length };
        cssCache.set(href, entry);
        cssFileInfo[style.href] = { bytes: entry.bytes, gzip: entry.gzip };
      }
      declarations.push(...parseStylesheet(entry.text, state));
      stylesheetList.push({ href: style.href, bytes: entry.bytes, gzip: entry.gzip });
      rawBytes += entry.bytes;
      gzipBytes += entry.gzip;
    }

    // Resolve selectors once.
    const preparedBySelector = new Map();
    for (const declaration of declarations) {
      let prepared = preparedBySelector.get(declaration.selectorText);
      if (!prepared) {
        prepared = prepareSelector(declaration.selectorText);
        preparedBySelector.set(declaration.selectorText, prepared);
      }
      declaration.prepared = prepared;
    }

    const layerRank = makeLayerRankLookup(state.layerOrder);
    const htmlElement = deepestHtml(document);
    const unsupported = { media: new Set(), selectors: new Set() };

    // Token snapshot: only declarations that can match <html>, captured per
    // viewport (responsive token overrides) and per palette/colour-mode.
    const tokenDeclarations = declarations.filter((declaration) => {
      if (declaration.prepared?.error) return false;
      const bucket = declaration.prepared?.bucket;
      return (
        bucket && (bucket.type === 'generic' || (bucket.type === 'tag' && bucket.value === 'html'))
      );
    });
    const tokens = {};
    if (htmlElement) {
      const originalAttrs = { ...htmlElement.attribs };
      for (const env of envs) {
        const envTokens = {};
        const tokenCandidates = buildCandidates(tokenDeclarations, env, layerRank, unsupported);
        for (const variant of THEME_VARIANTS) {
          applyTheme(htmlElement, variant.attrs);
          const sinks = new Map();
          computeStyleForElement(htmlElement, tokenCandidates, env, layerRank, sinks);
          const normal = sinks.get('normal') ?? new Map();
          const serialized = {};
          for (const [prop, value] of normal) {
            if (prop.startsWith('--') || prop === 'color-scheme') serialized[prop] = value.value;
          }
          envTokens[variant.id] = serialized;
        }
        tokens[env.id] = envTokens;
      }
      Object.assign(htmlElement.attribs, originalAttrs);
    }

    const envResults = {};
    for (const env of envs) {
      const candidates = buildCandidates(declarations, env, layerRank, unsupported);
      const elements = {};
      const states = {};
      const pseudos = {};
      const dom = {};
      walkWithPaths(document, null, (element, path) => {
        if (SKIP_TAGS.has(element.name)) return;
        const classes = (element.attribs.class ?? '').split(/\s+/).filter(Boolean).sort();
        const signature = `${element.name}${classes.length ? '.' + classes.join('.') : ''}${element.attribs.id ? '#' + element.attribs.id : ''}`;
        dom[path] = signature;
        const sinks = new Map();
        computeStyleForElement(element, candidates, env, layerRank, sinks);
        const normal = sinks.get('normal');
        if (normal && normal.size) elements[path] = serializeWinners(normal);
        const stateSink = sinks.get('state');
        if (stateSink && stateSink.size) states[path] = serializeWinners(stateSink);
        for (const [key, sink] of sinks) {
          if (!key.startsWith('pseudo:') && !key.startsWith('state:pseudo:')) continue;
          pseudos[`${path}::${key}`] = serializeWinners(sink);
        }
      });
      envResults[env.id] = {
        elements,
        states,
        pseudos,
        dom,
        activeDeclarations: candidates.activeCount,
        declarations: declarations.length,
      };
    }

    pageResults[route] = {
      status: response.status,
      stylesheets: stylesheetList,
      cssBytes: rawBytes,
      cssGzip: gzipBytes,
      tokens,
      envs: envResults,
      ms: Date.now() - started,
    };
    console.log(
      `[snapshot] ${route} status=${response.status} css=${(rawBytes / 1024).toFixed(1)}KB gz=${(gzipBytes / 1024).toFixed(1)}KB elements=${Object.keys(envResults[envs[0].id]?.elements ?? {}).length} (${Date.now() - started}ms)`,
    );
  }

  const payload = {
    meta: {
      generatedAt: new Date().toISOString(),
      base: args.base,
      api: args.api,
      routes,
      envs: envs.map((env) => ({ id: env.id, width: env.width, reducedMotion: env.reducedMotion })),
      themes: THEME_VARIANTS.map((variant) => variant.id),
      cssFiles: cssFileInfo,
      unsupported: {
        media: [...new Set([...Object.values(pageResults)].flatMap(() => []))],
      },
    },
    routes: pageResults,
  };

  mkdirSync(dirname(args.out), { recursive: true });
  writeFileSync(args.out, gzipSync(Buffer.from(JSON.stringify(payload))));
  const size = Buffer.byteLength(JSON.stringify(payload));
  console.log(
    `[snapshot] wrote ${args.out} (${(size / 1024 / 1024).toFixed(2)}MB json, ${(Buffer.byteLength(gzipSync(Buffer.from(JSON.stringify(payload)))) / 1024).toFixed(0)}KB gzip)`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
