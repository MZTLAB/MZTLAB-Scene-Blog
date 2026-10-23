/**
 * Minimal, framework-free form primitives for the 3.0.0 frontend.
 *
 * Built on the existing plain-HTML conventions: named controls (`name="..."`),
 * `[data-setting]` style attributes, and the `.field-error` class already
 * rendered by `styles/admin/forms.css`. No Preact/parity layer — just functions that
 * remove the copy-pasted form plumbing from the page scripts.
 */

export type FormValue = string | boolean | string[];

type FieldElement = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

function fieldsOf(container: HTMLFormElement | HTMLElement): FieldElement[] {
  // Some admin "forms" are plain divs (the save button lives in the layout
  // actions slot), so accept a container as well as a real <form>.
  return container instanceof HTMLFormElement
    ? (Array.from(container.elements) as FieldElement[])
    : Array.from(container.querySelectorAll<FieldElement>('input, textarea, select'));
}

/** Read a form (or a container of named controls) into a plain object keyed by `name`. */
export function readForm(form: HTMLFormElement | HTMLElement): Record<string, FormValue> {
  const values: Record<string, FormValue> = {};
  for (const element of fieldsOf(form)) {
    if (
      !(element instanceof HTMLInputElement) &&
      !(element instanceof HTMLTextAreaElement) &&
      !(element instanceof HTMLSelectElement)
    ) {
      continue;
    }
    const name = element.name;
    if (!name) continue;
    if (element instanceof HTMLInputElement) {
      if (element.type === 'checkbox') {
        values[name] = element.checked;
      } else if (element.type === 'radio') {
        if (element.checked) values[name] = element.value;
      } else if (element.type === 'file') {
        // File inputs are uploaded with FormData, not serialised as a value.
        continue;
      } else {
        values[name] = element.value;
      }
    } else if (element instanceof HTMLSelectElement) {
      values[name] = element.multiple
        ? Array.from(element.selectedOptions, (option) => option.value)
        : element.value;
    } else {
      values[name] = element.value;
    }
  }
  return values;
}

/**
 * Fill named controls from a plain object. Checkboxes accept booleans, radio
 * groups accept the value to select, multiple selects accept string arrays.
 */
export function fillForm(
  form: HTMLFormElement | HTMLElement,
  values: Record<string, string | boolean | string[] | null | undefined>,
): void {
  for (const element of fieldsOf(form)) {
    if (
      !(element instanceof HTMLInputElement) &&
      !(element instanceof HTMLTextAreaElement) &&
      !(element instanceof HTMLSelectElement)
    ) {
      continue;
    }
    const name = element.name;
    if (!name || !(name in values)) continue;
    const value = values[name];
    if (element instanceof HTMLInputElement) {
      if (element.type === 'checkbox') {
        element.checked = Boolean(value);
      } else if (element.type === 'radio') {
        const candidate = Array.isArray(value) ? value[0] : String(value ?? '');
        element.checked = element.value === candidate;
      } else if (element.type !== 'file') {
        element.value = Array.isArray(value) ? (value[0] ?? '') : String(value ?? '');
      }
    } else if (element instanceof HTMLSelectElement) {
      const wanted = new Set(
        Array.isArray(value)
          ? value.map(String)
          : value === null || value === undefined
            ? []
            : [String(value)],
      );
      Array.from(element.options).forEach((option) => {
        option.selected = element.multiple
          ? wanted.has(option.value)
          : option.value === [...wanted][0];
      });
    } else {
      element.value = Array.isArray(value) ? (value[0] ?? '') : String(value ?? '');
    }
  }
}

/**
 * Subscribe a control to value changes. Text-like controls fire on `input`,
 * selects/checkboxes/radios on `change`. Returns an unsubscribe function.
 */
export function bindField(
  field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  onChange: (value: FormValue) => void,
): () => void {
  const usesChange =
    field instanceof HTMLSelectElement ||
    (field instanceof HTMLInputElement && (field.type === 'checkbox' || field.type === 'radio'));
  const eventName = usesChange ? 'change' : 'input';
  const listener = () => {
    if (field instanceof HTMLInputElement && field.type === 'checkbox') {
      onChange(field.checked);
    } else if (field instanceof HTMLSelectElement && field.multiple) {
      onChange(Array.from(field.selectedOptions, (option) => option.value));
    } else {
      onChange(field.value);
    }
  };
  field.addEventListener(eventName, listener);
  return () => field.removeEventListener(eventName, listener);
}

const DIRTY_ATTR = 'data-dirty';
const ERROR_ATTR = 'data-field-error';

/** Mark a form as containing unsaved changes. */
export function markDirty(form: HTMLFormElement): void {
  form.setAttribute(DIRTY_ATTR, '1');
}

/** Whether a form was marked dirty via `markDirty`. */
export function isDirty(form: HTMLFormElement): boolean {
  return form.getAttribute(DIRTY_ATTR) === '1';
}

function fieldKey(field: HTMLElement): string {
  return field.dataset.fieldName ?? field.getAttribute('name') ?? field.id;
}

function errorNodeFor(field: HTMLElement): HTMLElement {
  const key = fieldKey(field);
  const scope = field.closest('form') ?? field.parentElement ?? document;
  const escapedKey = key.replace(/["\\]/g, '\\$&');
  const existing = scope.querySelector<HTMLElement>(`[${ERROR_ATTR}="${escapedKey}"]`);
  if (existing) return existing;
  const node = document.createElement('span');
  node.className = 'field-error';
  node.setAttribute(ERROR_ATTR, key);
  node.hidden = true;
  field.insertAdjacentElement('afterend', node);
  return node;
}

/** Show a `.field-error` message next to a control and mark it invalid. */
export function showFieldError(field: HTMLElement, message: string): void {
  if (!field) return;
  field.setAttribute('aria-invalid', 'true');
  const node = errorNodeFor(field);
  node.textContent = message;
  node.hidden = false;
}

/** Remove all field errors created by `showFieldError` and their aria state. */
export function clearFieldErrors(form: HTMLFormElement | HTMLElement): void {
  form.querySelectorAll<HTMLElement>(`[${ERROR_ATTR}]`).forEach((node) => node.remove());
  form.querySelectorAll<HTMLElement>('[aria-invalid="true"]').forEach((field) => {
    field.removeAttribute('aria-invalid');
  });
}
