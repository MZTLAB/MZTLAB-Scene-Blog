import { api } from '../lib/api';
import { errorMessage, toast } from '../lib/admin-client';
import { html, setHTML } from '../lib/dom';
import { jobLabel, jobProgressText, runJob, waitForJob } from '../lib/jobs';
import { buildSettingsPatch, flattenSettings } from '../lib/settings';
import type { AdminSettings, AdminSettingsResponse, NavLink } from '../types';

const root = document.querySelector<HTMLElement>('[data-settings-page]');
if (root) {
  const saveButton = document.querySelector<HTMLButtonElement>('[data-save-settings]');
  let flat: Record<string, string | boolean> = {};
  const links: Record<'nav' | 'social' | 'footer', NavLink[]> = {
    nav: [],
    social: [],
    footer: [],
  };

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

  const syncSwitches = () => {
    root.querySelectorAll<HTMLElement>('[data-switch]').forEach((label) => {
      const input = label.querySelector<HTMLInputElement>('input[type="checkbox"]');
      if (!input) return;
      label.setAttribute('aria-checked', input.checked ? 'true' : 'false');
    });
  };
  root.querySelectorAll<HTMLElement>('[data-switch]').forEach((label) => {
    const input = label.querySelector<HTMLInputElement>('input[type="checkbox"]');
    if (!input) return;
    input.addEventListener('change', syncSwitches);
  });
  syncSwitches();

  const setHint = (selector: string, text: string) => {
    const node = root.querySelector<HTMLElement>(selector);
    if (node) node.textContent = text;
  };

  const hydrate = (result: AdminSettingsResponse) => {
    const settings: AdminSettings = result.settings;
    flat = flattenSettings(settings);
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      const value = flat[input.dataset.setting!];
      if (input.type === 'checkbox') (input as HTMLInputElement).checked = Boolean(value);
      else input.value = String(value ?? '');
    });
    const image = (
      result.meta as unknown as { image?: { avif?: boolean; webp?: boolean } } | undefined
    )?.image;
    if (image) {
      setHint(
        '[data-codec-status]',
        `服务端能力：AVIF ${image.avif ? '可用' : '不可用'} · WebP ${image.webp ? '可用' : '不可用'}`,
      );
    }
    const secrets = result.storage_secrets;
    if (secrets) {
      setHint(
        '[data-storage-secrets]',
        `Access Key：${secrets.access_key_configured ? '已配置' : '未配置'} · Secret Key：${
          secrets.secret_key_configured ? '已配置' : '未配置'
        }（只从环境变量读取）`,
      );
    }
    links.nav = [...(settings.site.nav || [])];
    links.social = [...(settings.site.social || [])];
    links.footer = [...(settings.site.footer_links || [])];
    renderLinks('nav');
    renderLinks('social');
    renderLinks('footer');
    syncSwitches();
  };

  const load = async () => {
    try {
      hydrate(await api<AdminSettingsResponse>('/api/admin/settings'));
    } catch (error) {
      toast(errorMessage(error), 'error');
    }
  };

  let dragLink: { kind: 'nav' | 'social' | 'footer'; index: number } | null = null;

  const moveLink = (
    kind: 'nav' | 'social' | 'footer',
    from: number,
    to: number,
  ) => {
    const list = links[kind];
    if (from < 0 || from >= list.length || to < 0 || to >= list.length || from === to) {
      return;
    }
    const [item] = list.splice(from, 1);
    list.splice(to, 0, item);
    renderLinks(kind);
  };

  const renderLinks = (kind: 'nav' | 'social' | 'footer') => {
    const host = root.querySelector<HTMLElement>(`[data-links="${kind}"]`);
    if (!host) return;
    setHTML(
      host,
      html`${links[kind].map(
        (link, index) => html`<div class="nav-editor__row" data-link-row data-index="${index}">
          <span class="nav-editor__handle" draggable="true" tabindex="0" role="button" data-link-drag title="拖动排序（聚焦后可用 ↑ ↓ 键）" aria-label="拖动排序">⋮⋮</span>
          <input type="text" value="${link.label}" placeholder="名称" data-link-label="${kind}" data-index="${index}" />
          <input type="text" value="${link.url}" placeholder="/path 或 https://" data-link-url="${kind}" data-index="${index}" />
          <button type="button" data-remove-link="${kind}" data-index="${index}" title="移除"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
          <span class="nav-editor__move">
            <button type="button" data-link-move="${kind}" data-index="${index}" data-delta="-1" title="上移" aria-label="上移" ${index === 0 ? 'disabled' : ''}>↑</button>
            <button type="button" data-link-move="${kind}" data-index="${index}" data-delta="1" title="下移" aria-label="下移" ${index === links[kind].length - 1 ? 'disabled' : ''}>↓</button>
          </span>
        </div>`,
      )}`,
    );
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
    // Clickable ↑/↓ buttons: needed on touch screens where HTML5 drag is not
    // available. Also handy with keyboard/mouse.
    host.querySelectorAll<HTMLButtonElement>('[data-link-move]').forEach((button) => {
      button.addEventListener('click', () => {
        const from = Number(button.dataset.index);
        moveLink(kind, from, from + Number(button.dataset.delta));
      });
    });

    // Native HTML5 drag & drop on the handle; no extra library needed.
    host.querySelectorAll<HTMLElement>('[data-link-row]').forEach((row) => {
      const index = Number(row.dataset.index);
      const handle = row.querySelector<HTMLElement>('[data-link-drag]');
      handle?.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          moveLink(kind, index, index - 1);
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          moveLink(kind, index, index + 1);
        }
      });
      row.addEventListener('dragstart', (event) => {
        dragLink = { kind, index };
        row.classList.add('is-dragging');
        event.dataTransfer?.setData('text/plain', String(index));
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
      });
      row.addEventListener('dragend', () => {
        dragLink = null;
        row.classList.remove('is-dragging');
        host
          .querySelectorAll('.is-drop-target')
          .forEach((element) => element.classList.remove('is-drop-target'));
      });
      row.addEventListener('dragover', (event) => {
        if (!dragLink || dragLink.kind !== kind) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        row.classList.add('is-drop-target');
      });
      row.addEventListener('dragleave', () => row.classList.remove('is-drop-target'));
      row.addEventListener('drop', (event) => {
        event.preventDefault();
        row.classList.remove('is-drop-target');
        if (!dragLink || dragLink.kind !== kind) {
          dragLink = null;
          return;
        }
        const from = dragLink.index;
        dragLink = null;
        moveLink(kind, from, index);
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
    const values: Record<string, string | boolean> = {};
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-setting]').forEach((input) => {
      values[input.dataset.setting!] =
        input.type === 'checkbox' ? (input as HTMLInputElement).checked : input.value;
    });
    const patch = buildSettingsPatch(values);
    const site = (patch.site as Record<string, unknown> | undefined) ?? {};
    patch.site = site;
    site.nav = links.nav.filter((link) => link.label.trim() && link.url.trim());
    site.social = links.social.filter((link) => link.label.trim() && link.url.trim());
    site.footer_links = links.footer.filter((link) => link.label.trim() && link.url.trim());
    return patch;
  };

  const save = async () => {
    if (saveButton) saveButton.disabled = true;
    try {
      const result = await api<AdminSettingsResponse>('/api/admin/settings', {
        method: 'PATCH',
        body: collect(),
      });
      hydrate(result);
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

  const setJobHint = (selector: string, text: string) => {
    const node = root.querySelector<HTMLElement>(selector);
    if (node) node.textContent = text;
  };

  /** Run a background job and mirror its status into `selector`. */
  const runTrackedJob = async (
    request: { kind: string; force?: boolean },
    selector: string,
    onFinished?: () => void,
  ) => {
    const job = await runJob(request);
    setJobHint(selector, jobProgressText(job));
    const finished = await waitForJob(job, {
      intervalMs: 2000,
      onProgress: (current) => setJobHint(selector, jobProgressText(current)),
    });
    if (finished.status === 'failed') {
      toast(`${jobLabel(finished.kind)}失败：${finished.error || '未知错误'}`, 'error');
    } else if (finished.status === 'done') {
      toast(`${jobLabel(finished.kind)}完成`, 'success');
    }
    onFinished?.();
    return finished;
  };

  root.querySelector('[data-optimize-all]')?.addEventListener('click', async () => {
    if (!window.confirm('重新生成全部图片的派生图？该任务在后台执行，可能需要较长时间。')) return;
    setJobHint('[data-optimize-status]', '正在创建任务…');
    try {
      await runTrackedJob({ kind: 'reencode' }, '[data-optimize-status]');
    } catch (error) {
      setJobHint('[data-optimize-status]', '');
      toast(errorMessage(error), 'error');
    }
  });

  root.querySelector('[data-storage-sync]')?.addEventListener('click', async () => {
    const force =
      root.querySelector<HTMLInputElement>('[data-sync-force]')?.checked ?? false;
    if (force && !window.confirm('强制覆盖对象存储中已有的同名文件？')) return;
    setJobHint('[data-sync-status]', '正在创建任务…');
    try {
      await runTrackedJob(
        { kind: 'storage_sync', force },
        '[data-sync-status]',
        () => refreshStorage(),
      );
    } catch (error) {
      setJobHint('[data-sync-status]', '');
      toast(errorMessage(error), 'error');
    }
  });

  load();
  refreshStorage();
}
