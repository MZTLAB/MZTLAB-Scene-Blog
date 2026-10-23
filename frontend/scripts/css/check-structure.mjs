#!/usr/bin/env node
/**
 * Structure gate for the finished @layer CSS refactor.
 *
 * Usage: node scripts/css/check-structure.mjs [--strict] [--dir <stylesDir>] [--allow-important <list>]
 *
 * Rules: 1 canonical layer banner first, 2 rules inside a known @layer, 3 size
 * (400 hard / 250 warn), 4 one owner file per selector+prop, 5 no !important,
 * 6 no hardcoded colours outside tokens/, 7 no orphan stylesheet, 8 no legacy
 * root files. `tokens/layers.css` and `styles/archive/` are exempt.
 *
 * Findings print as `ERROR|WARN <file>:<line> <rule> <detail>`; exit 1 only when
 * errors exist and --strict is passed.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createParseState, parseStylesheet } from './lib/css.mjs';

const KNOWN_LAYERS = new Set(['tokens', 'base', 'components', 'pages', 'utilities']);
const LAYERS_FILE = 'tokens/layers.css';
const LEGACY_ROOT = new Set(['global.css', 'mono.css', 'index.css']);
const CANONICAL_BANNER = '@layer tokens, base, components, pages, utilities;';
const BANNER_ANY = /@layer\s+tokens\s*,\s*base\s*,\s*components\s*,\s*pages\s*,\s*utilities\s*;/;
const BANNER_FIRST = /^@layer\s+tokens\s*,\s*base\s*,\s*components\s*,\s*pages\s*,\s*utilities\s*;/;
const [HARD_LINES, WARN_LINES] = [400, 250];
const DEFAULT_DIR = fileURLToPath(new URL('../../src/styles/', import.meta.url));
const HELP =
  'usage: node scripts/css/check-structure.mjs [--strict] [--dir <stylesDir>] ' +
  '[--allow-important <comma list>]';
const findings = [];
const ERROR = (file, line, rule, detail) =>
  findings.push({ level: 'ERROR', file, line, rule, detail });
const WARN = (file, line, rule, detail) =>
  findings.push({ level: 'WARN', file, line, rule, detail });

function parseArgs(argv) {
  const args = { strict: false, dir: DEFAULT_DIR, allowed: [] };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    const value = () => {
      const next = argv[++i];
      if (!next) throw new Error(`${arg} requires a value`);
      return next;
    };
    if (arg === '--strict') args.strict = true;
    else if (arg === '--dir') args.dir = resolve(value());
    else if (arg === '--allow-important')
      args.allowed = value()
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    else if (arg === '--help' || arg === '-h') {
      console.log(HELP);
      process.exit(0);
    } else throw new Error(`unknown argument "${arg}" (try --help)`);
  }
  args.dir = resolve(args.dir);
  return args;
}
function walkCss(dir, rel = '', out = []) {
  const entries = readdirSync(dir, { withFileTypes: true }).sort((a, b) =>
    a.name.localeCompare(b.name),
  );
  for (const entry of entries) {
    const path = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.isDirectory()) walkCss(join(dir, entry.name), path, out);
    else if (entry.isFile() && entry.name.toLowerCase().endsWith('.css'))
      out.push({ abs: join(dir, entry.name), rel: path });
  }
  return out;
}

// Replace comments with spaces so offsets and newlines survive.
const stripComments = (text) =>
  text.replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, ' '));
const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** Colour literals in a value; `var()` fallbacks, url() fragments and strings are ignored. */
function colorLiterals(value) {
  const scrubbed = value
    .replace(/url\([^)]*\)/gi, 'url()')
    .replace(/"[^"]*"|'[^']*'/g, ' ')
    .replace(/var\([^()]*(?:\([^()]*\)[^()]*)*\)/g, 'var()');
  // hex / rgb() / hsl() / oklch() / color() literals; `color-mix(` is not a literal.
  const literals =
    /#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})\b|\b(?:rgba?|hsla?|hsl|oklch|color)\((?:[^()]|\([^()]*\))*\)/gi;
  return [...scrubbed.matchAll(literals)];
}

function isAllowedImportant(args, decl) {
  return args.allowed.some((entry) =>
    [decl.prop, decl.selectorText].some((value) =>
      entry.includes('*')
        ? new RegExp(`^${entry.split('*').map(escapeRe).join('.*')}$`).test(value)
        : entry === value,
    ),
  );
}

