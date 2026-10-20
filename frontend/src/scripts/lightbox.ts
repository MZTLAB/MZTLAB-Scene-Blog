/**
 * Scene lightbox.
 *
 * Any element with `data-photo` opens the viewer. The list is read from the DOM
 * on every open, so several grids (a gallery page with related albums, the
 * photos feed) keep working without shared state.
 *
 * Elements may also carry `data-image` (the API image metadata block); when
 * present the lightbox loads the full-resolution AVIF/WebP variants directly
 * and falls back to the original URL otherwise.
 */

import {
  fallbackUrl,
  isValidImage,
  srcset,
  variantUrl,
  type ImageInfo,
} from '../lib/images';

interface PhotoEntry {
  src: string;
  image: ImageInfo | null;
  title: string;
  caption: string;
  meta: string;
  specs: Array<[string, string]>;
}

const box = document.getElementById('sceneLightbox');
const items = () =>
  Array.from(document.querySelectorAll<HTMLElement>('[data-photo]')).filter(
    (element) => !element.closest('[hidden]') && element.getClientRects().length > 0,
  );

if (box) {
  const image = box.querySelector<HTMLImageElement>('[data-lb-image]');
  const sources = {
    avif: box.querySelector<HTMLSourceElement>('[data-lb-source="avif"]'),
    webp: box.querySelector<HTMLSourceElement>('[data-lb-source="webp"]'),
  };
  const titleNode = box.querySelector<HTMLElement>('[data-lb-title]');
  const captionNode = box.querySelector<HTMLElement>('[data-lb-caption]');
  const metaNode = box.querySelector<HTMLElement>('[data-lb-meta]');
  const exifNode = box.querySelector<HTMLElement>('[data-lb-exif]');
  const counter = box.querySelector<HTMLElement>('[data-lb-counter]');
  const position = box.querySelector<HTMLElement>('[data-lb-position]');
  const closeButton = box.querySelector<HTMLButtonElement>('[data-lb-close]');
  const prevButton = box.querySelector<HTMLButtonElement>('[data-lb-prev]');
  const nextButton = box.querySelector<HTMLButtonElement>('[data-lb-next]');

  let index = 0;
  let entries: PhotoEntry[] = [];
  let lastFocused: HTMLElement | null = null;
  let touchStartX: number | null = null;

  const readEntry = (element: HTMLElement): PhotoEntry => {
    let specs: Array<[string, string]> = [];
    try {
      const parsed = JSON.parse(element.dataset.specs || '[]');
      if (Array.isArray(parsed)) {
        specs = parsed.filter(
          (item): item is [string, string] =>
            Array.isArray(item) && item.length === 2 && typeof item[1] === 'string' && item[1] !== '',
        );
      }
    } catch {
      specs = [];
    }
    let parsedImage: ImageInfo | null = null;
    try {
      const candidate = JSON.parse(element.dataset.image || 'null');
      if (isValidImage(candidate as ImageInfo | null)) parsedImage = candidate as ImageInfo;
    } catch {
      parsedImage = null;
    }
    return {
      src: element.dataset.src || '',
      image: parsedImage,
      title: element.dataset.title || '',
      caption: element.dataset.caption || '',
      meta: element.dataset.meta || '',
      specs,
    };
  };

  const pad = (value: number) => String(value).padStart(2, '0');

  /** Point `<picture>` at the full scene (AVIF/WebP) or the original URL. */
  const setSource = (entry: PhotoEntry) => {
    if (!image) return;
    const info = entry.image;
    if (info) {
      image.src = fallbackUrl(info, 'full');
      image.width = info.f;
      image.height = Math.max(1, Math.round(info.f * (info.height / info.width)));
      sources.avif?.setAttribute(
        'srcset',
        info.formats.includes('avif') ? srcset(info, 'full', 'avif') : '',
      );
      sources.webp?.setAttribute(
        'srcset',
        info.formats.includes('webp') ? srcset(info, 'full', 'webp') : '',
      );
    } else {
      sources.avif?.removeAttribute('srcset');
      sources.webp?.removeAttribute('srcset');
      image.removeAttribute('width');
      image.removeAttribute('height');
      image.src = entry.src;
    }
  };

  const warmEntry = (entry: PhotoEntry | undefined) => {
    if (!entry) return;
    const preload = new Image();
    preload.src = entry.image
      ? variantUrl(entry.image, 'full', entry.image.f, 'avif', true)
      : entry.src;
  };

  const render = (nextDirection = 0) => {
    const entry = entries[index];
    if (!entry || !image) return;
    image.classList.remove('is-entering');
    image.dataset.direction =
      nextDirection < 0 ? 'prev' : nextDirection > 0 ? 'next' : '';
    setSource(entry);
    image.alt = entry.title || entry.caption || '摄影作品';
    if (nextDirection !== 0) {
      // Restart the entrance animation on every arrow press.
      void image.offsetWidth;
      image.classList.add('is-entering');
    }
    if (titleNode) titleNode.textContent = entry.title;
    if (captionNode) captionNode.textContent = entry.caption;
    if (captionNode) captionNode.hidden = !entry.caption;
    if (metaNode) metaNode.textContent = entry.meta;
    if (exifNode) {
      exifNode.replaceChildren();
      entry.specs.forEach(([label, value]) => {
        const term = document.createElement('dt');
        const detail = document.createElement('dd');
        term.textContent = label;
        detail.textContent = value;
        exifNode.append(term, detail);
      });
      exifNode.hidden = entry.specs.length === 0;
    }
    if (counter) counter.textContent = `${pad(index + 1)} / ${pad(entries.length)}`;
    if (position) position.textContent = `${pad(index + 1)} / ${pad(entries.length)}`;
    if (prevButton) prevButton.disabled = entries.length < 2;
    if (nextButton) nextButton.disabled = entries.length < 2;

    // Warm the neighbours so arrow-key browsing feels instant.
    [index - 1, index + 1].forEach((next) => {
      if (entries.length > 1) warmEntry(entries[(next + entries.length) % entries.length]);
    });
  };

  const open = (element: HTMLElement) => {
    const list = items();
    entries = list.map(readEntry);
    index = Math.max(0, list.indexOf(element));
    lastFocused = element;
    box.hidden = false;
    box.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    render();
    closeButton?.focus();
  };

  const close = () => {
    box.hidden = true;
    box.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    lastFocused?.focus();
  };

  const step = (delta: number) => {
    if (entries.length < 2) return;
    index = (index + delta + entries.length) % entries.length;
    render(delta);
  };

  document.addEventListener('click', (event) => {
    const trigger = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-photo]');
    if (trigger) {
      event.preventDefault();
      open(trigger);
    }
  });

  closeButton?.addEventListener('click', close);
  prevButton?.addEventListener('click', () => step(-1));
  nextButton?.addEventListener('click', () => step(1));

  box.addEventListener('click', (event) => {
    if (event.target === box) close();
  });

  document.addEventListener('keydown', (event) => {
    if (box.hidden) return;
    const key = event.key;
    if (key === 'Escape') {
      close();
    } else if (key === 'ArrowLeft') {
      event.preventDefault();
      step(-1);
    } else if (key === 'ArrowRight') {
      event.preventDefault();
      step(1);
    } else if (key === 'Tab') {
      // Keep focus inside the dialog.
      const focusables = box.querySelectorAll<HTMLElement>('button');
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    }
  });

  box.addEventListener('touchstart', (event) => {
    touchStartX = event.touches[0]?.clientX ?? null;
  }, { passive: true });

  box.addEventListener('touchend', (event) => {
    if (touchStartX === null) return;
    const endX = event.changedTouches[0]?.clientX ?? touchStartX;
    const delta = endX - touchStartX;
    touchStartX = null;
    if (Math.abs(delta) > 48) step(delta > 0 ? -1 : 1);
  }, { passive: true });
}
