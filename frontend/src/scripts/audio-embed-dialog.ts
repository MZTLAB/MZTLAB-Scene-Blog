import { api } from '../lib/api';
import { buildAudioBlock, normalizeAudioUrl } from '../lib/audio-embed';
import type { MediaItem, Paginated } from '../types';

/**
 * Small, isolated dialog for the editor's HTML5 audio embed.
 *
 * It communicates with the editor through two document events:
 *   audio-embed:open   — editor asks the dialog to open
 *   audio-embed:insert — dialog returns the generated HTML block
 *
 * This keeps the editor and the player/dialog independently replaceable.
 */
export function initAudioEmbedDialog(): void {
  const root = document.querySelector<HTMLElement>('[data-audio-dialog]');
  if (!root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';

  const form = root.querySelector<HTMLFormElement>('[data-audio-form]');
  const urlInput = root.querySelector<HTMLInputElement>('[data-audio-url]');
  const titleInput = root.querySelector<HTMLInputElement>('[data-audio-title]');
  const artistInput = root.querySelector<HTMLInputElement>('[data-audio-artist]');
  const librarySelect = root.querySelector<HTMLSelectElement>('[data-audio-library]');
  const errorNode = root.querySelector<HTMLElement>('[data-audio-error]');
  let previousOverflow = '';

  const loadLibrary = async () => {
    if (!librarySelect) return;
    try {
      const data = await api<Paginated<MediaItem>>('/api/admin/media?kind=audio&per_page=60');
      librarySelect.replaceChildren();
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = data.items.length ? '选择媒体库里的音频…' : '媒体库暂无音频';
      librarySelect.append(empty);
      data.items.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.url;
        option.textContent = `${item.original_name}${item.alt ? ` · ${item.alt}` : ''}`;
        librarySelect.append(option);
      });
    } catch {
      librarySelect.replaceChildren();
      const option = document.createElement('option');
      option.value = '';
      option.textContent = '媒体库加载失败';
      librarySelect.append(option);
    }
  };

  librarySelect?.addEventListener('change', () => {
    if (librarySelect.value && urlInput) {
      urlInput.value = librarySelect.value;
      setError('');
      titleInput?.focus();
    }
  });

  void loadLibrary();

  const setError = (message: string) => {
    if (!errorNode) return;
    errorNode.textContent = message;
    errorNode.hidden = !message;
  };

  const close = () => {
    root.classList.remove('is-open');
    document.body.style.overflow = previousOverflow;
  };

  const open = () => {
    previousOverflow = document.body.style.overflow;
    setError('');
    root.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    void loadLibrary();
    window.setTimeout(() => urlInput?.focus(), 30);
  };

  root.querySelectorAll<HTMLElement>('[data-close-audio]').forEach((button) => {
    button.addEventListener('click', close);
  });

  root.addEventListener('click', (event) => {
    if (event.target === root) close();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && root.classList.contains('is-open')) close();
  });

  document.addEventListener('audio-embed:open', open);

  form?.addEventListener('submit', (event) => {
    event.preventDefault();
    const url = urlInput?.value || '';
    if (!normalizeAudioUrl(url)) {
      setError('请输入 http(s) 音频地址，或以 / 开头的站内路径。');
      urlInput?.focus();
      return;
    }
    try {
      const markdown = buildAudioBlock({
        url,
        title: titleInput?.value || '',
        artist: artistInput?.value || '',
      });
      document.dispatchEvent(
        new CustomEvent('audio-embed:insert', { detail: { markdown } }),
      );
      close();
    } catch (error) {
      setError(error instanceof Error ? error.message : '无法生成播放器。');
    }
  });
}
