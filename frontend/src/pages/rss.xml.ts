import type { APIRoute } from 'astro';
import { apiServer, getSite } from '../lib/api';
import { absoluteUrl } from '../lib/format';
import type { Paginated, PostSummary } from '../types';

function escapeXml(value: string): string {
  return (value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

export const GET: APIRoute = async ({ url }) => {
  const site = await getSite();
  const settings = site.settings;
  const base = (settings.site_url || url.origin).replace(/\/$/, '');
  let items: PostSummary[] = [];
  try {
    const data = await apiServer<Paginated<PostSummary>>('/api/posts?per_page=40');
    items = data.items;
  } catch {
    items = [];
  }
  const now = items[0]?.published_at ? new Date(items[0].published_at) : new Date();
  const entries = items
    .map((post) => {
      const link = absoluteUrl(base, post.url);
      return `    <item>
      <title>${escapeXml(post.title)}</title>
      <link>${escapeXml(link)}</link>
      <guid isPermaLink="true">${escapeXml(link)}</guid>
      <pubDate>${new Date(post.published_at || Date.now()).toUTCString()}</pubDate>
      <description>${escapeXml(post.excerpt)}</description>
      ${post.categories.map((category) => `<category>${escapeXml(category.name)}</category>`).join('\n      ')}
    </item>`;
    })
    .join('\n');

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${escapeXml(settings.site_title)}</title>
    <link>${escapeXml(base)}</link>
    <description>${escapeXml(settings.description || settings.seo_description)}</description>
    <language>zh-CN</language>
    <lastBuildDate>${now.toUTCString()}</lastBuildDate>
    <atom:link href="${escapeXml(base)}/rss.xml" rel="self" type="application/rss+xml"/>
${entries}
  </channel>
</rss>`;

  return new Response(xml, {
    headers: {
      'content-type': 'application/rss+xml; charset=utf-8',
      'cache-control': 'public, max-age=300',
    },
  });
};
