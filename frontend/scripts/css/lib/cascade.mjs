/**
 * Selector preparation + cascade primitives for the CSS equivalence checker.
 *
 * The checker must answer: "does this element get exactly the same winning
 * declaration for every property before and after the refactor?" It therefore
 * needs browser-like cascade semantics: layer order, specificity, source order
 * and `!important`, plus enough selector matching to find applicable rules.
 */

import { compile } from 'css-select';
import { adapter } from './html.mjs';

const DYNAMIC_PSEUDOS = /:(hover|focus|focus-visible|focus-within|active|visited|target)\b/g;
const PSEUDO_ELEMENT =
  /(.*?)(::(?:before|after|selection|marker|placeholder|first-line|first-letter|backdrop))\s*$/;

export function computeSpecificity(selectorText) {
  let ids = 0;
  let classes = 0;
  let types = 0;
  let rest = selectorText;

  rest = rest.replace(/::[a-zA-Z-]+(?:\([^)]*\))?/g, () => {
    types += 1;
    return ' ';
  });
  rest = rest.replace(/:(not|is|has)\(([^()]*)\)/g, (_whole, _name, arg) => {
    const inner = computeSpecificity(arg);
    ids += inner[0];
    classes += inner[1];
    types += inner[2];
    return ' ';
  });
  rest = rest.replace(/:where\(([^()]*)\)/g, ' ');
  rest = rest.replace(/\[[^\]]*\]/g, () => {
    classes += 1;
    return ' ';
  });
  rest = rest.replace(/#[a-zA-Z0-9_-]+/g, () => {
    ids += 1;
    return ' ';
  });
  rest = rest.replace(/\.[a-zA-Z0-9_-]+/g, () => {
    classes += 1;
    return ' ';
  });
  rest = rest.replace(/(?<!:):[a-zA-Z-]+(?:\([^)]*\))?/g, () => {
    classes += 1;
    return ' ';
  });
  for (const token of rest.split(/[\s>+~,]+/)) {
    const name = token.trim();
    if (!name || name === '*' || name === '|') continue;
    if (/^[a-zA-Z][a-zA-Z0-9-]*$/.test(name)) types += 1;
  }
  return [ids, classes, types];
}

export function specificityScore(selectorText) {
  const [ids, classes, types] = computeSpecificity(selectorText);
  return ids * 1_000_000 + classes * 1_000 + types;
}

function rightmostKey(selector) {
  const last =
    selector
      .split(/[\s>+~]+/)
      .filter(Boolean)
      .pop() ?? '';
  const idMatch = /#([a-zA-Z0-9_-]+)/.exec(last);
  if (idMatch) return { type: 'id', value: idMatch[1] };
  const classMatches = [...last.matchAll(/\.([a-zA-Z0-9_-]+)/g)];
  if (classMatches.length)
    return { type: 'class', value: classMatches[classMatches.length - 1][1] };
  const typeMatch = /^([a-zA-Z][a-zA-Z0-9-]*)/.exec(last);
  if (typeMatch) return { type: 'tag', value: typeMatch[1].toLowerCase() };
  return { type: 'generic', value: '' };
}

const compileCache = new Map();

/**
 * Prepare one selector for matching.
 * Returns null when the selector cannot be evaluated without browser state.
 */
export function prepareSelector(selectorText) {
  if (compileCache.has(selectorText)) return compileCache.get(selectorText);

  let base = selectorText.trim();
  let pseudo = null;
  const pseudoMatch = PSEUDO_ELEMENT.exec(base);
  if (pseudoMatch) {
    pseudo = pseudoMatch[2].slice(2);
    base = pseudoMatch[1];
  }

  let stateful = false;
  base = base.replace(DYNAMIC_PSEUDOS, () => {
    stateful = true;
    return '';
  });
  base = base.replace(/:root\b/g, 'html');
  base = base.replace(/\s+/g, ' ').trim();

  const prepared = {
    raw: selectorText,
    base,
    pseudo,
    stateful,
    specificity: specificityScore(selectorText),
    bucket: rightmostKey(base || '*'),
    compiled: null,
    error: null,
  };
  if (!base) {
    prepared.error = 'empty selector after pseudo-class stripping';
    compileCache.set(selectorText, prepared);
    return prepared;
  }
  try {
    prepared.compiled = compile(base, { adapter, xmlMode: false });
  } catch (error) {
    prepared.error = String(error?.message ?? error);
  }
  compileCache.set(selectorText, prepared);
  return prepared;
}

