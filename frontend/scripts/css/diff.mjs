#!/usr/bin/env node
/**
 * Compare two CSS cascade snapshots produced by `snapshot.mjs`.
 *
 * Exit code 0 = identical cascade. Exit code 1 = differences (printed), so the
 * migration can gate every phase on it.
 *
 * Usage:
 *   node scripts/css/diff.mjs .tmp/css-snap/baseline.json.gz .tmp/css-snap/after.json.gz
 *     [--limit 40] [--quiet]
 */

import { gunzipSync } from 'node:zlib';
import { readFileSync } from 'node:fs';

function parseArgs(argv) {
  const args = {
    a: null,
    b: null,
    limit: 40,
    quiet: false,
    allowRemoved: new Set(),
    allowAdded: new Set(),
  };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--limit') args.limit = Number(argv[++i]);
    else if (arg === '--quiet') args.quiet = true;
    else if (arg === '--allow-token-removed' || arg === '--allow-removed-prop') {
      for (const name of String(argv[++i] ?? '').split(','))
        if (name.trim()) args.allowRemoved.add(name.trim());
    } else if (arg === '--allow-added-prop') {
      for (const name of String(argv[++i] ?? '').split(','))
        if (name.trim()) args.allowAdded.add(name.trim());
    } else if (!args.a) args.a = arg;
    else if (!args.b) args.b = arg;
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!args.a || !args.b) throw new Error('usage: diff.mjs <baseline.json.gz> <candidate.json.gz>');
  return args;
}

function load(file) {
  return JSON.parse(gunzipSync(readFileSync(file)).toString('utf8'));
}

