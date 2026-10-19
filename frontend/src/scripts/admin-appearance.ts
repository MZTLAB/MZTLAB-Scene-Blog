import { api } from '../lib/api';
import { errorMessage, toast } from '../lib/admin-client';
import type { SiteSettings } from '../types';

const root = document.querySelector<HTMLElement>('[data-appearance]');
if (root) {
  const saveButton = document.querySelector<HTMLButtonElement>('[data-save-appearance]');
  let settings: SiteSettings | null = null;

  const load = async () => {
    try {
      const result = await api<{ settings: SiteSettings }>('/api/admin/settings');
      settings = result.settings;
      hydrate(settings);
      apply();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const hydrate = (value: SiteSettings) => {
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      const key = input.dataset.setting as keyof SiteSettings;
      const current = value[key];
      if (input.type === 'checkbox') {
        (input as HTMLInputElement).checked = Boolean(current);
      } else {
        input.value = String(current ?? '');
      }
    });
    root.querySelectorAll<HTMLElement>('[data-choice]').forEach((button) => {
      const key = button.dataset.choiceGroup as keyof SiteSettings;
      button.classList.toggle('is-selected', String(value[key]) === button.dataset.choice);
      button.classList.toggle('is-active', String(value[key]) === button.dataset.choice);
    });
    updateRangeLabels();
  };

  const updateRangeLabels = () => {
    const width = root.querySelector<HTMLInputElement>('[data-setting="layout_width"]');
    const radius = root.querySelector<HTMLInputElement>('[data-setting="radius"]');
    const widthOut = root.querySelector<HTMLElement>('[data-out="layout_width"]');
    const radiusOut = root.querySelector<HTMLElement>('[data-out="radius"]');
    if (widthOut && width) widthOut.textContent = `${width.value}px`;
    if (radiusOut && radius) radiusOut.textContent = `${radius.value}px`;
  };

  const collect = () => {
    const result: Record<string, unknown> = {};
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      const key = input.dataset.setting!;
      result[key] = input.type === 'checkbox' ? (input as HTMLInputElement).checked : input.value;
    });
    ['layout_width', 'radius', 'gallery_columns'].forEach((key) => {
      if (result[key] !== undefined) result[key] = Number(result[key]);
    });
    return result;
  };

  const paletteAliases: Record<string, string> = {
    paper: 'scene',
    graphite: 'stone',
    forest: 'sand',
    ocean: 'stone',
  };

  const apply = () => {
    if (!settings) return;
    settings = { ...settings, ...(collect() as Partial<SiteSettings>) };
    const html = document.documentElement;
    html.style.setProperty('--accent', String(settings.accent));
    html.style.setProperty('--layout-width', `${settings.layout_width}px`);
    html.style.setProperty('--radius', `${settings.radius}px`);
    html.style.setProperty('--photo-columns', String(settings.gallery_columns || 3));
    const rawPalette = String(settings.theme);
    html.dataset.palette = ['scene', 'stone', 'sand', 'night'].includes(rawPalette)
      ? rawPalette
      : paletteAliases[rawPalette] || 'scene';
    html.dataset.font = String(settings.font_pair);
    const mode =
      settings.color_mode === 'system'
        ? window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light'
        : String(settings.color_mode);
    html.dataset.colorMode = mode;
    html.style.colorScheme = mode;

    const title = root.querySelector<HTMLElement>('[data-preview-title]');
    const subtitle = root.querySelector<HTMLElement>('[data-preview-subtitle]');
    const hero = root.querySelector<HTMLElement>('[data-preview-hero]');
    const siteName = root.querySelector<HTMLElement>('[data-preview-site]');
    const card = root.querySelector<HTMLElement>('[data-preview-card]');
    const accentInput = root.querySelector<HTMLInputElement>('input[type="color"][data-setting="accent"]');
    const accentText = root.querySelector<HTMLInputElement>('input[type="text"][data-setting="accent"]');
    if (accentInput) accentInput.value = String(settings.accent);
    if (accentText) accentText.value = String(settings.accent);
    if (title) title.textContent = String(settings.hero_title || '光落下的地方，就是场景。');
    if (subtitle) subtitle.textContent = String(settings.hero_subtitle || settings.description || '');
    if (siteName) siteName.textContent = String(settings.site_title);
    if (hero) {
      hero.style.display = settings.hero_show ? '' : 'none';
      hero.dataset.style = String(settings.hero_style);
    }
    if (card) {
      card.style.display = settings.post_layout === 'list' ? 'none' : '';
    }
    updateRangeLabels();
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
      const result = await api<{ settings: SiteSettings }>('/api/admin/settings', {
        method: 'PUT',
        body: collect(),
      });
      settings = result.settings;
      hydrate(settings);
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
