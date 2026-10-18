/** CommonJS bridge for eventemitter3 (used by p-queue in Astro's content layer). */
import { createRequire } from 'node:module';

const nodeRequire = createRequire(import.meta.url);
const eventemitter3 = nodeRequire('eventemitter3');
const EventEmitter = eventemitter3.EventEmitter || eventemitter3;

export { EventEmitter };
export default EventEmitter;
