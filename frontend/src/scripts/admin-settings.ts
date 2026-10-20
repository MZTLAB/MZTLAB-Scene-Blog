import { api } from '../lib/api';
import { errorMessage, escapeHtml, toast } from '../lib/admin-client';
import type { NavLink, SiteSettings } from '../types';

const root = document.querySelector<HTMLElement>('[data-settings-page]');
if (root) {
  const saveButton = document.querySelector<HTMLButtonElement>('[data-save-settings]');
  let settings: SiteSettings | null = null;
  const links: Record<'nav' | 'social', NavLink[]> = { nav: [], social: [] };
  const numericKeys = new Set(['posts_per_page', 'upload_max_mb']);
  const booleanKeys = new Set([
    'show_reading_time',
    'show_author',
    'show_views',
    'comments_enabled',
    'comment_moderation',
  ]);

  const tabs = root.querySelectorAll<HTMLButtonElement>('[data-settings-tab]');
  const panels = root.querySelectorAll<HTMLElement>('[data-settings-panel]');
  const activateTab = (name: string) => {
    tabs.forEach((tab) => tab.classList.toggle('is-active', tab.dataset.settingsTab === name));
    panels.forEach((panel) => panel.classList.toggle('is-active', panel.dataset.settingsPanel === name));
    window.history.replaceState(null, '', `#${name}`);
  };
  tabs.forEach((tab) => tab.addEventListener('click', () => activateTab(tab.dataset.settingsTab || 'general')));
  const hash = window.location.hash.slice(1);
  if (hash) activateTab(hash);

  root.querySelectorAll<HTMLElement>('[data-switch]').forEach((label) => {
    const input = label.querySelector<HTMLInputElement>('input[type="checkbox"]');
    if (!input) return;
    const sync = () => label.setAttribute('aria-checked', input.checked ? 'true' : 'false');
    input.addEventListener('change', sync);
    sync();
  });

  const load = async () => {
    try {
      const result = await api<{ settings: SiteSettings }>('/api/admin/settings');
      settings = result.settings;
      root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
        const key = input.dataset.setting as keyof SiteSettings;
        const value = settings?.[key];
        if (input.type === 'checkbox') (input as HTMLInputElement).checked = Boolean(value);
        else input.value = String(value ?? '');
      });
      links.nav = [...(settings.nav || [])];
      links.social = [...(settings.social || [])];
      renderLinks('nav');
      renderLinks('social');
      root.querySelectorAll<HTMLElement>('[data-switch]').forEach((label) => {
        const input = label.querySelector<HTMLInputElement>('input[type="checkbox"]');
        if (input) label.setAttribute('aria-checked', input.checked ? 'true' : 'false');
      });
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const renderLinks = (kind: 'nav' | 'social') => {
    const host = root.querySelector<HTMLElement>(`[data-links="${kind}"]`);
    if (!host) return;
    host.innerHTML = links[kind]
      .map(
        (link, index) => `<div class="nav-editor__row">
          <input type="text" value="${escapeHtml(link.label)}" placeholder="名称" data-link-label="${kind}" data-index="${index}" />
          <input type="text" value="${escapeHtml(link.url)}" placeholder="/path 或 https://" data-link-url="${kind}" data-index="${index}" />
          <button type="button" data-remove-link="${kind}" data-index="${index}" title="移除"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
        </div>`,
      )
      .join('');
    host.querySelectorAll<HTMLInputElement>('[data-link-label]').forEach((input) => {
      input.addEventListener('input', () => {
        links[input.dataset.linkLabel as 'nav' | 'social'][Number(input.dataset.index)].label = input.value;
      });
    });
    host.querySelectorAll<HTMLInputElement>('[data-link-url]').forEach((input) => {
      input.addEventListener('input', () => {
        links[input.dataset.linkUrl as 'nav' | 'social'][Number(input.dataset.index)].url = input.value;
      });
    });
    host.querySelectorAll<HTMLButtonElement>('[data-remove-link]').forEach((button) => {
      button.addEventListener('click', () => {
        links[button.dataset.removeLink as 'nav' | 'social'].splice(Number(button.dataset.index), 1);
        renderLinks(kind);
      });
    });
  };

  root.querySelectorAll<HTMLButtonElement>('[data-add-link]').forEach((button) => {
    button.addEventListener('click', () => {
      const kind = button.dataset.addLink as 'nav' | 'social';
      if (links[kind].length >= 12) return;
      links[kind].push({ label: '', url: '' });
      renderLinks(kind);
    });
  });

  const collect = () => {
    const payload: Record<string, unknown> = {};
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('[data-setting]').forEach((input) => {
      const key = input.dataset.setting!;
      if (input.type === 'checkbox') payload[key] = (input as HTMLInputElement).checked;
      else if (numericKeys.has(key)) payload[key] = Number(input.value) || 1;
      else if (booleanKeys.has(key)) payload[key] = input.value === 'true';
      else payload[key] = input.value;
    });
    payload.nav = links.nav.filter((link) => link.label.trim() && link.url.trim());
    payload.social = links.social.filter((link) => link.label.trim() && link.url.trim());
    return payload;
  };

  const save = async () => {
    if (saveButton) saveButton.disabled = true;
    try {
      const result = await api<{ settings: SiteSettings }>('/api/admin/settings', {
        method: 'PUT',
        body: collect(),
      });
      settings = result.settings;
      toast('设置已保存', 'success');
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      if (saveButton) saveButton.disabled = false;
    }
  };
  saveButton?.addEventListener('click', save);

  load();
}