const MEDIA_SUPPORTED = [
  [/^\(\s*max-width:\s*([\d.]+)px\s*\)$/, (m, env) => env.width <= Number(m[1])],
  [/^\(\s*min-width:\s*([\d.]+)px\s*\)$/, (m, env) => env.width >= Number(m[1])],
  [/^\(\s*prefers-reduced-motion:\s*reduce\s*\)$/, (_m, env) => env.reducedMotion],
  [/^\(\s*prefers-reduced-motion:\s*no-preference\s*\)$/, (_m, env) => !env.reducedMotion],
  [/^\(\s*prefers-color-scheme:\s*dark\s*\)$/, (_m, env) => env.dark],
  [/^\(\s*prefers-color-scheme:\s*light\s*\)$/, (_m, env) => !env.dark],
  [/^\(\s*hover:\s*hover\s*\)$/, () => true],
  [/^\(\s*pointer:\s*fine\s*\)$/, () => true],
  [/^\(\s*orientation:\s*landscape\s*\)$/, () => true],
  [/^\(\s*min-resolution:\s*[\d.]+dppx\s*\)$/, () => true],
];

export function mediaMatches(mediaList, env, unsupported) {
  for (const condition of mediaList) {
    const conjuncts = condition.split(/\s+and\s+/i);
    let ok = true;
    for (const raw of conjuncts) {
      const part = raw.trim().toLowerCase();
      if (!part) continue;
      if (part === 'all' || part === 'screen') continue;
      if (part === 'print' || part === 'speech') {
        ok = false;
        break;
      }
      let matched = false;
      for (const [pattern, evaluate] of MEDIA_SUPPORTED) {
        const match = pattern.exec(part);
        if (match) {
          matched = evaluate(match, env);
          break;
        }
      }
      if (!matched) {
        unsupported?.add(`@media ${condition}`);
        ok = false;
        break;
      }
      if (!matched) {
        ok = false;
        break;
      }
    }
    if (!ok) return false;
  }
  return true;
}

/**
 * Build the priority tuple of a declaration.
 *
 * Normal declarations: unlayered > later layers > earlier layers.
 * Important declarations: important always beats normal; layered beats
 * unlayered; earlier layers beat later layers.
 */
export function priorityOf(declaration, layerRankLookup) {
  if (declaration.inline) {
    return [2, 0, 0, declaration.specificity ?? 0, declaration.order ?? 0];
  }
  const layerIndex = declaration.layer?.length ? layerRankLookup(declaration.layer) : -1;
  if (declaration.important) {
    const rank = layerIndex === -1 ? 0 : 1_000_000 - layerIndex;
    return [1, 1, rank, declaration.specificity, declaration.order];
  }
  const rank = layerIndex === -1 ? 1_000_000 : layerIndex;
  return [0, 0, rank, declaration.specificity, declaration.order];
}

export function comparePriority(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

export function makeLayerRankLookup(layerOrder) {
  const byPath = new Map();
  let next = 0;
  const lookup = (layerPath) => {
    const key = layerPath.join('.');
    if (byPath.has(key)) return byPath.get(key);
    // Nested layers: parent order dominates, then the nested layer order (the
    // nested names are declared in a fixed order in tokens/layers.css).
    const parentIndex = layerOrder.indexOf(layerPath[0]);
    if (parentIndex !== -1) {
      const nestedIndex = layerPath.length > 1 ? layerOrder.indexOf(layerPath[1]) : -1;
      const rank = parentIndex * 1000 + (nestedIndex === -1 ? 0 : nestedIndex);
      byPath.set(key, rank);
      return rank;
    }
    byPath.set(key, next++);
    return byPath.get(key);
  };
  return lookup;
}