/** Best-effort source locator: maps a declaration back to the line it came from. */
function makeLocator(source) {
  const starts = [0];
  for (let i = 0; i < source.length; i++) if (source[i] === '\n') starts.push(i + 1);
  const at = (offset) => {
    let low = 0;
    let high = starts.length - 1;
    while (low < high) {
      const mid = (low + high + 1) >> 1;
      if (starts[mid] <= offset) low = mid;
      else high = mid - 1;
    }
    return low + 1;
  };
  const positions = new Map();
  const occurrences = (selector) => {
    if (positions.has(selector)) return positions.get(selector);
    const pattern = selector.trim().split(/\s+/).map(escapeRe).join('\\s+');
    const found = [...source.matchAll(new RegExp(`(?<![\\w-])${pattern}(?![\\w-])`, 'g'))].map(
      (match) => match.index,
    );
    positions.set(selector, found);
    return found;
  };
  const lineFor = (selector, prop) => {
    const propRe = new RegExp(`(?:^|[;{])\\s*${escapeRe(prop)}\\s*:`, 'i');
    for (const start of occurrences(selector)) {
      const open = source.indexOf('{', start + selector.length);
      if (open < 0) continue;
      let depth = 0;
      let close = -1;
      for (let i = open; i < source.length; i++) {
        if (source[i] === '{') depth++;
        else if (source[i] === '}' && --depth === 0) {
          close = i;
          break;
        }
      }
      const match = propRe.exec(source.slice(open + 1, close < 0 ? source.length : close));
      if (match)
        return at(open + 1 + match.index + match[0].toLowerCase().indexOf(prop.toLowerCase()));
    }
    const found = occurrences(selector);
    return found.length ? at(found[0]) : 1;
  };
  return { at, lineFor };
}
/** Every `.css` specifier quoted in an .astro/.ts/.mjs file under the source root. */
function collectCssImports(root) {
  const specifiers = new Set();
  const walk = (dir) => {
    let entries = [];
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const abs = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!/^(node_modules|dist)$/.test(entry.name)) walk(abs);
        continue;
      }
      if (!/\.(astro|ts|mjs)$/.test(entry.name)) continue;
      let text = '';
      try {
        text = readFileSync(abs, 'utf8');
      } catch {
        continue;
      }
      for (const match of text.matchAll(/['"]([^'"\n]+?\.css)(?:[?#][^'"]*)?['"]/g))
        specifiers.add(match[1].replace(/\\/g, '/'));
    }
  };
  walk(root);
  return [...specifiers];
}
function checkFile(file, args, index) {
  let source;
  try {
    source = readFileSync(file.abs, 'utf8');
  } catch (error) {
    WARN(file.rel, 1, 'file.unreadable', error.message);
    return;
  }
  const clean = stripComments(source);
  const loc = makeLocator(clean);
  const inTokens = file.rel.startsWith('tokens/');
  const lines = source ? source.split(/\r\n|\r|\n/) : [];
  if (lines[lines.length - 1] === '') lines.pop(); // ignore a trailing newline

  // 8 — legacy root files (archive/ is filtered out before we get here).
  if (LEGACY_ROOT.has(file.rel))
    ERROR(file.rel, 1, 'file.legacy', 'legacy root stylesheet; split it and delete it');
  // 1 — canonical banner as the first non-comment statement.
  if (file.rel !== LAYERS_FILE) {
    if (!BANNER_ANY.test(clean))
      ERROR(file.rel, 1, 'banner.missing', `missing "${CANONICAL_BANNER}"`);
    else if (!BANNER_FIRST.test(clean.replace(/^\s+/, ''))) {
      const match = BANNER_ANY.exec(clean);
      ERROR(
        file.rel,
        match ? loc.at(match.index) : 1,
        'banner.displaced',
        'layer banner must be the first statement',
      );
    }
  }
  // 3 — file size.
  if (lines.length > HARD_LINES)
    ERROR(file.rel, 1, 'size.hard', `${lines.length} lines > ${HARD_LINES} hard limit`);
  else if (lines.length > WARN_LINES)
    WARN(file.rel, 1, 'size.warn', `${lines.length} lines > ${WARN_LINES} warn limit`);

  for (const decl of parseStylesheet(clean, createParseState())) {
    const line = loc.lineFor(decl.selectorText, decl.prop);
    const where = `${decl.selectorText} { ${decl.prop} }`;
    // 2 — every rule inside a known layer.
    if (!decl.layer.length)
      ERROR(file.rel, line, 'layer.unlayered', `${where} is outside any @layer`);
    else if (!KNOWN_LAYERS.has(decl.layer[0]))
      ERROR(
        file.rel,
        line,
        'layer.unknown',
        `${where} is in unknown @layer ${decl.layer.join('.')}`,
      );
    // 5 — no !important unless allow-listed.
    if (decl.important && !isAllowedImportant(args, decl))
      ERROR(file.rel, line, 'important', where);
    // 6 — no hardcoded colours outside tokens/.
    if (!inTokens && colorLiterals(decl.value).length) {
      ERROR(
        file.rel,
        line,
        'color.hardcoded',
        `${decl.selectorText} { ${decl.prop}: ${decl.value.slice(0, 70)} }`,
      );
    }
    // 4 — bookkeeping: one owner file per selector+prop, last value wins in a file.
    const key = `${decl.selectorText}\u0000${decl.prop}`;
    if (!index.owners.has(key)) index.owners.set(key, new Map());
    if (!index.owners.get(key).has(file.rel)) index.owners.get(key).set(file.rel, decl);
    if (!index.within.has(file.rel)) index.within.set(file.rel, new Map());
    const local = index.within.get(file.rel);
    const localKey = `${key}\u0000${decl.media.join(' && ')}`;
    if (!local.has(localKey)) local.set(localKey, { decl, values: new Set() });
    local.get(localKey).values.add(decl.value);
  }
  index.locators.set(file.rel, loc);
}

