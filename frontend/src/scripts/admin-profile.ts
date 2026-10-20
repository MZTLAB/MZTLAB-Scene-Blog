import { api } from '../lib/api';
import { errorMessage, toast } from '../lib/admin-client';
import type { AdminUser } from '../types';

const form = document.querySelector<HTMLElement>('[data-profile-form]');
const saveButton = document.querySelector<HTMLButtonElement>('[data-save-profile]');

const refreshAdminIdentity = (user: AdminUser) => {
  const nameNode = document.querySelector<HTMLElement>('.admin-user__meta strong');
  if (nameNode) nameNode.textContent = user.display_name;
  const avatarNode = document.querySelector<HTMLElement>('.admin-user .avatar');
  if (avatarNode) {
    avatarNode.innerHTML = user.avatar
      ? `<img src="${user.avatar}" alt="" />`
      : (user.display_name || 'M').slice(0, 1);
  }
};

saveButton?.addEventListener('click', async () => {
  if (!form) return;
  const data = Object.fromEntries(
    Array.from(form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('[name]')).map((input) => [
      input.name,
      input.value,
    ]),
  ) as Record<string, string>;
  if (data.new_password && data.new_password !== data.confirm_password) {
    toast('两次输入的新密码不一致', 'error');
    return;
  }
  delete data.confirm_password;
  if (saveButton) saveButton.disabled = true;
  try {
    const result = await api<{ user: AdminUser }>('/api/admin/profile', { method: 'PUT', body: data });
    toast('个人资料已更新', 'success');
    form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => (input.value = ''));
    refreshAdminIdentity(result.user);
  } catch (error) {
    toast(errorMessage(error), 'error');
  } finally {
    if (saveButton) saveButton.disabled = false;
  }
});
