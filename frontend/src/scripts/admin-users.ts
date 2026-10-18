import { api, qs } from '../lib/api';
import { debounce, errorMessage, escapeHtml, toast } from '../lib/admin-client';
import { formatDate, timeAgo } from '../lib/format';
import type { Member } from '../types';

const root = document.querySelector<HTMLElement>('[data-users-page]');

if (root) {
  const selfId = Number(root.dataset.selfId || 0);
  const grid = root.querySelector<HTMLElement>('[data-member-grid]');
  const filters = root.querySelector<HTMLElement>('[data-role-filters]');
  const search = root.querySelector<HTMLInputElement>('[data-user-search]');
  const modal = root.querySelector<HTMLElement>('[data-user-modal]');
  const form = root.querySelector<HTMLFormElement>('[data-user-form]');
  const modalTitle = root.querySelector<HTMLElement>('[data-modal-title]');
  const submitButton = root.querySelector<HTMLButtonElement>('[data-submit-user]');
  const usernameField = root.querySelector<HTMLElement>('[data-username-field]');
  const usernameInput = root.querySelector<HTMLInputElement>('#user-username');
  const nameInput = root.querySelector<HTMLInputElement>('#user-name');
  const emailInput = root.querySelector<HTMLInputElement>('#user-email');
  const passwordInput = root.querySelector<HTMLInputElement>('#user-password');
  const passwordLabel = root.querySelector<HTMLElement>('[data-password-label]');
  const activeInput = root.querySelector<HTMLInputElement>('[data-user-active]');
  const activeRow = root.querySelector<HTMLElement>('[data-active-row]');

  const state: { role: string; q: string } = { role: '', q: '' };
  let editingId: number | null = null;
  let members: Member[] = [];

  const selectedRole = (): string =>
    root.querySelector<HTMLInputElement>('input[name="role"]:checked')?.value || 'author';

  const syncRoleOptions = () => {
    const role = selectedRole();
    root.querySelectorAll<HTMLElement>('[data-role-option]').forEach((option) => {
      option.classList.toggle('is-selected', option.dataset.roleOption === role);
    });
  };

  const openModal = (member: Member | null) => {
    editingId = member?.id ?? null;
    if (modalTitle) modalTitle.textContent = member ? `编辑成员 · ${member.display_name}` : '邀请成员';
    if (usernameField) usernameField.style.display = member ? 'none' : '';
    if (usernameInput) usernameInput.value = member?.username || '';
    if (nameInput) nameInput.value = member?.display_name || '';
    if (emailInput) emailInput.value = member?.email || '';
    if (passwordInput) {
      passwordInput.value = '';
      passwordInput.required = !member;
      passwordInput.placeholder = member ? '留空则不修改密码' : '至少 10 位';
    }
    if (passwordLabel) passwordLabel.textContent = member ? '重置密码（可选）' : '初始密码 *';
    if (activeInput) activeInput.checked = member ? member.is_active : true;
    if (activeRow) activeRow.style.display = member && member.id === selfId ? 'none' : '';

    const role = member?.role || 'author';
    root.querySelectorAll<HTMLInputElement>('input[name="role"]').forEach((input) => {
      input.checked = input.value === role;
    });
    syncRoleOptions();
    modal?.classList.add('is-open');
    (member ? nameInput : usernameInput)?.focus();
  };

  const closeModal = () => modal?.classList.remove('is-open');

  const render = () => {
    if (!grid) return;
    if (!members.length) {
      grid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1">
        <p>${state.q ? '没有匹配的成员。' : '还没有成员。'}</p>
      </div>`;
      return;
    }
    grid.innerHTML = members
      .map((member) => {
        const isSelf = member.id === selfId;
        const roleLabel = member.role === 'admin' ? '管理员' : member.role === 'editor' ? '编辑' : '作者';
        return `<article class="member-card" data-member="${member.id}" data-self="${isSelf}">
          <div class="member-card__top">
            <span class="avatar">${escapeHtml((member.display_name || 'M').slice(0, 1))}</span>
            <div class="member-card__id">
              <strong>${escapeHtml(member.display_name)}${isSelf ? '（你）' : ''}</strong>
              <span>@${escapeHtml(member.username)}</span>
            </div>
            <span class="role-badge" data-role="${member.role}" data-inactive="${member.is_active ? 'false' : 'true'}">${roleLabel}</span>
          </div>
          <div class="member-card__meta">
            <div><span>邮箱</span><span>${escapeHtml(member.email || '—')}</span></div>
            <div><span>内容</span><span>${member.content_count} 篇 · ${member.gallery_count} 本相册 · ${member.media_count ?? 0} 个媒体</span></div>
            <div><span>最近登录</span><span>${member.last_login_at ? escapeHtml(timeAgo(member.last_login_at)) : '从未登录'}</span></div>
            <div><span>加入</span><span>${escapeHtml(formatDate(member.created_at, 'short'))}</span></div>
            <div><span>状态</span><span>${member.is_active ? '启用中' : '已停用'}</span></div>
          </div>
          <div class="member-card__actions">
            <button class="a-btn a-btn--sm" type="button" data-edit="${member.id}">编辑</button>
            <button class="a-btn a-btn--sm" type="button" data-toggle="${member.id}" ${isSelf ? 'disabled' : ''}>
              ${member.is_active ? '停用' : '启用'}
            </button>
            <button class="a-btn a-btn--sm a-btn--danger" type="button" data-delete="${member.id}" data-name="${escapeHtml(member.display_name)}" ${isSelf ? 'disabled' : ''}>删除</button>
          </div>
        </article>`;
      })
      .join('');

    grid.querySelectorAll<HTMLButtonElement>('[data-edit]').forEach((button) => {
      button.addEventListener('click', () => {
        const member = members.find((item) => item.id === Number(button.dataset.edit));
        if (member) openModal(member);
      });
    });

    grid.querySelectorAll<HTMLButtonElement>('[data-toggle]').forEach((button) => {
      button.addEventListener('click', async () => {
        const member = members.find((item) => item.id === Number(button.dataset.toggle));
        if (!member) return;
        button.disabled = true;
        try {
          await api(`/api/admin/users/${member.id}`, {
            method: 'PUT',
            body: {
              display_name: member.display_name,
              email: member.email,
              bio: member.bio,
              role: member.role,
              is_active: !member.is_active,
              password: '',
            },
          });
          toast(member.is_active ? '成员已停用，会话已失效' : '成员已启用', 'success');
          await load();
        } catch (error) {
          button.disabled = false;
          toast(errorMessage(error), 'error');
        }
      });
    });

    grid.querySelectorAll<HTMLButtonElement>('[data-delete]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!window.confirm(`删除成员「${button.dataset.name}」？其内容会保留，作者标记变为未署名。`)) return;
        try {
          await api(`/api/admin/users/${button.dataset.delete}`, { method: 'DELETE' });
          toast('成员已删除', 'success');
          await load();
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      });
    });
  };

  const syncCounts = (counts: Record<string, number>) => {
    filters?.querySelectorAll<HTMLElement>('[data-role]').forEach((button) => {
      const value = button.dataset.role || '';
      const node = button.querySelector('small');
      if (node) {
        node.textContent = String(value ? counts[value] || 0 : counts.admin + counts.editor + counts.author || 0);
      }
      button.classList.toggle('is-active', value === state.role);
    });
  };

  const load = async () => {
    if (!grid) return;
    try {
      const data = await api<{ items: Member[]; counts: Record<string, number> }>(
        `/api/admin/users${qs({ q: state.q, role: state.role })}`,
      );
      members = data.items;
      syncCounts(data.counts);
      render();
    } catch (error) {
      grid.innerHTML = `<div class="admin-empty" style="grid-column:1/-1"><p>${escapeHtml(errorMessage(error))}</p></div>`;
    }
  };

  const submit = async () => {
    const role = selectedRole();
    const displayName = nameInput?.value.trim() || '';
    const email = emailInput?.value.trim() || '';
    const password = passwordInput?.value || '';
    const isActive = activeInput?.checked ?? true;

    if (!displayName) {
      toast('请填写显示名称', 'error');
      nameInput?.focus();
      return;
    }
    if (editingId === null) {
      const username = usernameInput?.value.trim() || '';
      if (!/^[a-zA-Z0-9_.-]{3,32}$/.test(username)) {
        toast('用户名需为 3-32 位字母、数字、点、下划线或短横线', 'error');
        usernameInput?.focus();
        return;
      }
      if (password.length < 10) {
        toast('初始密码至少 10 位', 'error');
        passwordInput?.focus();
        return;
      }
    } else if (password && password.length < 10) {
      toast('新密码至少 10 位', 'error');
      passwordInput?.focus();
      return;
    }

    if (submitButton) submitButton.disabled = true;
    try {
      if (editingId === null) {
        await api('/api/admin/users', {
          method: 'POST',
          body: {
            username: usernameInput?.value.trim().toLowerCase(),
            password,
            display_name: displayName,
            email,
            bio: '',
            role,
          },
        });
        toast('成员已创建', 'success');
      } else {
        await api(`/api/admin/users/${editingId}`, {
          method: 'PUT',
          body: {
            display_name: displayName,
            email,
            bio: members.find((item) => item.id === editingId)?.bio || '',
            role,
            is_active: isActive,
            password,
          },
        });
        toast('成员资料已更新', 'success');
      }
      closeModal();
      await load();
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  };

  root.querySelectorAll<HTMLElement>('[data-open-user]').forEach((button) =>
    button.addEventListener('click', () => openModal(null)),
  );
  root.querySelectorAll<HTMLElement>('[data-close-user]').forEach((button) =>
    button.addEventListener('click', closeModal),
  );
  modal?.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });
  form?.addEventListener('submit', (event) => {
    event.preventDefault();
    submit();
  });
  submitButton?.addEventListener('click', submit);
  root.querySelectorAll<HTMLInputElement>('input[name="role"]').forEach((input) =>
    input.addEventListener('change', syncRoleOptions),
  );
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModal();
  });

  filters?.querySelectorAll<HTMLButtonElement>('[data-role]').forEach((button) => {
    button.addEventListener('click', () => {
      state.role = button.dataset.role || '';
      load();
    });
  });

  search?.addEventListener(
    'input',
    debounce(() => {
      state.q = search.value.trim();
      load();
    }, 320),
  );

  load();
}
