/**
 * Gallery large-image viewer.
 *
 * The whole album is laid out as a single horizontal track. Moving to the next
 * frame is one GPU transform, so the transition stays smooth even on phones:
 *
 *   track.style.transform = translate3d(-index * 100%, 0, 0)
 *
 * Keyboard (← / →), buttons, thumbnail clicks and horizontal swipes all feed
 * the same `go()` function. Clicking the image itself still opens the lightbox.
 */

const root = document.querySelector<HTMLElement>('[data-gallery-viewer]');

if (root) {
  const track = root.querySelector<HTMLElement>('[data-gv-track]');
  const slides = Array.from(root.querySelectorAll<HTMLElement>('[data-gv-slide]'));
  const prevButton = root.querySelector<HTMLButtonElement>('[data-gv-prev]');
  const nextButton = root.querySelector<HTMLButtonElement>('[data-gv-next]');
  const counter = root.querySelector<HTMLElement>('[data-gv-counter]');
  const titleNode = root.querySelector<HTMLElement>('[data-gv-title]');
  const metaNode = root.querySelector<HTMLElement>('[data-gv-meta]');
  const exifNode = root.querySelector<HTMLElement>('[data-gv-exif]');
  const captionNode = root.querySelector<HTMLElement>('[data-gv-caption]');
  const thumbnails = Array.from(root.querySelectorAll<HTMLButtonElement>('[data-gv-go]'));
  const stage = root.querySelector<HTMLElement>('.gallery-viewer__stage');
  const downloadLink = root.querySelector<HTMLAnchorElement>('[data-gv-download]');
  const count = slides.length;

  if (track && count > 0) {
    let index = 0;
    let pointerStart: { x: number; y: number; id: number } | null = null;
    let swiped = false;

    const pad = (value: number) => String(value).padStart(2, '0');

    const entry = (slide: HTMLElement) => {
      const trigger = slide.querySelector<HTMLElement>('[data-photo]');
      return {
        title: trigger?.dataset.title || '',
        caption: trigger?.dataset.caption || '',
        meta: trigger?.dataset.meta || '',
        exif: trigger?.dataset.exif || '',
      };
    };

    const warm = (target: number) => {
      if (count < 2) return;
      const slide = slides[(target + count) % count];
      const image = slide?.querySelector<HTMLImageElement>('img');
      if (!image) return;
      const preload = new Image();
      preload.src = image.currentSrc || image.src;
    };

    const go = (next: number, options: { animate?: boolean; scrollThumb?: boolean } = {}) => {
      const { animate = true, scrollThumb = true } = options;
      index = ((next % count) + count) % count;

      if (!animate) {
        track.style.transition = 'none';
        track.style.transform = `translate3d(${-index * 100}%, 0, 0)`;
        // Force a paint before restoring the transition, otherwise the first
        // programmatic move would animate from the previous position.
        void track.offsetHeight;
        track.style.transition = '';
      } else {
        track.style.transform = `translate3d(${-index * 100}%, 0, 0)`;
      }

      slides.forEach((slide, position) => {
        const active = position === index;
        slide.classList.toggle('is-active', active);
        slide.setAttribute('aria-hidden', active ? 'false' : 'true');
        const trigger = slide.querySelector<HTMLElement>('[data-photo]');
        if (trigger) trigger.tabIndex = active ? 0 : -1;
      });

      const current = entry(slides[index]);
      if (counter) counter.textContent = `${pad(index + 1)} / ${pad(count)}`;
      if (titleNode) titleNode.textContent = current.title || '未命名';
      if (metaNode) metaNode.textContent = current.meta;
      if (exifNode) exifNode.textContent = current.exif;
      if (captionNode) {
        captionNode.textContent = current.caption;
        captionNode.hidden = !current.caption;
      }

      // Original download is per-photo: hide the affordance unless allowed.
      if (downloadLink) {
        const trigger = slides[index]?.querySelector<HTMLElement>('[data-photo]');
        const url = trigger?.dataset.downloadUrl || '';
        const name = trigger?.dataset.downloadName || '';
        downloadLink.hidden = !url;
        if (url) {
          downloadLink.href = url;
          if (name) downloadLink.setAttribute('download', name);
          else downloadLink.removeAttribute('download');
        } else {
          downloadLink.removeAttribute('href');
          downloadLink.removeAttribute('download');
        }
      }

      thumbnails.forEach((thumb, position) => {
        const active = position === index;
        thumb.classList.toggle('is-active', active);
        thumb.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      if (scrollThumb && thumbnails[index]) {
        thumbnails[index].scrollIntoView({
          behavior: animate ? 'smooth' : 'auto',
          block: 'nearest',
          inline: 'center',
        });
      }

      warm(index - 1);
      warm(index + 1);
    };

    const step = (delta: number) => go(index + delta);

    prevButton?.addEventListener('click', (event) => {
      event.preventDefault();
      step(-1);
    });
    nextButton?.addEventListener('click', (event) => {
      event.preventDefault();
      step(1);
    });

    thumbnails.forEach((thumb) => {
      thumb.addEventListener('click', (event) => {
        event.preventDefault();
        const target = Number(thumb.dataset.gvGo);
        if (Number.isInteger(target)) go(target);
      });
    });

    root.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        step(-1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        step(1);
      } else if (event.key === 'Home') {
        event.preventDefault();
        go(0);
      } else if (event.key === 'End') {
        event.preventDefault();
        go(count - 1);
      }
    });

    stage?.addEventListener('pointerdown', (event) => {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      pointerStart = { x: event.clientX, y: event.clientY, id: event.pointerId };
      swiped = false;
    });

    stage?.addEventListener('pointerup', (event) => {
      if (!pointerStart || pointerStart.id !== event.pointerId) return;
      const dx = event.clientX - pointerStart.x;
      const dy = event.clientY - pointerStart.y;
      pointerStart = null;
      if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.4) {
        swiped = true;
        step(dx > 0 ? -1 : 1);
        // If the browser does not synthesise a click, do not suppress the next
        // real one.
        window.setTimeout(() => {
          swiped = false;
        }, 350);
      }
    });

    stage?.addEventListener('pointercancel', () => {
      pointerStart = null;
    });

    // A swipe should not also open the lightbox on pointerup's click.
    root.addEventListener(
      'click',
      (event) => {
        if (!swiped) return;
        event.preventDefault();
        event.stopPropagation();
        swiped = false;
      },
      true,
    );

    go(0, { animate: false, scrollThumb: false });
  }
}
