import { api } from '../lib/api';
import { errorMessage, escapeHtml, toast } from '../lib/admin-client';
import type { Term } from '../types';

interface TaxonomyResponse {
  categories: Term[];
  tags: Term[];
}

interface ModalState {
  kind: 'categories' | 'tags';
  id: number | null;
}

const root = document.querySelector<HTMLElement>('[data-taxonomy-page]');
if (root) {
  const modal = root.querySelector<HTMLElement>('[data-term-modal]');
  const modalTitle = modal?.querySelector<HTMLElement>('[data-modal-title]');
  const nameInput = modal?.querySelector<HTMLInputElement>('[data-term-name]');
  const slugInput = modal?.querySelector<HTMLInputElement>('[data-term-slug]');
  const descInput = modal?.querySelector<HTMLTextAreaElement>('[data-term-desc]');
  let state: ModalState = { kind: 'categories', id: null };

  const load = async () => {
    try {
      const data = await api<TaxonomyResponse>('/api/admin/taxonomy');
      render('categories', data.categories);
      render('tags', data.tags);
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const render = (kind: 'categories' | 'tags', terms: Term[]) => {
    const host = root.querySelector<HTMLElement>(`[data-term-list="${kind}"]`);
    if (!host) return;
    if (!terms.length) {
      host.innerHTML = '<div class="admin-empty" style="padding: 30px"><p>还没有条目。</p></div>';
      return;
    }
    host.innerHTML = terms
      .map(
        (term) => `<div class="term-row">
          <div class="term-row__main">
            <strong>${escapeHtml(term.name)}</strong>
            <span>/${escapeHtml(term.slug)}${term.description ? ` · ${escapeHtml(term.description)}` : ''}</span>
          </div>
          <span class="term-row__count">${term.count || 0}</span>
          <div class="term-row__actions">
            <button type="button" data-edit="${term.id}" data-kind="${kind}" title="编辑"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>
            <button type="button" data-delete="${term.id}" data-kind="${kind}" data-name="${escapeHtml(term.name)}" title="删除"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6"/></svg></button>
          </div>
        </div>`,
      )
      .join('');
    host.querySelectorAll<HTMLButtonElement>('[data-edit]').forEach((button) => {
      button.addEventListener('click', () => {
        const term = terms.find((item) => item.id === Number(button.dataset.edit));
        if (term) openModal(kind, term);
      });
    });
    host.querySelectorAll<HTMLButtonElement>('[data-delete]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!window.confirm(`删除「${button.dataset.name}」？文章中的关联也会被移除。`)) return;
        try {
          await api(`/api/admin/taxonomy/${kind}/${button.dataset.delete}`, { method: 'DELETE' });
          toast('已删除', 'success');
          load();
        } catch (error) {
          toast(errorMessage(error), 'error');
        }
      });
    });
  };

  const openModal = (kind: 'categories' | 'tags', term?: Term) => {
    state = { kind, id: term?.id || null };
    if (modalTitle) modalTitle.textContent = term ? '编辑条目' : kind === 'categories' ? '新建分类' : '新建标签';
    if (nameInput) nameInput.value = term?.name || '';
    if (slugInput) slugInput.value = term?.slug || '';
    if (descInput) descInput.value = term?.description || '';
    modal?.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    nameInput?.focus();
  };

  const closeModal = () => {
    modal?.classList.remove('is-open');
    document.body.style.overflow = '';
  };

  root.querySelectorAll<HTMLElement>('[data-add-term]').forEach((button) => {
    button.addEventListener('click', () => openModal(button.dataset.addTerm as 'categories' | 'tags'));
  });
  modal?.querySelectorAll('[data-close-term-modal]').forEach((button) => button.addEventListener('click', closeModal));
  modal?.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModal();
  });

  modal?.querySelector<HTMLButtonElement>('[data-save-term]')?.addEventListener('click', async () => {
    const name = nameInput?.value.trim();
    if (!name) {
      toast('名称不能为空', 'error');
      nameInput?.focus();
      return;
    }
    const body = {
      name,
      slug: slugInput?.value.trim() || '',
      description: descInput?.value.trim() || '',
    };
    const button = modal?.querySelector<HTMLButtonElement>('[data-save-term]');
    if (button) button.disabled = true;
    try {
      if (state.id) {
        await api(`/api/admin/taxonomy/${state.kind}/${state.id}`, { method: 'PUT', body });
      } else {
        await api(`/api/admin/taxonomy/${state.kind}`, { method: 'POST', body });
      }
      toast(state.id ? '已更新' : '已创建', 'success');
      closeModal();
      load();
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      if (button) button.disabled = false;
    }
  });

  load();
}
