import type { AdminUser } from '../types';

/**
 * Client- and server-safe permission check mirrored from
 * backend/app/permissions.py. Editors do not own `content.others` statically:
 * the backend adds it to the session list only when the site owner enables
 * 设置 → 协作与权限 → 编辑可管理他人内容.
 */
export const ROLE_PERMISSIONS: Record<string, string[]> = {
  admin: [
    'comment.moderate',
    'content.delete',
    'content.others',
    'content.publish',
    'content.read',
    'content.write',
    'data.export',
    'gallery.manage',
    'media.manage',
    'settings.manage',
    'taxonomy.manage',
    'users.manage',
  ],
  editor: [
    'comment.moderate',
    'content.delete',
    'content.publish',
    'content.read',
    'content.write',
    'data.export',
    'gallery.manage',
    'media.manage',
    'taxonomy.manage',
  ],
  author: [
    'content.publish',
    'content.read',
    'content.write',
    'gallery.manage',
    'media.manage',
  ],
};

export function hasPermission(
  user: Pick<AdminUser, 'permissions'> | null | undefined,
  permission: string,
): boolean {
  if (!user) return false;
  const granted = user.permissions?.length
    ? user.permissions
    : ROLE_PERMISSIONS[(user as AdminUser).role] || [];
  return granted.includes(permission);
}

export function canAny(
  user: Pick<AdminUser, 'permissions'> | null | undefined,
  permissions: string[],
): boolean {
  return permissions.some((permission) => hasPermission(user, permission));
}
