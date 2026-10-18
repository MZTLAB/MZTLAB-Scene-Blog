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

const escapeHtml = (value: string): string =>
  value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    };
    return entities[character] || character;
  });

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

/** Serialise a portable HTML block that the article sanitizer accepts. */
export function buildAudioEmbed({ url, title = '', artist = '' }: AudioEmbedOptions): string {
  const src = normalizeAudioUrl(url);
  if (!src) throw new Error('音频地址需要是 http(s) 链接或站内 / 路径');
  const safeTitle = escapeHtml(title.trim().slice(0, 120));
  const safeArtist = escapeHtml(artist.trim().slice(0, 120));
  const mime = audioMimeFor(src);
  const caption = [safeTitle, safeArtist].filter(Boolean).join(' · ');

  return [
    '<figure class="audio-embed">',
    `<figcaption><span class="audio-embed__label">AUDIO</span><span>${caption || '音乐播放器'}</span></figcaption>`,
    '<audio controls preload="metadata">',
    `<source src="${escapeHtml(src)}"${mime ? ` type="${mime}"` : ''}>`,
    '你的浏览器不支持 HTML5 音频播放。',
    '</audio>',
    '</figure>',
  ].join('\n');
}
