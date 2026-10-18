import type { AstroGlobal } from 'astro';
import type { AdminUser, SiteStatus } from '../types';
import { apiServer } from './api';
import { hasPermission } from './permissions';

export function requestCookie(astro: AstroGlobal): string {
  return astro.request.headers.get('cookie') || '';
}

export async function getAuthStatus(astro: AstroGlobal): Promise<SiteStatus> {
  try {
    return await apiServer<SiteStatus>('/api/auth/status', {
      cookie: requestCookie(astro),
      timeoutMs: 6_000,
    });
  } catch {
    return { authenticated: false, user: null, needs_setup: false };
  }
}

export async function currentAdmin(astro: AstroGlobal): Promise<AdminUser | null> {
  const status = await getAuthStatus(astro);
  return status.authenticated ? status.user : null;
}

/**
 * Page-level guard. Returns the signed-in member, or a redirect Response that
 * the caller should return immediately.
 */
export async function guardAdmin(
  astro: AstroGlobal,
  permission?: string,
): Promise<AdminUser | Response> {
  const user = await currentAdmin(astro);
  if (!user) {
    const next = encodeURIComponent(astro.url.pathname + astro.url.search);
    return astro.redirect(`/admin/login?next=${next}`);
  }
  if (permission && !hasPermission(user, permission)) {
    return astro.redirect(`/admin?denied=${encodeURIComponent(permission)}`);
  }
  return user;
}
