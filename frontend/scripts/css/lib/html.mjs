/**
 * Minimal, dependency-free HTML parser + DOM adapter for `css-select`.
 *
 * The CSS equivalence checker only needs the server-rendered HTML: tag names,
 * attributes and the element tree. `htmlparser2`/`parse5` are not installed in
 * this project, and adding a dependency just for the migration is avoidable —
 * Astro's SSR output is well-formed, so a straightforward tag scanner is
 * enough. Text nodes are kept for `:empty`/`getText`, but selectors used by
 * this project never depend on their content.
 */

const VOID = new Set([
  'area',
  'base',
  'br',
  'col',
  'embed',
  'hr',
  'img',
  'input',
  'link',
  'meta',
  'param',
  'source',
  'track',
  'wbr',
]);

const RAW_TEXT = new Set([
  'script',
  'style',
  'textarea',
  'title',
  'xmp',
  'iframe',
  'noembed',
  'noframes',
  'plaintext',
]);

const ENTITIES = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
  nbsp: '\u00a0',
};

export function decodeEntities(text) {
  return text.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (whole, body) => {
    if (body[0] === '#') {
      const hex = body[1] === 'x' || body[1] === 'X';
      const code = Number.parseInt(hex ? body.slice(2) : body.slice(1), hex ? 16 : 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : whole;
    }
    return ENTITIES[body] ?? whole;
  });
}

function findTagEnd(html, start) {
  let quote = null;
  for (let i = start; i < html.length; i++) {
    const ch = html[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '>') return i;
  }
  return -1;
}

function parseAttribs(raw) {
  const attribs = Object.create(null);
  const re = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
  let match;
  while ((match = re.exec(raw))) {
    const name = match[1].toLowerCase();
    const value = match[2] ?? match[3] ?? match[4] ?? '';
    attribs[name] = decodeEntities(value);
  }
  return attribs;
}

export function parseHtml(html) {
  const document = { type: 'document', name: '#document', attribs: {}, children: [], parent: null };
  const stack = [document];
  let i = 0;
  const len = html.length;

  const pushText = (text, raw) => {
    if (!text) return;
    const parent = stack[stack.length - 1];
    parent.children.push({ type: 'text', data: raw ? text : decodeEntities(text), parent });
  };

  while (i < len) {
    const lt = html.indexOf('<', i);
    if (lt === -1) {
      pushText(html.slice(i));
      break;
    }
    if (lt > i) pushText(html.slice(i, lt));
    i = lt;

    if (html.startsWith('<!--', i)) {
      const end = html.indexOf('-->', i + 4);
      i = end === -1 ? len : end + 3;
      continue;
    }
    const next = html[i + 1];
    if (next === '!' || next === '?') {
      const end = html.indexOf('>', i);
      i = end === -1 ? len : end + 1;
      continue;
    }
    if (next === '/') {
      const end = html.indexOf('>', i);
      if (end === -1) break;
      const name = html
        .slice(i + 2, end)
        .trim()
        .toLowerCase();
      for (let s = stack.length - 1; s > 0; s--) {
        if (stack[s].name === name) {
          stack.length = s;
          break;
        }
      }
      i = end + 1;
      continue;
    }

    const tagEnd = findTagEnd(html, i + 1);
    if (tagEnd === -1) break;
    const rawTag = html.slice(i + 1, tagEnd);
    const selfClosing = rawTag.endsWith('/');
    const content = selfClosing ? rawTag.slice(0, -1) : rawTag;
    const match = /^([a-zA-Z][^\s/>]*)([\s\S]*)$/.exec(content);
    i = tagEnd + 1;
    if (!match) continue;
    const name = match[1].toLowerCase();
    const parent = stack[stack.length - 1];
    const element = {
      type: 'tag',
      name,
      attribs: parseAttribs(match[2]),
      children: [],
      parent,
    };
    parent.children.push(element);

    if (VOID.has(name) || selfClosing) continue;
    if (RAW_TEXT.has(name)) {
      const closeRe = new RegExp(`</${name}\\s*>`, 'i');
      const rest = html.slice(i);
      const closeMatch = closeRe.exec(rest);
      const text = closeMatch ? rest.slice(0, closeMatch.index) : rest;
      if (text) element.children.push({ type: 'text', data: text, parent: element });
      i = closeMatch ? i + closeMatch.index + closeMatch[0].length : len;
      continue;
    }
    stack.push(element);
  }

  return document;
}

export function isTag(node) {
  return node.type === 'tag';
}

export function elementChildren(node) {
  return (node.children ?? []).filter(isTag);
}

export function walkElements(node, visit) {
  for (const child of node.children ?? []) {
    if (!isTag(child)) continue;
    visit(child);
    walkElements(child, visit);
  }
}

export function textContent(node) {
  if (node.type === 'text') return node.data;
  let out = '';
  for (const child of node.children ?? []) out += textContent(child);
  return out;
}

function isAncestor(maybeAncestor, node) {
  let current = node.parent;
  while (current) {
    if (current === maybeAncestor) return true;
    current = current.parent;
  }
  return false;
}

export const adapter = {
  isTag,
  getAttributeValue(element, name) {
    return element.attribs[name];
  },
  getChildren(node) {
    return node.children ?? [];
  },
  getName(element) {
    return element.name;
  },
  getParent(node) {
    return node.parent ?? null;
  },
  getSiblings(node) {
    return node.parent ? (node.parent.children ?? []) : [node];
  },
  getText: textContent,
  hasAttrib(element, name) {
    return name in element.attribs;
  },
  removeSubsets(nodes) {
    return nodes.filter(
      (node, index) =>
        !nodes.some((other, otherIndex) => otherIndex !== index && isAncestor(other, node)),
    );
  },
};

export function getAttribute(element, name) {
  return element.attribs[name] ?? '';
}
