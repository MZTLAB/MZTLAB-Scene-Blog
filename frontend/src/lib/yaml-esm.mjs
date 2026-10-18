/**
 * The `yaml` package is CommonJS-only. Vite 8's dev SSR module runner evaluates
 * it as ESM (see picomatch-esm.mjs), so bridge it through Node's require().
 * This shim is only used by the dev server; production bundling handles the
 * original package.
 */
import { createRequire } from 'node:module';

const nodeRequire = createRequire(import.meta.url);
const yaml = nodeRequire('yaml');

export const parseDocument = yaml.parseDocument;
export const YAMLParseError = yaml.YAMLParseError;
export default yaml;