function normalizeValue(value) {
  if (value === undefined) return value;
  // CSS string values are equivalent regardless of quote style; the formatter
  // also normalises whitespace.
  return String(value).replace(/'/g, '"').replace(/\s+/g, ' ').trim();
}

function parseWinnerString(text) {
  const map = new Map();
  if (!text) return map;
  for (const entry of text.split(';')) {
    if (!entry) continue;
    const index = entry.indexOf('=');
    if (index === -1) continue;
    map.set(entry.slice(0, index), entry.slice(index + 1));
  }
  return map;
}

function diffWinnerStrings(a, b, label, diffs, limit, allowRemoved, allowAdded) {
  const left = parseWinnerString(a);
  const right = parseWinnerString(b);
  for (const [prop, value] of left) {
    if (!right.has(prop)) {
      if (allowRemoved?.has(prop)) continue;
      diffs.push(`${label}  - ${prop}: ${value}`);
    } else if (normalizeValue(right.get(prop)) !== normalizeValue(value)) {
      diffs.push(`${label}  ${prop}: ${value}  ->  ${right.get(prop)}`);
    }
  }
  for (const [prop, value] of right) {
    if (!left.has(prop) && !allowAdded?.has(prop)) diffs.push(`${label}  + ${prop}: ${value}`);
  }
  return diffs.length >= limit * 4;
}

function main() {
  const args = parseArgs(process.argv);
  const baseline = load(args.a);
  const candidate = load(args.b);
  const diffs = [];
  const stats = { routes: 0, comparedElements: 0, comparedTokens: 0, envs: 0 };

  if (JSON.stringify(baseline.meta.envs) !== JSON.stringify(candidate.meta.envs)) {
    diffs.push(
      `envs differ: ${JSON.stringify(baseline.meta.envs)} vs ${JSON.stringify(candidate.meta.envs)}`,
    );
  }
  if (JSON.stringify(baseline.meta.themes) !== JSON.stringify(candidate.meta.themes)) {
    diffs.push(
      `themes differ: ${JSON.stringify(baseline.meta.themes)} vs ${JSON.stringify(candidate.meta.themes)}`,
    );
  }

  const routes = new Set([...Object.keys(baseline.routes), ...Object.keys(candidate.routes)]);
  for (const route of [...routes].sort()) {
    stats.routes += 1;
    const left = baseline.routes[route];
    const right = candidate.routes[route];
    if (!left || !right) {
      diffs.push(`route ${route}: missing in ${!left ? 'baseline' : 'candidate'}`);
      continue;
    }
    if (left.status !== right.status)
      diffs.push(`route ${route}: status ${left.status} -> ${right.status}`);

    for (const tokenEnv of Object.keys(left.tokens ?? {})) {
      for (const theme of Object.keys(left.tokens?.[tokenEnv] ?? {})) {
        stats.comparedTokens += 1;
        const oldTokens = left.tokens?.[tokenEnv]?.[theme] ?? {};
        const newTokens = right.tokens?.[tokenEnv]?.[theme] ?? {};
        const props = new Set([...Object.keys(oldTokens), ...Object.keys(newTokens)]);
        for (const prop of [...props].sort()) {
          if (normalizeValue(oldTokens[prop]) === normalizeValue(newTokens[prop])) continue;
          if (!(prop in newTokens) && args.allowRemoved.has(prop)) continue;
          if (!(prop in oldTokens) && args.allowAdded.has(prop)) continue;
          diffs.push(
            `route ${route} token[${tokenEnv}/${theme}] ${prop}: ${oldTokens[prop]} -> ${newTokens[prop]}`,
          );
        }
      }
    }

    for (const env of Object.keys(left.envs ?? {})) {
      const oldEnv = left.envs[env];
      const newEnv = right.envs?.[env];
      if (!newEnv) {
        diffs.push(`route ${route} env ${env}: missing in candidate`);
        continue;
      }
      stats.envs += 1;
      const firstEnv = env === Object.keys(left.envs)[0];
      if (firstEnv) {
        // DOM signature comparison: the refactor must not change markup either.
        const oldDom = oldEnv.dom ?? {};
        const newDom = newEnv.dom ?? {};
        const domPaths = new Set([...Object.keys(oldDom), ...Object.keys(newDom)]);
        for (const path of [...domPaths].sort()) {
          stats.comparedElements += 1;
          if (oldDom[path] === newDom[path]) continue;
          diffs.push(
            `route ${route} dom ${path}: ${oldDom[path] ?? '(missing)'} -> ${newDom[path] ?? '(missing)'}`,
          );
        }
      }
      for (const bucket of ['elements', 'states', 'pseudos']) {
        const oldMap = oldEnv[bucket] ?? {};
        const newMap = newEnv[bucket] ?? {};
        const paths = new Set([...Object.keys(oldMap), ...Object.keys(newMap)]);
        for (const path of [...paths].sort()) {
          stats.comparedElements += 1;
          if (oldMap[path] === newMap[path]) continue;
          if (!(path in oldMap)) {
            diffs.push(`route ${route} env ${env} ${bucket} ${path}: new element`);
            continue;
          }
          if (!(path in newMap)) {
            diffs.push(`route ${route} env ${env} ${bucket} ${path}: element disappeared`);
            continue;
          }
          diffWinnerStrings(
            oldMap[path],
            newMap[path],
            `route ${route} env ${env} ${bucket} ${path}`,
            diffs,
            args.limit,
            args.allowRemoved,
            args.allowAdded,
          );
        }
      }
      // Stylesheet payload metrics (informational, not part of pass/fail).
      if (env === Object.keys(left.envs)[0] && left.cssBytes !== right.cssBytes) {
        stats.cssBytes = [left.cssBytes, right.cssBytes];
      }
    }
    if (left.stylesheets?.length !== right.stylesheets?.length) {
      stats.stylesheetCount = [left.stylesheets?.length, right.stylesheets?.length];
    }
  }

  if (diffs.length) {
    console.log(`CSS CASCADE DIFF: ${diffs.length} differences`);
    for (const line of diffs.slice(0, args.limit)) console.log(`  ${line}`);
    if (diffs.length > args.limit) console.log(`  ... ${diffs.length - args.limit} more`);
    process.exit(1);
  }

  console.log(
    `CSS CASCADE IDENTICAL: ${stats.routes} routes, ${stats.envs} route-envs, ${stats.comparedElements} element buckets, ${stats.comparedTokens} token sets`,
  );
  if (stats.cssBytes)
    console.log(`  css bytes per page: ${stats.cssBytes[0]} -> ${stats.cssBytes[1]}`);
  if (stats.stylesheetCount)
    console.log(
      `  stylesheet count per page: ${stats.stylesheetCount[0]} -> ${stats.stylesheetCount[1]}`,
    );
  process.exit(0);
}

main();
