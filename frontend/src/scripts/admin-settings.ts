import { api } from '../lib/api';
import { errorMessage, escapeHtml, toast } from '../lib/admin-client';
import type { NavLink, SiteSettings } from '../types';

const root = document.querySelector<HTMLElement>('[data-settings-page]');
if (root) {
  const saveButton = document.querySelector<HTMLButtonElement>('[data-save-settings]');
  let settings: SiteSettings | null = null;
  const links: Record<'nav' | 'social' | 'footer', NavLink[]> = {
    nav: [],
    social: [],
    footer: [],
  };
  const numericKeys = new Set([
    'posts_per_page', 'upload_max_mb', 'image_avif_speed', 'image_webp_quality',
    'image_jpeg_quality', 'image_quality_thumb', 'image_quality_tile',
    'image_quality_card', 'image_quality_hero', 'image_quality_viewer',
    'image_quality_prose', 'image_quality_full', 'image_max_width',
    'image_cache_days',
  ]);
  const booleanKeys = new Set([
    'show_reading_time',
    'show_author',
    'show_views',
    'comments_enabled',
    'comment_moderation',
    'image_avif_enabled',
    'image_webp_enabled',
    'image_prewarm',
    'image_lazy_enabled',
    'storage_s3_path_style',
    'storage_backup_local',
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

  interface SettingsMeta {
    image?: { avif?: boolean; webp?: boolean; scenes?: string[] };
    storage?: { backends?: string[]; serve_modes?: string[] };
  }

  const setHint = (selector: string, text: string) => {
    const node = root.querySelector<HTMLElement>(selector);
    if (node) node.textContent = text;
  };

  const load = async () => {
    try {
      const result = await api<{ settings: SiteSettings; meta?: SettingsMeta }>(
        '/api/admin/settings',
      );
      settings = result.settings;
      root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
        const key = input.dataset.setting as keyof SiteSettings;
        const value = settings?.[key];
        if (input.type === 'checkbox') (input as HTMLInputElement).checked = Boolean(value);
        else input.value = String(value ?? '');
      });
      const image = result.meta?.image;
      if (image) {
        setHint(
          '[data-codec-status]',
          `服务端能力：AVIF ${image.avif ? '可用' : '不可用'} · WebP ${image.webp ? '可用' : '不可用'}`,
        );
      }
      const secretField = root.querySelector<HTMLInputElement>('[data-secret]');
      if (secretField) {
        const configured = Boolean(settings?.storage_s3_secret_key_configured);
        secretField.placeholder = configured ? '已保存，留空则不修改' : '尚未设置';
        setHint('[data-secret-hint]', configured ? '已保存密钥；填写新值可替换。' : '还没有保存密钥。');
      }
      links.nav = [...(settings.nav || [])];
      links.social = [...(settings.social || [])];
      links.footer = [...(settings.footer_links || [])];
      renderLinks('nav');
      renderLinks('social');
      renderLinks('footer');
      root.querySelectorAll<HTMLElement>('[data-switch]').forEach((label) => {
        const input = label.querySelector<HTMLInputElement>('input[type="checkbox"]');
        if (input) label.setAttribute('aria-checked', input.checked ? 'true' : 'false');
      });
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  const renderLinks = (kind: 'nav' | 'social' | 'footer') => {
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
        links[input.dataset.linkLabel as 'nav' | 'social' | 'footer'][Number(input.dataset.index)].label = input.value;
      });
    });
    host.querySelectorAll<HTMLInputElement>('[data-link-url]').forEach((input) => {
      input.addEventListener('input', () => {
        links[input.dataset.linkUrl as 'nav' | 'social' | 'footer'][Number(input.dataset.index)].url = input.value;
      });
    });
    host.querySelectorAll<HTMLButtonElement>('[data-remove-link]').forEach((button) => {
      button.addEventListener('click', () => {
        links[button.dataset.removeLink as 'nav' | 'social' | 'footer'].splice(Number(button.dataset.index), 1);
        renderLinks(kind);
      });
    });
  };

  root.querySelectorAll<HTMLButtonElement>('[data-add-link]').forEach((button) => {
    button.addEventListener('click', () => {
      const kind = button.dataset.addLink as 'nav' | 'social' | 'footer';
      if (links[kind].length >= 12) return;
      links[kind].push({ label: '', url: '' });
      renderLinks(kind);
    });
  });

  const collect = () => {
    const payload: Record<string, unknown> = {};
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      const key = input.dataset.setting!;
      if (input.type === 'checkbox') payload[key] = (input as HTMLInputElement).checked;
      else if (numericKeys.has(key)) {
        const value = Number(input.value);
        payload[key] = Number.isFinite(value) ? value : 0;
      } else if (booleanKeys.has(key)) payload[key] = input.value === 'true';
      else payload[key] = input.value;
    });
    payload.nav = links.nav.filter((link) => link.label.trim() && link.url.trim());
    payload.social = links.social.filter((link) => link.label.trim() && link.url.trim());
    payload.footer_links = links.footer.filter(
      (link) => link.label.trim() && link.url.trim(),
    );
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

  const refreshStorage = async (notify = false) => {
    const node = root.querySelector<HTMLElement>('[data-storage-status]');
    const result = root.querySelector<HTMLElement>('[data-storage-result]');
    try {
      const data = await api<{
        config: { backend: string; bucket: string; endpoint: string; direct_enabled: boolean; public_base_url: string; backup_local?: boolean };
        avif: boolean;
        webp: boolean;
        reachable: boolean | null;
        error: string;
        health?: { backup_ok?: boolean; backup_error?: string } | null;
        derivatives: { files: number; bytes: number };
      }>('/api/admin/storage/status');
      const config = data.config;
      const size = data.derivatives.files
        ? ` · 派生图 ${data.derivatives.files} 个 / ${(data.derivatives.bytes / 1024 / 1024).toFixed(1)}MB`
        : '';
      if (node) {
        node.textContent = config.backend === 's3'
          ? `${config.bucket || '未设置 bucket'}${config.direct_enabled ? ' · 直连' : ' · 代理'}${config.backup_local ? ' · 本地备份' : ''}${size}`
          : `本地磁盘${size}`;
      }
      if (result && (notify || config.backend === 's3')) {
        const reach = data.reachable === null ? '' : data.reachable ? ' · 连接正常' : ` · 连接失败：${data.error}`;
        const backupIssue = data.health && data.health.backup_ok === false ? ' · 本地备份异常' : '';
        result.textContent = `${config.backend === 's3' ? '对象存储' : '本地存储'}${reach}${backupIssue}`;
      }
    } catch (error) {
      if (result && notify) result.textContent = errorMessage(error);
    }
  };

  root.querySelector('[data-storage-refresh]')?.addEventListener('click', () => refreshStorage(true));
  root.querySelector('[data-storage-test]')?.addEventListener('click', async () => {
    const result = root.querySelector<HTMLElement>('[data-storage-result]');
    if (result) result.textContent = '正在测试…';
    try {
      const data = await api<{ ok: boolean; message: string }>('/api/admin/storage/test', {
        method: 'POST',
      });
      if (result) result.textContent = data.message;
      toast(data.message, data.ok ? 'success' : 'error');
      refreshStorage();
    } catch (error) {
      if (result) result.textContent = errorMessage(error);
      toast(errorMessage(error), 'error');
    }
  });

  const pollOptimize = async () => {
    const node = root.querySelector<HTMLElement>('[data-optimize-status]');
    try {
      const data = await api<{
        running: boolean;
        total: number;
        done: number;
        failed: number;
        error: string;
      }>('/api/admin/media/optimize-status');
      if (node) {
        node.textContent = data.running
          ? `生成中 ${data.done}/${data.total}${data.failed ? ` · 失败 ${data.failed}` : ''}`
          : data.total
            ? `上次完成 ${data.done}/${data.total}${data.failed ? ` · 失败 ${data.failed}` : ''}`
            : '';
      }
      if (data.running) window.setTimeout(pollOptimize, 2000);
    } catch {
      // the status endpoint is best-effort; the button still works
    }
  };

  root.querySelector('[data-optimize-all]')?.addEventListener('click', async () => {
    try {
      const data = await api<{ started: boolean; message?: string }>(
        '/api/admin/media/optimize-all',
        { method: 'POST' },
      );
      toast(data.message || '已开始生成派生图', 'success');
      pollOptimize();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  });

  interface StorageSyncState {
    running: boolean;
    total: number;
    uploaded: number;
    skipped: number;
    failed: number;
    bytes: number;
    current: string;
    error: string;
  }

  const renderSync = (data: StorageSyncState) => {
    const node = root.querySelector<HTMLElement>('[data-sync-status]');
    if (!node) return;
    const done = data.uploaded + data.skipped + data.failed;
    if (data.running) {
      node.textContent = `同步中 ${done}/${data.total} · 上传 ${data.uploaded} · 跳过 ${data.skipped}${
        data.failed ? ` · 失败 ${data.failed}` : ''
      }`;
    } else if (data.error) {
      node.textContent = `同步失败：${data.error}`;
    } else if (data.total) {
      node.textContent = `上次同步：上传 ${data.uploaded} · 跳过 ${data.skipped}${
        data.failed ? ` · 失败 ${data.failed}` : ''
      }`;
    }
  };

  const pollSync = async () => {
    try {
      const data = await api<StorageSyncState>('/api/admin/storage/sync-status');
      renderSync(data);
      if (data.running) {
        window.setTimeout(pollSync, 1500);
      } else {
        refreshStorage();
      }
    } catch {
      // status polling is best-effort
    }
  };

  root.querySelector('[data-storage-sync]')?.addEventListener('click', async () => {
    const force =
      root.querySelector<HTMLInputElement>('[data-sync-force]')?.checked ?? false;
    if (force && !window.confirm('强制覆盖对象存储中已有的同名文件？')) return;
    try {
      const data = await api<{ started: boolean; message?: string }>(
        '/api/admin/storage/sync',
        { method: 'POST', body: { force, scope: 'all' } },
      );
      toast(
        data.message || (force ? '已开始强制同步' : '已开始增量同步'),
        'success',
      );
      pollSync();
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  });
  pollSync();

  load();
  refreshStorage();
}
