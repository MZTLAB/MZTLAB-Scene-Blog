import { api } from '../lib/api';
import { errorMessage, toast } from '../lib/admin-client';
import { buildSettingsPatch, flattenSettings } from '../lib/settings';
import type { AdminSettings, AdminSettingsResponse } from '../types';

const root = document.querySelector<HTMLElement>('[data-appearance]');
if (root) {
  const saveButton = document.querySelector<HTMLButtonElement>('[data-save-appearance]');
  let flat: Record<string, string | boolean> = {};

  const updateRangeLabels = () => {
    const width = root.querySelector<HTMLInputElement>('[data-setting="layout_width"]');
    const radius = root.querySelector<HTMLInputElement>('[data-setting="radius"]');
    const widthOut = root.querySelector<HTMLElement>('[data-out="layout_width"]');
    const radiusOut = root.querySelector<HTMLElement>('[data-out="radius"]');
    if (widthOut && width) widthOut.textContent = `${width.value}px`;
    if (radiusOut && radius) radiusOut.textContent = `${radius.value}px`;
  };

  const hydrate = (settings: AdminSettings) => {
    flat = flattenSettings(settings);
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      const value = flat[input.dataset.setting!];
      if (input.type === 'checkbox') {
        (input as HTMLInputElement).checked = Boolean(value);
      } else {
        input.value = String(value ?? '');
      }
    });
    root.querySelectorAll<HTMLElement>('[data-choice]').forEach((button) => {
      const group = button.dataset.choiceGroup!;
      const selected = String(flat[group] ?? '') === button.dataset.choice;
      button.classList.toggle('is-selected', selected);
      button.classList.toggle('is-active', selected);
    });
    updateRangeLabels();
  };

  const collect = (): Record<string, string | boolean> => {
    const result: Record<string, string | boolean> = {};
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      result[input.dataset.setting!] =
        input.type === 'checkbox' ? (input as HTMLInputElement).checked : input.value;
    });
    return result;
  };

  const apply = () => {
    const current: Record<string, string | boolean> = { ...flat, ...collect() };
    const html = document.documentElement;
    html.style.setProperty('--accent', String(current.accent || '#c2451f'));
    html.style.setProperty('--layout-width', `${Number(current.layout_width) || 1360}px`);
    html.style.setProperty('--radius', `${Number(current.radius) || 0}px`);
    html.style.setProperty('--photo-columns', String(Number(current.gallery_columns) || 3));
    const palette = ['scene', 'stone', 'sand', 'night'].includes(String(current.theme))
      ? String(current.theme)
      : 'scene';
    html.dataset.palette = palette;
    html.dataset.font = String(current.font_pair || 'mono');
    const mode =
      current.color_mode === 'system'
        ? window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light'
        : String(current.color_mode || 'light');
    html.dataset.colorMode = mode;
    html.style.colorScheme = mode;

    const title = root.querySelector<HTMLElement>('[data-preview-title]');
    const subtitle = root.querySelector<HTMLElement>('[data-preview-subtitle]');
    const hero = root.querySelector<HTMLElement>('[data-preview-hero]');
    const siteName = root.querySelector<HTMLElement>('[data-preview-site]');
    const card = root.querySelector<HTMLElement>('[data-preview-card]');
    const accentInput = root.querySelector<HTMLInputElement>('input[type="color"][data-setting="accent"]');
    const accentText = root.querySelector<HTMLInputElement>('input[type="text"][data-setting="accent"]');
    if (accentInput) accentInput.value = String(current.accent || '#c2451f');
    if (accentText) accentText.value = String(current.accent || '#c2451f');
    if (title) title.textContent = String(current.hero_title || '光落下的地方，就是场景。');
    if (subtitle) subtitle.textContent = String(current.hero_subtitle || current.description || '');
    if (siteName) siteName.textContent = String(current.site_title || '');
    if (hero) {
      hero.style.display = current.hero_show ? '' : 'none';
      hero.dataset.style = String(current.hero_style || 'split');
    }
    if (card) {
      card.style.display = current.post_layout === 'list' ? 'none' : '';
    }
    updateRangeLabels();
  };

  const load = async () => {
    try {
      const result = await api<AdminSettingsResponse>('/api/admin/settings');
      hydrate(result.settings);
      apply();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  root.addEventListener('input', (event) => {
    const input = event.target as HTMLInputElement;
    if (input.dataset.setting === 'accent') {
      if (/^#[0-9a-fA-F]{6}$/.test(input.value)) {
        root.querySelectorAll<HTMLInputElement>('[data-setting="accent"]').forEach((field) => {
          if (field !== input) field.value = input.value;
        });
        apply();
      }
      return;
    }
    apply();
  });

  root.querySelectorAll<HTMLElement>('[data-choice]').forEach((button) => {
    button.addEventListener('click', () => {
      const group = button.dataset.choiceGroup!;
      const value = button.dataset.choice!;
      root.querySelectorAll<HTMLElement>(`[data-choice-group="${group}"]`).forEach((item) => {
        item.classList.remove('is-selected');
        item.classList.remove('is-active');
      });
      button.classList.add('is-selected');
      button.classList.add('is-active');
      const input = root.querySelector<HTMLInputElement>(`[data-setting="${group}"]`);
      if (input) input.value = value;
      apply();
    });
  });

  const save = async () => {
    if (saveButton) saveButton.disabled = true;
    try {
      const result = await api<AdminSettingsResponse>('/api/admin/settings', {
        method: 'PATCH',
        body: buildSettingsPatch(collect(), ['site', 'appearance', 'copy']),
      });
      hydrate(result.settings);
      apply();
      toast('外观设置已保存，刷新前台即可看到变化', 'success');
    } catch (error) {
      toast(errorMessage(error), 'error');
    } finally {
      if (saveButton) saveButton.disabled = false;
    }
  };

  saveButton?.addEventListener('click', save);
  load();
}
