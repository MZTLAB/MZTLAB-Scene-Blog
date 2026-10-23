/**
 * CSS parser used by the CSS equivalence checker.
 *
 * It does not try to be a full CSS parser: it yields the rules this project
 * actually uses — style rules inside optional `@layer` and `@media` blocks —
 * while skipping `@font-face`/`@keyframes`/`@property` payloads. The cascade
 * checker needs three things from each declaration: its selector list, its
 * at-rule context (media + layer path) and its document order.
 */

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, ' '));
}

function splitTopLevel(text, separator) {
  const parts = [];
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
    if (ch === separator && depth === 0) {
      parts.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  parts.push(current);
  return parts.map((part) => part.trim()).filter(Boolean);
}

function findMatchingBrace(text, openIndex) {
  let depth = 0;
  let quote = null;
  for (let i = openIndex; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === quote && text[i - 1] !== '\\') quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

const SKIP_AT_RULES = new Set([
  'font-face',
  'keyframes',
  '-webkit-keyframes',
  'page',
  'counter-style',
  'property',
  'view-transition',
  'font-palette-values',
  'position-try',
  'starting-style',
]);

export function createParseState() {
  return { order: 0, layerOrder: [], unsupported: new Set() };
}

function registerLayer(state, name) {
  if (!state.layerOrder.includes(name)) state.layerOrder.push(name);
  return state.layerOrder.indexOf(name);
}

/**
 * Parse a stylesheet into flat declarations.
 *
 * @returns {Array<{selectorText:string, media:string[], layer:string[], prop:string, value:string, important:boolean, order:number}>}
 */
export function parseStylesheet(source, state, { media = [], layer = [] } = {}) {
  const text = stripComments(source);
  const declarations = [];

  const parseRange = (chunk, contextMedia, contextLayer) => {
    let i = 0;
    while (i < chunk.length) {
      // Skip whitespace, semicolons.
      while (i < chunk.length && /[\s;]/.test(chunk[i])) i++;
      if (i >= chunk.length) break;
      const brace = chunk.indexOf('{', i);
      const semi = chunk.indexOf(';', i);
      if (brace === -1) {
        // Trailing statement at-rules without a following block, e.g. the
        // inline `@layer tokens, base, …;` order declaration.
        for (const statement of splitTopLevel(chunk.slice(i), ';'))
          handleStatement(statement.trim());
        break;
      }
      // At-rule or rule prelude ends at the first `{`; a `;` before it means a
      // statement at-rule (e.g. `@layer a, b;` or `@import ...;`).
      if (semi !== -1 && semi < brace) {
        const statement = chunk.slice(i, semi).trim();
        handleStatement(statement);
        i = semi + 1;
        continue;
      }
      const prelude = chunk.slice(i, brace).trim().replace(/\s+/g, ' ');
      const close = findMatchingBrace(chunk, brace);
      if (close === -1) break;
      const body = chunk.slice(brace + 1, close);
      handleBlock(prelude, body, contextMedia, contextLayer);
      i = close + 1;
    }
  };

  const handleStatement = (statement) => {
    const layerMatch = /^@layer\s+([^{]+)$/i.exec(statement);
    if (layerMatch) {
      for (const name of splitTopLevel(layerMatch[1], ',')) registerLayer(state, name.trim());
      return;
    }
    if (/^@import/i.test(statement) || /^@charset/i.test(statement)) {
      state.unsupported.add(statement.slice(0, 60));
    }
  };

  const handleBlock = (prelude, body, contextMedia, contextLayer) => {
    if (prelude.startsWith('@')) {
      const name = /^@([a-zA-Z-]+)/.exec(prelude)?.[1]?.toLowerCase() ?? '';
      if (SKIP_AT_RULES.has(name)) return;
      if (name === 'layer') {
        const layerName = prelude.slice('@layer'.length).trim();
        const nextLayer = layerName ? [...contextLayer, layerName] : contextLayer;
        if (layerName) registerLayer(state, layerName);
        parseRange(body, contextMedia, nextLayer);
        return;
      }
      if (name === 'media') {
        const condition = prelude.slice('@media'.length).trim();
        parseRange(body, [...contextMedia, condition], contextLayer);
        return;
      }
      if (name === 'supports' || name === 'container' || name === 'scope') {
        // Not used by this project; parsed but reported as unsupported so the
        // checker output shows it if that ever changes.
        state.unsupported.add(prelude.slice(0, 80));
        parseRange(body, contextMedia, contextLayer);
        return;
      }
      state.unsupported.add(prelude.slice(0, 80));
      return;
    }

    const selectors = splitTopLevel(prelude, ',');
    if (!selectors.length) return;
    const decls = splitTopLevel(body, ';');
    for (const decl of decls) {
      const colon = decl.indexOf(':');
      if (colon === -1) continue;
      let prop = decl.slice(0, colon).trim();
      let value = decl.slice(colon + 1).trim();
      if (!prop || !value) continue;
      const importantMatch = /!\s*important\s*$/i.exec(value);
      const important = Boolean(importantMatch);
      if (important) value = value.slice(0, importantMatch.index).trim();
      if (!prop.startsWith('--')) prop = prop.toLowerCase();
      for (const selector of selectors) {
        declarations.push({
          selectorText: selector,
          media: contextMedia,
          layer: contextLayer,
          prop,
          value,
          important,
          order: state.order++,
        });
      }
    }
  };

  parseRange(text, media, layer);
  return declarations;
}
