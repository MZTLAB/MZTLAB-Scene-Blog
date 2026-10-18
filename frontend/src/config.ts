/**
 * Front-end configuration.
 *
 * Visual tokens live in `src/styles/global.css` ("Scene" design system);
 * runtime content comes from FastAPI. This file contains only things that are
 * easier to change in code than in the admin UI.
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

export const fallbackSite = {
  settings: {
    site_title: 'MZTLAB',
    site_subtitle: 'SCENE',
    tagline: '影像与文字。',
    description: 'MZTLAB。影像与文字。',
    author_name: 'MZTLAB',
    author_bio: '以影像记录光，以文字整理观察。',
    author_avatar: '',
    theme: 'scene',
    color_mode: 'light',
    accent: '#e8481d',
    font_pair: 'mono',
    layout_width: 1400,
    radius: 0,
    hero_show: true,
    hero_eyebrow: 'MZTLAB // VISUAL_ARCHIVE',
    hero_title: '光落下。\n场景生成。',
    hero_subtitle: '影像。文字。记录。',
    hero_image: '',
    hero_style: 'split',
    post_layout: 'grid',
    posts_per_page: 9,
    gallery_columns: 3,
    home_section_title: '文字',
    home_section_subtitle: '',
    home_gallery_title: '影像相册',
    home_gallery_subtitle: '',
    show_reading_time: true,
    show_author: true,
    show_views: true,
    nav: [],
    social: [],
    footer_text: '影像与文字。',
    footer_note: 'MZTLAB // ASTRO × FASTAPI',
    custom_css: '',
    head_html: '',
    announcement: '',
    editor_manage_others: false,
    seo_description: '',
    seo_keywords: '',
    og_image: '',
    site_url: '',
    logo: '',
    favicon: '',
    icp: '',
  },
  categories: [],
  tags: [],
  post_count: 0,
  photo_count: 0,
  gallery_count: 0,
  version: '2.1.0',
};
