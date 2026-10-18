/**
 * Vite 8's dev module runner evaluates CommonJS packages as ESM, which breaks
 * picomatch (a CJS-only dependency used by Astro's asset plugin). Load it with
 * Node's native CommonJS bridge instead. The Vite alias in astro.config.mjs
 * points `picomatch` here for the SSR dev environment.
 */
import { createRequire } from 'node:module';

const nodeRequire = createRequire(import.meta.url);
const picomatch = nodeRequire('picomatch');

export default picomatch;
