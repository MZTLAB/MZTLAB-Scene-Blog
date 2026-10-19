/**
 * Scene audio player.
 *
 * Audio blocks inserted by the editor are stored as plain `<figure class=
 * "audio-embed"><audio controls>…` so they survive Markdown, bleach and older
 * posts. This module progressively replaces the native controls with a
 * theme-matched player. It runs on public pages and in the admin editor
 * preview, and re-scans whenever content is injected (the editor renders the
 * preview without a page reload).
 */

const ICONS = {
  play: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5L8 5.5Z"/></svg>',
  pause:
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5h3.6v14H7zM13.4 5H17v14h-3.6z"/></svg>',
  volume:
    '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
  mute: '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="m16 9 5 6M21 9l-5 6"/></svg>',
};

const formatTime = (seconds: number): string => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
};

const text = (value: string): string => value.trim();

const readMeta = (figure: HTMLElement, audio: HTMLAudioElement) => {
  const titleNode = figure.querySelector<HTMLElement>('.audio-embed__title');
  const artistNode = figure.querySelector<HTMLElement>('.audio-embed__artist');
  let title = text(titleNode?.textContent || '');
  let artist = text(artistNode?.textContent || '');
  if (!title) {
    // Older embeds only have `AUDIO · Title · Artist` in the figcaption.
    const caption = text(figure.querySelector('figcaption')?.textContent || '');
    const cleaned = caption.replace(/^AUDIO\s*[·/]?\s*/i, '');
    const parts = cleaned.split('·').map((part) => part.trim()).filter(Boolean);
    title = audio.title || parts[0] || '音频';
    artist = parts[1] || '';
  }
  return { title, artist };
};

