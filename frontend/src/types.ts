export interface NavLink {
  label: string;
  url: string;
}

export interface SiteSettings {
  site_title: string;
  site_subtitle: string;
  tagline: string;
  description: string;
  site_url: string;
  logo: string;
  favicon: string;
  author_name: string;
  author_bio: string;
  author_avatar: string;
  theme: string;
  color_mode: string;
  accent: string;
  font_pair: string;
  layout_width: number;
  radius: number;
  post_layout: string;
  hero_style: string;
  hero_show: boolean;
  hero_eyebrow: string;
  hero_title: string;
  hero_subtitle: string;
  hero_image: string;
  show_reading_time: boolean;
  show_author: boolean;
  show_views: boolean;
  home_section_title: string;
  home_section_subtitle: string;
  home_gallery_title: string;
  home_gallery_subtitle: string;
  posts_per_page: number;
  gallery_columns: number;
  announcement: string;
  comments_enabled: boolean;
  comment_moderation: boolean;
  editor_manage_others: boolean;
  nav: NavLink[];
  social: NavLink[];
  footer_text: string;
  footer_note: string;
  icp: string;
  seo_description: string;
  seo_keywords: string;
  og_image: string;
  custom_css: string;
  head_html: string;
  [key: string]: unknown;
}

export interface Term {
  id: number;
  name: string;
  slug: string;
  description?: string;
  count?: number;
}

export interface SiteInfo {
  settings: SiteSettings;
  categories: Term[];
  tags: Term[];
  post_count: number;
  photo_count: number;
  gallery_count: number;
  version: string;
}

export interface Author {
  name: string;
  username?: string;
  avatar?: string;
  bio?: string;
}

export interface PostSummary {
  id: number;
  type: 'post' | 'page';
  title: string;
  slug: string;
  url: string;
  excerpt: string;
  cover_image: string;
  status: string;
  featured: boolean;
  allow_comments: boolean;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  reading_time: number;
  view_count: number;
  comment_count: number;
  author: Author;
  categories: Term[];
  tags: Term[];
  raw_status?: string;
  author_id?: number | null;
  owner_id?: number | null;
  seo_title?: string;
  seo_description?: string;
  revision_count?: number;
}

export interface TocItem {
  id: string;
  text: string;
  level: number;
}

export interface AdminPost extends PostSummary {
  content_html: string;
  content_md: string;
  toc: TocItem[];
  raw_status: string;
  author_id: number | null;
  revision_count: number;
}

export interface PostDetail extends PostSummary {
  content_html: string;
  content_md?: string;
  toc: TocItem[];
  prev: { title: string; slug: string; url: string } | null;
  next: { title: string; slug: string; url: string } | null;
  related: PostSummary[];
  canonical: string;
  comments_enabled: boolean;
  comment_moderation: boolean;
}

export interface Comment {
  id: number;
  post_id: number;
  author_name: string;
  author_email?: string;
  author_url: string;
  content: string;
  status?: string;
  created_at: string;
  post_title?: string;
  post_slug?: string;
}

export type PhotoExifField =
  | 'camera'
  | 'lens'
  | 'focal_length'
  | 'aperture'
  | 'exposure'
  | 'iso'
  | 'taken_at'
  | 'dimensions';

export interface PhotoExif {
  camera: string;
  lens: string;
  taken_at: string;
  taken_at_raw: string;
  aperture: string;
  exposure: string;
  iso: number | null;
  focal_length: string;
  focal_length_35mm: number | null;
  software: string;
  orientation: number | null;
}

export interface Photo {
  id: number;
  gallery_id: number | null;
  gallery: { id: number; title: string; slug: string; url: string } | null;
  media_id: number | null;
  url: string;
  filename: string;
  title: string;
  caption: string;
  alt: string;
  location: string;
  camera: string;
  lens: string;
  taken_at: string;
  taken_at_raw: string;
  aperture: string;
  exposure: string;
  iso: number | null;
  focal_length: string;
  focal_length_35mm: number | null;
  exif_fields: PhotoExifField[];
  exif: PhotoExif | null;
  width: number;
  height: number;
  aspect: number;
  featured: boolean;
  status: string;
  sort_order: number;
  created_at: string;
}

export interface Gallery {
  id: number;
  title: string;
  slug: string;
  url: string;
  description: string;
  status: string;
  featured: boolean;
  cover: Photo | null;
  photo_count: number;
  view_count: number;
  created_at: string;
  updated_at: string;
  author: { name: string; avatar?: string };
  cover_photo_id?: number | null;
  author_id?: number | null;
  photos?: Photo[];
  related?: Gallery[];
}

export interface Paginated<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  pages: number;
  has_prev: boolean;
  has_next: boolean;
}

export interface SearchResults {
  query: string;
  articles: PostSummary[];
  galleries: Gallery[];
}

export interface SiteStatus {
  authenticated: boolean;
  user: AdminUser | null;
  needs_setup: boolean;
}

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  email: string;
  bio: string;
  avatar: string;
  role: 'admin' | 'editor' | 'author';
  role_label?: string;
  is_active?: boolean;
  last_login_at?: string;
  permissions: string[];
  can_manage_others?: boolean;
  created_at?: string;
}

export interface Member extends AdminUser {
  role_label: string;
  is_active: boolean;
  last_login_at: string;
  created_at: string;
  content_count: number;
  gallery_count: number;
  media_count: number;
}

export interface RoleMeta {
  key: string;
  label: string;
  summary: string;
  permissions: string[];
}

export interface PermissionMeta {
  key: string;
  label: string;
}

export interface MembersMeta {
  roles: RoleMeta[];
  permissions: PermissionMeta[];
  role_labels: Record<string, string>;
}

export interface ExifGps {
  latitude: number;
  longitude: number;
  altitude?: number | null;
}

export interface ExifInfo {
  found: boolean;
  camera: string;
  make: string;
  model: string;
  lens: string;
  taken_at: string;
  taken_at_raw: string;
  exposure: string;
  aperture: string;
  iso: number | null;
  focal_length: string;
  focal_length_35mm?: number | null;
  orientation?: number | null;
  software?: string;
  artist?: string;
  copyright?: string;
  gps?: ExifGps | null;
  raw?: Record<string, unknown>;
}

export interface MediaItem {
  id: number;
  filename: string;
  original_name: string;
  kind: 'image' | 'audio';
  mime: string;
  size: number;
  width: number;
  height: number;
  alt: string;
  url: string;
  created_at: string;
  owner_id: number | null;
  owner: { id: number | null; name: string; username?: string };
  exif: ExifInfo | null;
  exif_summary?: string;
}

export interface Stats {
  posts: { all: number; published: number; draft: number; scheduled: number };
  pages: number;
  comments: { all: number; pending: number; approved: number; spam: number };
  media: number;
  galleries: number;
  photos: number;
  views: number;
  tags: number;
  categories: number;
  recent_posts: PostSummary[];
  recent_galleries: Array<{
    id: number;
    title: string;
    slug: string;
    status: string;
    updated_at: string;
    photo_count: number;
  }>;
  pending_comments: Comment[];
  recent_comments: Comment[];
  top_posts: Array<{
    id: number;
    title: string;
    slug: string;
    view_count: number;
    published_at: string | null;
  }>;
  system: { version: string; generated_at: string };
}

export interface Revision {
  id: number;
  title: string;
  excerpt: string;
  content_md: string;
  created_at: string;
  author_name: string;
  reading_time: number;
}
