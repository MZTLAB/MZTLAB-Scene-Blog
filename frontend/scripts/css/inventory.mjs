#!/usr/bin/env node
/**
 * CSS inventory — read-only report over `src/styles/` used to plan the @layer
 * refactor: sizes, @media/@layer density, duplication, !important and hardcoded
 * colours. It is a planning aid, not a gate, so it always exits 0.
 *
 * Usage: node scripts/css/inventory.mjs [--json] [--dir <stylesDir>]
 *
 * Counts come from `lib/css.mjs`, so a selector list (`a, b`) contributes one
 * declaration per selector. Directory paths are reported with `/` separators.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createParseState, parseStylesheet } from './lib/css.mjs';

const HARD_LINES = 400;
const WARN_LINES = 250;
const LIMIT = 20; // examples per category
const DEFAULT_DIR = fileURLToPath(new URL('../../src/styles/', import.meta.url));
const HELP = 'usage: node scripts/css/inventory.mjs [--json] [--dir <stylesDir>]';

const BANNER_FIRST = /^@layer\s+tokens\s*,\s*base\s*,\s*components\s*,\s*pages\s*,\s*utilities\s*;/;
const CANONICAL = '@layer tokens, base, components, pages, utilities;';
const LAYER_STATEMENT = /@layer\s+([^{};]+);/g;
const HEX = /#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})\b/gi;
// rgb()/hsl()/oklch()/color() literals; `color-mix(` does not match on purpose.
const COLOR_FN = /\b(?:rgba?|hsla?|hsl|oklch|color)\((?:[^()]|\([^()]*\))*\)/gi;

function parseArgs(argv) {
  const args = { json: false, dir: DEFAULT_DIR };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--json') args.json = true;
    else if (arg === '--dir') {
      const value = argv[++i];
      if (!value) throw new Error('--dir requires a path');
      args.dir = resolve(value);
    } else if (arg === '--help' || arg === '-h') {
      console.log(HELP);
      process.exit(0);
    } else throw new Error(`unknown argument "${arg}" (try --help)`);
  }
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

function countLines(text) {
  if (!text) return 0;
  const lines = text.split(/\r\n|\r|\n/);
  if (lines[lines.length - 1] === '') lines.pop(); // trailing newline is not a line
  return lines.length;
}

/** Colour literals in a value; `var()` fallbacks, url() fragments and strings are ignored. */
function colorLiterals(value) {
  const scrubbed = value
    .replace(/url\([^)]*\)/gi, 'url()')
    .replace(/"[^"]*"|'[^']*'/g, ' ')
    .replace(/var\([^()]*(?:\([^()]*\)[^()]*)*\)/g, 'var()');
  return [...scrubbed.matchAll(HEX), ...scrubbed.matchAll(COLOR_FN)].map((match) =>
    match[0].replace(/\s+/g, ' '),
  );
}

