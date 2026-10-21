/**
 * DOM + HTML primitives for the 3.0.0 frontend.
 *
 * Policy (ADR-5, first step):
 * - HTML is built with the `html` tagged template. It escapes every
 *   interpolated value by default; only `RawHtml` values (from `html`/`raw`)
 *   are inserted verbatim. This removes the per-value `escapeHtml()` calls from
 *   templates and the double-escaping bugs that came with them.
 * - `setHTML()` is the ONLY place allowed to assign `innerHTML` (enforced by the
 *   `no-restricted-syntax` rule in eslint.config.js). A plain string argument is
 *   treated as pre-escaped legacy markup and must be documented as such.
 * - The rest are small DOM helpers shared by the admin/public scripts.
 *
 * Dependency-free: no framework, no runtime other than the DOM.
 */

/** A string of markup that is safe to inject. Only `raw()` and `html` create it. */
export class RawHtml {
  constructor(readonly value: string) {}

  toString(): string {
    return this.value;
  }
}

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#039;',
};

/**
 * Escape a value for use as HTML text or attribute content.
 *
 * This is the single implementation used by the whole frontend; `admin-client`
 * re-exports it for backwards compatibility.
 */
export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ESCAPES[character] ?? character);
}

/** Mark a trusted markup string as safe to inject. Use sparingly. */
export function raw(markup: string): RawHtml {
  return new RawHtml(markup);
}

function renderValue(value: unknown): string {
  if (value instanceof RawHtml) return value.value;
  if (Array.isArray(value)) return value.map(renderValue).join('');
  if (value === null || value === undefined) return '';
  return escapeHtml(value);
}

/**
 * Default-safe HTML builder:
 *
 * ```ts
 * setHTML(el, html`<strong>${post.title}</strong>`);
 * ```
 *
 * Every interpolation is escaped unless it is `RawHtml` (or an array of
 * `RawHtml`, which is concatenated — handy for the `.map()` pattern):
 *
 * ```ts
 * setHTML(list, html`${items.map((item) => html`<li>${item.name}</li>`)}`);
 * ```
 */
export function html(strings: TemplateStringsArray, ...values: unknown[]): RawHtml {
  let output = strings[0] ?? '';
  for (let index = 0; index < values.length; index += 1) {
    output += renderValue(values[index]);
    output += strings[index + 1] ?? '';
  }
  return raw(output);
}

/** Escaped text content, for building textual fragments. */
export function text(value: unknown): string {
  return escapeHtml(value);
}

/**
 * Assign markup to an element. The only sanctioned `innerHTML` assignment.
 *
 * A `string` argument is treated as pre-escaped legacy markup — the caller is
 * responsible for escaping it. Prefer passing the result of `html`/`raw`.
 */
export function setHTML(element: Element | null | undefined, value: RawHtml | string): void {
  if (!element) return;
  element.innerHTML = value instanceof RawHtml ? value.value : value;
}

/** Render markup into a container and return it (null when the container is absent). */
export function mount<T extends Element>(element: T | null | undefined, value: RawHtml | string): T | null {
  if (!element) return null;
  setHTML(element, value);
  return element;
}

/** `querySelector` with a default root and element type. */
export function qs<T extends Element = HTMLElement>(selector: string, root: ParentNode = document): T | null {
  return root.querySelector<T>(selector);
}

/** `querySelectorAll` as an array (never a live NodeList). */
export function qsa<T extends Element = HTMLElement>(selector: string, root: ParentNode = document): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

/**
 * Add an event listener and return an unsubscribe function.
 *
 * Generic over the event type so handlers can stay typed:
 * `on<KeyboardEvent>(document, 'keydown', (event) => event.key)`.
 */
export function on<E extends Event = Event>(
  target: EventTarget | null | undefined,
  type: string,
  handler: (event: E) => void,
  options?: boolean | AddEventListenerOptions,
): () => void {
  if (!target) return () => {};
  const listener = (event: Event) => handler(event as E);
  target.addEventListener(type, listener, options);
  return () => target.removeEventListener(type, listener, options);
}

/**
 * Reflect a busy state on a control: `aria-busy`, a `.is-busy` class and
 * `disabled` for form controls. When `label` is given the visible text is
 * swapped while busy and restored afterwards.
 */
export function setBusy(
  element: HTMLElement | null | undefined,
  busy: boolean,
  label?: string,
): void {
  if (!element) return;
  element.classList.toggle('is-busy', busy);
  element.setAttribute('aria-busy', busy ? 'true' : 'false');
  if (element instanceof HTMLButtonElement || element instanceof HTMLInputElement) {
    element.disabled = busy;
  }
  if (label !== undefined) {
    if (busy) {
      element.dataset.busyLabel = element.textContent ?? '';
      element.textContent = label;
    } else if (element.dataset.busyLabel !== undefined) {
      element.textContent = element.dataset.busyLabel;
      delete element.dataset.busyLabel;
    }
  }
}

/**
 * Standard empty state block. `action` is trusted markup (use `html`):
 *
 * ```ts
 * emptyState('还没有相册。', '新建一本，从媒体库挑几张照片开始。',
 *   html`<button class="a-btn a-btn--sm" type="button" data-empty-create>新建相册</button>`);
 * ```
 */
export function emptyState(title: string, text?: string, action?: RawHtml | string): RawHtml {
  return html`<div class="admin-empty"><p>${title}${text ? ` ${text}` : ''}</p>${action ?? ''}</div>`;
}