const enhance = (audio: HTMLAudioElement): void => {
  if (audio.dataset.audioEnhanced === '1') return;
  const figure = audio.closest<HTMLElement>('figure.audio-embed');
  if (!figure) return;
  audio.dataset.audioEnhanced = '1';
  audio.removeAttribute('controls');
  figure.classList.add('audio-embed--enhanced');

  const caption = figure.querySelector<HTMLElement>('figcaption');
  caption?.setAttribute('aria-hidden', 'true');
  const { title, artist } = readMeta(figure, audio);

  const player = document.createElement('div');
  player.className = 'audio-player';
  player.innerHTML = `
    <div class="audio-player__top">
      <button class="audio-player__toggle" type="button" aria-label="播放">${ICONS.play}</button>
      <div class="audio-player__meta">
        <span class="audio-player__label">
          <span class="audio-player__meter" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
          AUDIO
        </span>
        <strong class="audio-player__title"></strong>
        <span class="audio-player__artist"></span>
      </div>
      <span class="audio-player__state" data-state>READY</span>
    </div>
    <div class="audio-player__timeline">
      <span class="audio-player__time" data-current>0:00</span>
      <input class="audio-player__seek" type="range" min="0" max="1000" step="1" value="0"
        aria-label="播放进度" />
      <span class="audio-player__time" data-duration>0:00</span>
    </div>
    <div class="audio-player__foot">
      <div class="audio-player__volume">
        <button class="audio-player__mute" type="button" aria-label="静音">${ICONS.volume}</button>
        <input class="audio-player__volume-range" type="range" min="0" max="1" step="0.01" value="1"
          aria-label="音量" />
      </div>
      <span class="audio-player__hint">MZTLAB / AUDIO</span>
    </div>
  `;
  figure.append(player);

  const titleNode = player.querySelector<HTMLElement>('.audio-player__title')!;
  const artistNode = player.querySelector<HTMLElement>('.audio-player__artist')!;
  titleNode.textContent = title;
  artistNode.textContent = artist;
  artistNode.hidden = !artist;

  const toggle = player.querySelector<HTMLButtonElement>('.audio-player__toggle')!;
  const state = player.querySelector<HTMLElement>('[data-state]')!;
  const seek = player.querySelector<HTMLInputElement>('.audio-player__seek')!;
  const currentTime = player.querySelector<HTMLElement>('[data-current]')!;
  const durationTime = player.querySelector<HTMLElement>('[data-duration]')!;
  const mute = player.querySelector<HTMLButtonElement>('.audio-player__mute')!;
  const volume = player.querySelector<HTMLInputElement>('.audio-player__volume-range')!;

  let dragging = false;
  let duration = 0;

  const paintProgress = () => {
    const ratio = duration > 0 ? Math.min(1, audio.currentTime / duration) : 0;
    player.style.setProperty('--audio-progress', `${(ratio * 100).toFixed(2)}%`);
    if (!dragging) seek.value = String(Math.round(ratio * 1000));
    currentTime.textContent = formatTime(audio.currentTime);
  };

  const paintVolume = () => {
    const value = audio.muted ? 0 : audio.volume;
    volume.value = String(value);
    player.style.setProperty('--volume-progress', `${(value * 100).toFixed(2)}%`);
    mute.innerHTML = audio.muted || audio.volume === 0 ? ICONS.mute : ICONS.volume;
    mute.setAttribute('aria-label', audio.muted ? '取消静音' : '静音');
  };

  const setState = (value: string) => {
    state.textContent = value;
    player.classList.toggle('is-playing', value === 'PLAYING');
  };

  const setPlayingUi = (playing: boolean) => {
    toggle.innerHTML = playing ? ICONS.pause : ICONS.play;
    toggle.setAttribute('aria-label', playing ? '暂停' : '播放');
    if (playing) setState('PLAYING');
    else if (duration > 0 && audio.currentTime >= duration - 0.05) setState('ENDED');
    else setState(audio.currentTime > 0 ? 'PAUSED' : 'READY');
  };

  toggle.addEventListener('click', () => {
    if (audio.paused) {
      void audio.play().catch(() => setState('ERROR'));
    } else {
      audio.pause();
    }
  });

  seek.addEventListener('pointerdown', () => {
    dragging = true;
  });
  const finishSeek = () => {
    dragging = false;
  };
  seek.addEventListener('pointerup', finishSeek);
  seek.addEventListener('pointercancel', finishSeek);
  seek.addEventListener('input', () => {
    if (!duration) return;
    const ratio = Number(seek.value) / 1000;
    audio.currentTime = ratio * duration;
    currentTime.textContent = formatTime(audio.currentTime);
    player.style.setProperty('--audio-progress', `${(ratio * 100).toFixed(2)}%`);
  });
  seek.addEventListener('change', finishSeek);

  mute.addEventListener('click', () => {
    audio.muted = !audio.muted;
    paintVolume();
  });
  volume.addEventListener('input', () => {
    audio.volume = Number(volume.value);
    audio.muted = false;
    paintVolume();
  });

  audio.addEventListener('loadedmetadata', () => {
    duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    durationTime.textContent = duration ? formatTime(duration) : 'LIVE';
    seek.disabled = !duration;
    paintProgress();
  });
  audio.addEventListener('timeupdate', paintProgress);
  audio.addEventListener('play', () => {
    // One player at a time, like a small radio.
    document
      .querySelectorAll<HTMLAudioElement>('audio[data-audio-enhanced]')
      .forEach((other) => {
        if (other !== audio && !other.paused) other.pause();
      });
    setPlayingUi(true);
  });
  audio.addEventListener('pause', () => setPlayingUi(false));
  audio.addEventListener('ended', () => {
    setState('ENDED');
    setPlayingUi(false);
    paintProgress();
  });
  audio.addEventListener('volumechange', paintVolume);
  audio.addEventListener('error', () => setState('ERROR'));

  paintVolume();
  paintProgress();
};

const scan = (root: ParentNode = document): void => {
  root.querySelectorAll<HTMLAudioElement>('figure.audio-embed audio:not([data-audio-enhanced])').forEach(enhance);
};

const start = (): void => {
  scan();
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches('figure.audio-embed audio')) enhance(node as HTMLAudioElement);
        else scan(node);
      });
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start, { once: true });
} else {
  start();
}

export { enhance as enhanceAudioPlayer };