/** Collect everything the report needs in one pass over the tree. */
function analyze(files, dir) {
  const records = [];
  const across = new Map(); // selector+prop -> Set<file>
  const within = []; // same selector+prop+@media, different values
  const important = [];
  const colors = [];
  const statements = new Map(); // normalized `@layer a, b;` -> Set<file>

  for (const file of files) {
    const source = readFileSync(file.abs, 'utf8');
    const clean = stripComments(source);
    const declarations = parseStylesheet(clean, createParseState());
    const inTokens = file.rel.startsWith('tokens/');
    const record = {
      path: file.rel,
      lines: countLines(source),
      bytes: Buffer.byteLength(source),
      declarations: declarations.length,
      media: (clean.match(/@media\b/gi) ?? []).length,
      layerBlocks: (clean.match(/@layer\s+[^{;]+\{/gi) ?? []).length,
      banner: BANNER_FIRST.test(clean.replace(/^\s+/, '')),
      important: 0,
      colors: 0,
      maxLines: 'ok',
    };
    record.maxLines =
      record.lines > HARD_LINES ? 'hard' : record.lines > WARN_LINES ? 'warn' : 'ok';
    for (const match of clean.matchAll(LAYER_STATEMENT)) {
      const statement = `@layer ${match[1].trim().replace(/\s+/g, ' ')};`;
      statements.set(statement, (statements.get(statement) ?? new Set()).add(file.rel));
    }

    const seenInFile = new Map();
    for (const decl of declarations) {
      const key = `${decl.selectorText}\u0000${decl.prop}`;
      if (!across.has(key)) across.set(key, new Set());
      across.get(key).add(file.rel);

      const localKey = `${key}\u0000${decl.media.join(' && ')}`;
      if (!seenInFile.has(localKey)) seenInFile.set(localKey, { decl, values: new Set() });
      seenInFile.get(localKey).values.add(decl.value);

      if (decl.important) {
        record.important += 1;
        important.push({ file: file.rel, selector: decl.selectorText, prop: decl.prop });
      }
      if (!inTokens) {
        const literals = colorLiterals(decl.value);
        if (!literals.length) continue;
        record.colors += literals.length;
        colors.push({
          file: file.rel,
          selector: decl.selectorText,
          prop: decl.prop,
          value: decl.value,
          literals,
        });
      }
    }
    for (const { decl, values } of seenInFile.values()) {
      if (values.size > 1)
        within.push({
          file: file.rel,
          selector: decl.selectorText,
          prop: decl.prop,
          values: [...values],
        });
    }
    records.push(record);
  }

  const duplicates = [];
  for (const [key, owners] of across) {
    if (owners.size < 2) continue;
    const [selector, prop] = key.split('\u0000');
    duplicates.push({ selector, prop, files: [...owners].sort() });
  }
  duplicates.sort((a, b) => a.selector.localeCompare(b.selector) || a.prop.localeCompare(b.prop));

  const sum = (key) => records.reduce((total, record) => total + record[key], 0);
  const byFile = (key) =>
    Object.fromEntries(
      records.filter((record) => record[key] > 0).map((record) => [record.path, record[key]]),
    );
  return {
    dir,
    files: records,
    totals: {
      files: records.length,
      lines: sum('lines'),
      bytes: sum('bytes'),
      declarations: sum('declarations'),
      media: sum('media'),
      important: important.length,
    },
    duplicates: {
      count: duplicates.length,
      examples: duplicates.slice(0, LIMIT),
      truncated: duplicates.length > LIMIT,
    },
    withinFileDuplicates: {
      count: within.length,
      examples: within.slice(0, LIMIT),
      truncated: within.length > LIMIT,
    },
    important: {
      count: important.length,
      byFile: byFile('important'),
      examples: important.slice(0, LIMIT),
      truncated: important.length > LIMIT,
    },
    hardcodedColors: {
      count: records.reduce((total, record) => total + record.colors, 0),
      byFile: byFile('colors'),
      examples: colors.slice(0, LIMIT),
      truncated: colors.length > LIMIT,
    },
    layerBanner: {
      files: records.length,
      withBanner: records.filter((record) => record.banner).map((record) => record.path),
      missing: records.filter((record) => !record.banner).map((record) => record.path),
      statements: [...statements].map(([statement, owners]) => ({
        statement,
        files: [...owners].sort(),
      })),
    },
  };
}

function render(report) {
  const width = Math.max(20, ...report.files.map((record) => record.path.length));
  const row = (record) =>
    `${record.path.padEnd(width)}  ${String(record.lines).padStart(5)}  ` +
    `${String(record.bytes).padStart(7)}  ${String(record.declarations).padStart(6)}  ` +
    `${String(record.media).padStart(5)}  ${String(record.layerBlocks).padStart(5)}  ` +
    `${String(record.important).padStart(4)}  ${String(record.colors).padStart(4)}  ${record.maxLines.toUpperCase()}`;
  const header =
    `${'file'.padEnd(width)}  ${'lines'.padStart(5)}  ${'bytes'.padStart(7)}  ` +
    `${'decls'.padStart(6)}  ${'media'.padStart(5)}  ${'layer'.padStart(5)}  ` +
    `${'imp'.padStart(4)}  ${'col'.padStart(4)}  MAX`;

  console.log(`CSS inventory  ${report.dir}`);
  console.log(`\n${header}`);
  for (const record of report.files) console.log(row(record));
  const { totals } = report;
  console.log(
    `${'totals'.padEnd(width)}  ${String(totals.lines).padStart(5)}  ${String(totals.bytes).padStart(7)}  ` +
      `${String(totals.declarations).padStart(6)}  ${String(totals.media).padStart(5)}  ` +
      `${''.padStart(5)}  ${''.padStart(4)}  ${''.padStart(4)}  ${totals.files} files`,
  );

  const list = (title, entries, format, truncated, total) => {
    console.log(`\n${title}`);
    if (!entries.length) return console.log('  none');
    for (const entry of entries) console.log(`  ${format(entry)}`);
    if (truncated) console.log(`  (showing ${entries.length} of ${total})`);
  };
  list(
    `cross-file duplicates: ${report.duplicates.count} selector+prop pairs in 2+ files`,
    report.duplicates.examples,
    (e) => `${e.selector} { ${e.prop} }  ${e.files.join(', ')}`,
    report.duplicates.truncated,
    report.duplicates.count,
  );
  list(
    `within-file conflicting duplicates: ${report.withinFileDuplicates.count}`,
    report.withinFileDuplicates.examples,
    (e) => `${e.file}  ${e.selector} { ${e.prop} }  ${e.values.join(' | ')}`,
    report.withinFileDuplicates.truncated,
    report.withinFileDuplicates.count,
  );
  list(
    `!important: ${report.important.count} declarations in ${Object.keys(report.important.byFile).length} files`,
    report.important.examples,
    (e) => `${e.file}  ${e.selector} { ${e.prop} }`,
    report.important.truncated,
    report.important.count,
  );
  list(
    `hardcoded colours outside tokens/: ${report.hardcodedColors.count} literals in ${Object.keys(report.hardcodedColors.byFile).length} files`,
    report.hardcodedColors.examples,
    (e) => `${e.file}  ${e.selector} { ${e.prop}: ${e.value.slice(0, 60)} }`,
    report.hardcodedColors.truncated,
    report.hardcodedColors.count,
  );

  const banner = report.layerBanner;
  const missing = banner.missing.filter((path) => path !== 'tokens/layers.css');
  const others = banner.statements.filter((entry) => entry.statement !== CANONICAL);
  console.log(
    `\n@layer order statements: canonical banner in ${banner.withBanner.length}/${banner.files} files`,
  );
  console.log(`  missing banner: ${missing.length ? missing.join(', ') : 'none'}`);
  console.log(
    `  other statements: ${
      others.length
        ? others.map((entry) => `${entry.statement} (${entry.files.length})`).join('; ')
        : 'none'
    }`,
  );
}

function main() {
  const args = parseArgs(process.argv);
  const report = analyze(walkCss(args.dir), args.dir);
  if (args.json) console.log(JSON.stringify(report, null, 2));
  else render(report);
}

try {
  main();
} catch (error) {
  // A report tool: even a broken tree or bad argument exits 0, message on stderr.
  console.error(`inventory: ${error.message}`);
  if (/ENOENT|unknown argument|requires a path/.test(error.message)) console.error(HELP);
}
