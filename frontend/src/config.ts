/**
 * Front-end configuration.
 *
 * Visual tokens live in `src/styles/global.css` ("Scene" design system);
 * runtime content comes from FastAPI. This file contains only things that are
 * easier to change in code than in the admin UI. Site defaults live in the
 * backend settings models — the frontend has no fallback site document.
 */
export const appConfig = {
  locale: 'zh-CN',
  dateLocale: 'zh-CN',
  requestTimeoutMs: 12_000,
  footerYear: new Date().getFullYear(),
  /** Number of flat plate palettes used when an article has no cover. */
  coverVariants: 6,
  themeName: 'Scene',
} as const;
