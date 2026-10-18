import type { APIRoute } from 'astro';
import { forwardToApi } from '../../lib/proxy';

export const ALL: APIRoute = (context) => forwardToApi(context, '/media');
