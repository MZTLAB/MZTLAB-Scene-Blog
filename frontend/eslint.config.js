import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import eslintPluginAstro from 'eslint-plugin-astro';
import globals from 'globals';
import tseslint from 'typescript-eslint';

/**
 * Flat ESLint config for the Astro 7 frontend.
 *
 * Policy (3.0.0):
 * - New code must be clean under the recommended TypeScript/Astro rule sets.
 * - The 2.x legacy codebase is listed in the `legacyOverrides` block below:
 *   rules it currently violates are downgraded to "warn" so `npm run lint`
 *   stays green, but the rules are NOT disabled. Remove entries as the
 *   corresponding layer is rewritten; do not add global "off" entries.
 * - `innerHTML =` assignments are reported as warnings until the dom.ts/form.ts
 *   primitives land in Phase 4, then this rule becomes "error".
 */
const legacyOverrides = {
  name: 'mztlab/legacy-overrides',
  rules: {
    // 2.x scripts still use `any` and loose helper signatures; keep visible.
    '@typescript-eslint/no-explicit-any': 'warn',
    // Legacy code has unused imports/vars from pre-3.0.0 iterations.
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    // `astro check` covers types; keep the lint signal but do not block on
    // legacy constructs such as non-null assertions and banned types.
    '@typescript-eslint/no-non-null-assertion': 'warn',
    '@typescript-eslint/ban-ts-comment': 'warn',
    'no-empty': 'warn',
    'no-useless-escape': 'warn',
    'no-cond-assign': 'warn',
    'no-fallthrough': 'warn',
    // ESLint 10 core rule; 2.x pages assign a default value that is then
    // overwritten in every branch. Keep visible, do not block the build.
    'no-useless-assignment': 'warn',
  },
};

export default defineConfig(
  {
    name: 'mztlab/ignores',
    ignores: ['dist/**', '.astro/**', 'node_modules/**', 'coverage/**', 'public/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...eslintPluginAstro.configs.recommended,
  legacyOverrides,
  {
    name: 'mztlab/no-direct-html',
    files: ['src/**/*.{ts,mjs,js,astro}'],
    // ADR-5: HTML injection must go through src/lib/dom.ts (`setHTML` / `html`).
    // dom.ts is the only file allowed to assign innerHTML; everything under src/
    // now goes through the primitives, so no ratchet exceptions remain.
    ignores: ['src/lib/dom.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "AssignmentExpression[left.type='MemberExpression'][left.property.name=/^(innerHTML|outerHTML)$/]",
          message:
            'Do not assign innerHTML/outerHTML directly. Build markup with html`` / raw() from src/lib/dom.ts and use setHTML()/mount().',
        },
        {
          selector: "CallExpression[callee.property.name='insertAdjacentHTML']",
          message:
            'Do not call insertAdjacentHTML directly. Build markup with html`` from src/lib/dom.ts and use setHTML()/mount().',
        },
      ],
    },
  },
  {
    name: 'mztlab/browser-globals',
    files: ['src/**/*.{ts,mjs,js,astro}'],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    name: 'mztlab/node-config-files',
    files: ['*.config.{js,mjs,ts}', 'astro.config.mjs'],
    languageOptions: {
      globals: globals.node,
    },
  },
);
