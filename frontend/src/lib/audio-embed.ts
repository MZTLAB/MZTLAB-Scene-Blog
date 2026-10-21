/**
 * HTML5 audio embeds for the Markdown editor.
 *
 * The editor stores Markdown, so the player is serialised as a small,
 * sanitizer-friendly HTML block. Keeping the markup here means a future
 * player variant (cover, playlist, oEmbed provider) only has to change one
 * module.
 */

export interface AudioEmbedOptions {
  url: string;
  title?: string;
  artist?: string;
}

import { escapeHtml } from './dom';

const MIME_BY_EXTENSION: Record<string, string> = {
  mp3: 'audio/mpeg',
  m4a: 'audio/mp4',
  mp4: 'audio/mp4',
  ogg: 'audio/ogg',
  oga: 'audio/ogg',
  wav: 'audio/wav',
  flac: 'audio/flac',
  webm: 'audio/webm',
};

/**
 * Accept http(s) URLs and site-relative media paths. Reject `javascript:`,
 * protocol-relative URLs and anything the browser could execute.
 */
export function normalizeAudioUrl(raw: string): string {
  const value = raw.trim();
  if (!value) return '';
  if (/^\/(?!\/)/.test(value)) return value;
  try {
    const url = new URL(value);
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
  } catch {
    // Not an absolute URL; fall through.
  }
  return '';
}

export function audioMimeFor(url: string): string {
  const path = url.split(/[?#]/, 1)[0] || '';
  const extension = path.split('.').pop()?.toLowerCase() || '';
  return MIME_BY_EXTENSION[extension] || '';
}

/** Human-friendly fenced block inserted into the Markdown editor.
 *
 * ```audio
 * src: /media/track.mp3
 * title: Night Walk
 * artist: MZTLAB
 * ```
 *
 * The backend (`content.py: expand_audio_blocks`) turns it into the player
 * markup, so the author never has to paste HTML and the stored Markdown stays
 * readable and editable.
 */
export function buildAudioBlock({ url, title = '', artist = '' }: AudioEmbedOptions): string {
  const src = normalizeAudioUrl(url);
  if (!src) throw new Error('音频地址需要是 http(s) 链接或站内 / 路径');
  const oneLine = (value: string) => value.trim().replace(/[\r\n]+/g, ' ').slice(0, 120);
  const lines = ['```audio', `src: ${src}`];
  if (oneLine(title)) lines.push(`title: ${oneLine(title)}`);
  if (oneLine(artist)) lines.push(`artist: ${oneLine(artist)}`);
  lines.push('```');
  return lines.join('\n');
}

/** Legacy HTML builder kept for older editor flows and tests. */
export function buildAudioEmbed({ url, title = '', artist = '' }: AudioEmbedOptions): string {
  const src = normalizeAudioUrl(url);
  if (!src) throw new Error('音频地址需要是 http(s) 链接或站内 / 路径');
  const safeTitle = escapeHtml(title.trim().slice(0, 120));
  const safeArtist = escapeHtml(artist.trim().slice(0, 120));
  const mime = audioMimeFor(src);
  const displayTitle = safeTitle || '音乐播放器';
  const caption = [displayTitle, safeArtist].filter(Boolean).join(' · ');

  return [
    '<figure class="audio-embed">',
    '<figcaption>',
    '<span class="audio-embed__label">AUDIO</span>',
    `<span class="audio-embed__title">${displayTitle}</span>`,
    safeArtist ? `<span class="audio-embed__artist">${safeArtist}</span>` : '',
    '</figcaption>',
    `<audio controls preload="metadata" title="${escapeHtml(caption)}">`,
    `<source src="${escapeHtml(src)}"${mime ? ` type="${mime}"` : ''}>`,
    '你的浏览器不支持 HTML5 音频播放。',
    '</audio>',
    '</figure>',
  ]
    .filter(Boolean)
    .join('\n');
}