/**
 * Deliberate duplicates: the admin token variants and the public-only
 * refinement files intentionally restate rules from their shared counterparts
 * (see docs/CSS.md). The single-owner rule must not flag those pairs.
 */
function intentionalOverridePair(a, b) {
  const isAdminToken = (name) => name.startsWith('tokens/admin/');
  const isRefinement = (name) => /^site\/shell\/refinements/.test(name);
  const isHeaderRefinement = (name) =>
    name === 'site/shell/header.css' && (a.startsWith('shared/') || b.startsWith('shared/'));
  return (
    isAdminToken(a) ||
    isAdminToken(b) ||
    isRefinement(a) ||
    isRefinement(b) ||
    isHeaderRefinement(a) ||
    isHeaderRefinement(b)
  );
}

function checkDuplicates(index) {
  // 4a — cross-file duplicates: exactly one owner file per selector+prop.
  for (const owners of index.owners.values()) {
    if (owners.size < 2) continue;
    const names = [...owners.keys()].sort();
    for (const name of names.slice(1)) {
      if (names.some((other) => other !== name && intentionalOverridePair(other, name))) continue;
      const decl = owners.get(name);
      const line = index.locators.get(name).lineFor(decl.selectorText, decl.prop);
      ERROR(
        name,
        line,
        'single-owner',
        `${decl.selectorText} { ${decl.prop} } is also declared in ${names[0]}`,
      );
    }
  }
  // 4b — same file and media: only the last value wins, so differing values are dead weight.
  for (const [file, local] of index.within) {
    for (const { decl, values } of local.values()) {
      if (values.size < 2) continue;
      const line = index.locators.get(file).lineFor(decl.selectorText, decl.prop);
      WARN(
        file,
        line,
        'duplicate-prop',
        `${decl.selectorText} { ${decl.prop} } declared with ${values.size} different values (last wins)`,
      );
    }
  }
}

function main() {
  const args = parseArgs(process.argv);
  const sourceRoot = resolve(args.dir, '..');
  const files = walkCss(args.dir).filter((file) => !file.rel.startsWith('archive/'));
  const index = { owners: new Map(), within: new Map(), locators: new Map() };
  for (const file of files) checkFile(file, args, index);
  checkDuplicates(index);

  // 7 — every stylesheet (except tokens/layers.css) imported from src.
  const imports = collectCssImports(sourceRoot);
  for (const file of files) {
    if (file.rel === LAYERS_FILE) continue;
    if (
      !imports.some((specifier) => specifier === file.rel || specifier.endsWith(`/${file.rel}`))
    ) {
      ERROR(file.rel, 1, 'file.orphan', `nothing under ${sourceRoot} imports "${file.rel}"`);
    }
  }
  findings.sort(
    (a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.rule.localeCompare(b.rule),
  );
  for (const finding of findings) {
    console.log(
      `${finding.level} ${finding.file}:${finding.line} ${finding.rule} ${finding.detail}`,
    );
  }

  const counts = new Map();
  for (const finding of findings) counts.set(finding.rule, (counts.get(finding.rule) ?? 0) + 1);
  if (counts.size) {
    console.log('\nby rule:');
    for (const [rule, count] of [...counts].sort((a, b) => b[1] - a[1]))
      console.log(`  ${rule.padEnd(18)} ${count}`);
  }
  const errors = findings.filter((finding) => finding.level === 'ERROR').length;
  console.log(`\ncheck-structure: ${errors} errors, ${findings.length - errors} warnings`);
  process.exitCode = errors > 0 && args.strict ? 1 : 0;
}

try {
  main();
} catch (error) {
  console.error(`check-structure: ${error.message}`);
  process.exitCode = 2;
}
