# 图片加载优化实现方案

> 状态：**待评审**（本文只描述方案，尚未改代码）
> 目标版本：`2.3.0` / schema `9`
> 关联需求：AVIF 编码 + 手动质量控制 · 按场景动态分辨率 · 可选 S3 兼容对象存储

---

## 0. 一句话结论

在**后端**新增一层"图片派生管线"（原图不动，按需生成 AVIF / WebP / JPEG 多尺寸副本，Pillow 11.3 已内置 AVIF），通过**带哈希的不可变 URL** 暴露；在**前端**用 `<picture>` + `srcset` + 场景预设替换现在所有裸 `<img src={原图}>`；把文件读写收敛到**存储抽象层**，`local` 为默认，`s3` 通过环境变量启用（兼容 MinIO / R2 / B2 / AWS S3）。

预期收益（同质量主观对比）：

| 格式 | 相对 JPEG 体积 | 备注 |
| --- | --- | --- |
| AVIF q≈55 | **-60% ~ -75%** | 沙箱实测：1600×1067 样图 q55≈51KB，JPEG q82≈148KB |
| WebP q≈80 | -35% ~ -50% | 给不支持 AVIF 的旧浏览器 |
| JPEG q82 | 基准 | 最终兜底 |

同时首屏图片字节数因为"按容器宽度选尺寸"再降一个数量级（列表页目前全部加载原图）。

---

## 1. 现状盘点（方案依据）

| 位置 | 现状 | 问题 |
| --- | --- | --- |
| `backend/app/routes/media.py:293-344` | 上传时 `Image.open` 校验格式/尺寸，原样写盘 `uploads/YYYY/MM/{uuid}.{ext}` | 不生成任何派生图 |
| `backend/app/main.py:147` | `app.mount("/media", MediaStaticFiles(...))` 直接静态托管原图 | 无尺寸/格式协商，无缓存头定制 |
| `backend/app/galleries.py:46,103` | `photo_dict()` 返回 `url = /media/{filename}` | 前端只能拿原图 URL |
| `backend/app/posts.py:107` | `cover_image` 是裸 URL 字符串 | 封面无法走 `<picture>` |
| `frontend/src/components/PhotoGrid.astro:62` 等 8 处 | 全部 `<img src={photo.url} loading=fetchpriority=...>` | 列表页加载 4000px 原图；无 `srcset/sizes` |
| `frontend/src/pages/media/[...path].ts` | Astro 把 `/media/*` 代理给 FastAPI | 可复用，新派生图 URL 不必新增代理页 |
| `backend/app/defaults.py` + `routes/admin.py:840` | 设置是"默认值 + 白名单 + 校验分支"三件套 | 新设置项要同步三处 + 前端 `types.ts` |
| `frontend/src/scripts/admin-settings.ts:12-20` | `numericKeys` / `booleanKeys` 决定表单值类型 | 新设置项要登记，否则存成字符串 |
| `frontend/src/scripts/lightbox.ts:53-59` | 灯箱只读 `data-src`（原图 URL） | 要改成读图元数据，选最大 AVIF |
| 依赖 | `Pillow==11.3.0`，`features.check('avif') == True`（已在本机 venv 验证） | 无需新增编码库；Docker 需启动时探测 |

关键既有约定（必须遵守，见 `docs/DEVELOPMENT.md`）：

- 新设置项：`defaults.py` → `admin.py update_settings` 白名单/校验 → `types.ts` → `config.ts(fallbackSite)` → 后台表单 `data-setting`。
- 新增列：`_ADDED_COLUMNS`；新表直接写进 `SCHEMA`（`init_db()` 每次 `executescript`，`CREATE TABLE IF NOT EXISTS` 对老库同样生效）。
- 后台脚本：根节点 `[data-*]` 存在才执行，DOM 钩子用 `data-*`，模板拼接先 `escapeHtml()`。
- 权限：写操作挂 `Depends(require_permission(...))`。
- 不提交 `backend/data/`、`frontend/dist/`。

---

## 2. 总体架构

```text
上传 (POST /api/admin/media)
  ├─ 校验格式/像素/EXIF（现有逻辑不变）
  ├─ 原图写入 Storage（local | s3）
  ├─ INSERT media（新增 avif_quality、quality 等列）
  └─ BackgroundTasks：预热常用尺寸派生图（AVIF+WebP+JPEG）

读取 (GET /media/_v/{media_id}/{hash}/{width}.{fmt})
  ├─ 命中：media_derivatives 有记录 且 Storage 里有对象 → 直接返回
  ├─ 未命中：单飞锁 → 从 Storage 读原图 → 解码/旋转/缩放/编码 → 存派生图 → 返回
  └─ 头：Cache-Control: public, max-age=31536000, immutable

API 序列化（media / photo / post cover / site hero）
  └─ 附带 image 元数据块（base、widths、formats、quality、placeholder）

前端 <SmartImage scene="tile|card|hero|viewer|full|thumb">
  └─ <picture>
       <source type="image/avif" srcset=... sizes=...>
       <source type="image/webp" srcset=... sizes=...>
       <img src=... width height loading decoding fetchpriority>
```

设计原则：

1. **原图永不覆盖**：AVIF 只作为派生副本，EXIF / 原图下载 / 旧 `/media/{path}` 全部保持可用。
2. **URL 不可变**：派生图 URL 含质量/尺寸阶梯/管线版本哈希，改质量=换 URL，天然绕开缓存。
3. **按需生成 + 上传预热**：首次访问的极端尺寸不阻塞列表，常用尺寸在上传后后台生成。
4. **渐进增强**：`image` 字段缺失（老图未回填、GIF、非图片）时自动退回现在的 `<img src>`。
5. **存储可插拔**：所有文件操作走 `storage.py`，路由不出现 `Path.write_bytes` / `open()`。

---

## 3. 详细设计

### 3.1 数据库变更

`media` 新增列（写进 `_ADDED_COLUMNS["media"]`）：

```python
"media": {
    # 0 = 继承全局设置；1-100 = 该图单独指定 AVIF 质量
    "avif_quality": "INTEGER NOT NULL DEFAULT 0",
    # 派生图管线版本：编码参数/实现变更时 +1，强制全站换 URL
    "pipeline_version": "INTEGER NOT NULL DEFAULT 1",
    # 主色占位（"#rrggbb"），可选 LQIP，无额外依赖
    "placeholder": "TEXT NOT NULL DEFAULT ''",
}
```

新表（写进 `SCHEMA`，每次启动自动创建）：

```sql
CREATE TABLE IF NOT EXISTS media_derivatives (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id   INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    width      INTEGER NOT NULL,
    format     TEXT NOT NULL,              -- avif | webp | jpeg
    quality    INTEGER NOT NULL,           -- 生成时使用的质量
    height     INTEGER NOT NULL DEFAULT 0,
    size       INTEGER NOT NULL DEFAULT 0,
    key        TEXT NOT NULL,              -- Storage 内相对 key
    created_at TEXT NOT NULL,
    UNIQUE(media_id, width, format, quality)
);
CREATE INDEX IF NOT EXISTS idx_derivatives_media ON media_derivatives(media_id, format, width);
```

`_ensure_columns` 之外不变；`SCHEMA_VERSION` 8 → 9（仅为记录，`_backfill_*` 不做数据回填，派生图走懒生成 + 后台任务）。

删除媒体时：`delete_media()` 里同时 `DELETE FROM media_derivatives` 并 `storage.delete(key)`。

### 3.2 编码与质量控制（需求 1）

新增 `backend/app/images.py`，集中所有图像计算：

```python
PIPELINE_VERSION = 1
FORMAT_EXT = {"avif": "avif", "webp": "webp", "jpeg": "jpg"}
MIME = {"avif": "image/avif", "webp": "image/webp", "jpeg": "image/jpeg"}
# AVIF 的 quality 语义 = 100 - 量化强度，55 接近 JPEG 82 的主观质量
DEFAULT_WIDTHS = (320, 480, 720, 960, 1440, 1920)
```

**质量来源优先级**（逐级覆盖）：

1. 单图 `media.avif_quality`（1-100，0 表示不覆盖）
2. 全局设置 `image_avif_quality`
3. 硬编码默认 55

**全局设置项**（`defaults.py`，全部加入 `PRIVATE_SETTING_KEYS`，不暴露到 `/api/site`）：

| key | 默认 | 校验 |
| --- | --- | --- |
| `image_avif_enabled` | `true` | bool |
| `image_avif_quality` | `55` | 1–100 |
| `image_avif_speed` | `6` | 0–10（越大越快、压缩略差） |
| `image_webp_enabled` | `true` | bool |
| `image_webp_quality` | `80` | 1–100 |
| `image_jpeg_enabled` | `true` | bool |
| `image_jpeg_quality` | `82` | 1–100 |
| `image_widths` | `"320,480,720,960,1440,1920"` | 逗号分隔、去重升序、64–4096、最多 10 个 |
| `image_max_width` | `2560` | 320–8192 |
| `image_cache_days` | `365` | 1–3650 |
| `image_prewarm` | `true` | 上传后后台预热 |
| `image_lazy_enabled` | `true` | 生成 `loading="lazy"` |

**编码实现要点**：

```python
def encode_variant(source_bytes: bytes, width: int, fmt: str, quality: int,
                   speed: int) -> tuple[bytes, int, int]:
    with Image.open(BytesIO(source_bytes)) as im:
        im = ImageOps.exif_transpose(im)          # 派生图不带方向 EXIF，必须先转正
        if getattr(im, "is_animated", False):     # 动图不派生，保留原图
            raise SkipDerivative
        if im.mode not in ("RGB", "RGBA", "L"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        im.thumbnail((width, width * 4), Image.Resampling.LANCZOS)  # 不放大
        out = BytesIO()
        if fmt == "avif":
            im.save(out, "AVIF", quality=quality, speed=speed, subsampling="4:2:0")
        elif fmt == "webp":
            im.save(out, "WEBP", quality=quality, method=4, icc_profile=im.info.get("icc_profile"))
        else:
            im.save(out, "JPEG", quality=quality, optimize=True, progressive=True,
                    icc_profile=im.info.get("icc_profile"))
        return out.getvalue(), im.width, im.height
```

- 用 `thumbnail()`（内部走 `draft`）避免把 48MP 原图完整解码成内存位图；必要时先 `im.draft("RGB", (width*2, width*2))`。
- 派生图**剥离 EXIF/GPS**（隐私 + 体积），只保留 ICC；原图保留完整 EXIF（现有 `read_exif_bytes` 逻辑不变）。
- 并发控制：模块级 `threading.Semaphore(BLOG_IMAGE_ENCODE_WORKERS, default=2)`，避免多请求打满 CPU；`threading.Lock` 做同 URL 单飞。
- **能力探测**（启动时一次）：

```python
AVIF_SUPPORTED = features.check("avif")
WEBP_SUPPORTED = features.check("webp")
```

  若 `AVIF_SUPPORTED == False`（极端情况：精简版 Linux wheel），自动降级为 WebP+JPEG 并在后台设置页显示警告；日志 `WARNING: AVIF unavailable, serving WebP/JPEG`。Docker 构建验收里加一条：

```bash
docker run --rm mztlab-backend python -c "from PIL import features; assert features.check('avif')"
```

**手动控制质量的三层入口**：

1. 后台「设置 → 图片」滑杆（全局，保存后 URL 哈希变化 → 全站重新生成）。
2. 媒体库单图覆盖：`PUT /api/admin/media/{id}` 扩展 `MediaAltIn`，新增 `avif_quality: int = 0`（0=继承）。
3. 预览调参（可选，Phase 4）：`GET /api/admin/media/{id}/preview?quality=45&width=960` 返回一张即时编码的图，后台滑块旁显示预览与体积，满意再保存（预览结果走 `no-store`，不落库）。

### 3.3 派生图 URL 与生成（核心）

**URL 形态**（复用 `/media` 前缀，前端无需新增代理路由）：

```text
/media/_v/{media_id}/{hash}/{width}.{format}
例：/media/_v/42/8f3a1c2d5e/960.avif
```

**哈希**（纯函数，序列化时即时算，无需存储）：

```python
def variants_hash(media_row, settings) -> str:
    seed = "|".join([
        str(PIPELINE_VERSION),
        str(media_row["id"]), media_row["filename"], str(media_row["size"]),
        str(media_row["avif_quality"] or settings["image_avif_quality"]),
        settings["image_widths"], str(settings["image_max_width"]),
        ",".join(enabled_formats(settings)),
    ])
    return hashlib.sha1(seed.encode()).hexdigest()[:10]
```

哈希只做缓存击穿，不参与安全校验：服务端对未知 hash **照样生成**（避免 CDN 缓存的旧 HTML 404），只是 URL 不同。真正的校验是 `fmt ∈ 允许格式`、`width ∈ 阶梯`、`media 存在且 mime 是 image/*`。

**路由**（`backend/app/routes/media_serve.py`，注册在 `/media` 兜底路由之前）：

```python
@router.get("/media/_v/{media_id}/{token}/{name}")
def derivative(media_id: int, token: str, name: str) -> Response:
    width, fmt = parse_name(name)          # "960.avif" → (960, "avif")
    row = load_media_row(media_id)          # 404 if missing / not image
    ensure_allowed(width, fmt, settings)    # 400
    key = f"_derived/{media_id}/{token}/{width}.{EXT[fmt]}"
    if storage.exists(key) and row_in_db:
        return file_response(key, immutable=True)
    data = single_flight(key, lambda: generate(row, width, fmt))
    return file_response_from_bytes(key, data, immutable=True)
```

响应头：

```http
Cache-Control: public, max-age=31536000, immutable
ETag: "<hash-width-fmt>"
Content-Type: image/avif
Vary: Accept    # 仅为未来 content-negotiation 预留，可省略
```

**原图路由改造**（`main.py`）：去掉 `app.mount("/media", StaticFiles(...))`，改为显式 `GET /media/{path:path}`：

- `local`：安全解析到 `UPLOAD_DIR`（保留 `is_relative_to` 防穿越），`FileResponse` + `ETag` + `Cache-Control: public, max-age=604800`；保留现有 `ACTIVE_MEDIA_EXTENSIONS` → attachment + sandbox CSP 的逻辑。
- `s3`：`proxy` 模式流式转发对象（同源、无需公开桶）；`redirect` 模式 302 到 `public_url` 或 60s 预签名 URL。

**生成策略（性能）**：

| 时机 | 做什么 |
| --- | --- |
| 上传成功后（`BackgroundTasks`） | 预热 `image_widths` 的常用 2-3 档（320/720/1440）× 启用格式；失败只记日志，不影响上传结果 |
| 首次请求的极端尺寸 | 同步生成 + 单飞锁 + 落库/落存储 |
| 后台「重新优化」 | `--force` 重算全部 |
| 命令行回填 | `scripts/optimize_media.py` 遍历媒体库预热（见 3.8） |

### 3.4 序列化：给前端一个完整"图元数据块"（需求 2 的服务端部分）

新增 `backend/app/images.py: image_payload(media_row_or_dict, settings)`：

```json
"image": {
  "base": "/media/_v/42/8f3a1c2d5e",
  "width": 6000,
  "height": 4000,
  "widths": [320, 480, 720, 960, 1440, 1920, 2560],
  "formats": ["avif", "webp", "jpeg"],
  "quality": 55,
  "placeholder": "#7a6a58"
}
```

URL 规律：`{base}/{w}.{ext}`，`ext` 映射 `avif→avif, webp→webp, jpeg→jpg`；`base` 在 S3 直连模式下是绝对 URL（`https://cdn.example.com/_derived/...`），前端无需区分。

覆盖范围与改动点：

| 接口/层 | 改动 |
| --- | --- |
| `routes/media.py:_serialize()` | `item["image"] = image_payload(row, settings)` |
| `galleries.py:_PHOTO_COLUMNS` | 增选 `m.width AS media_width`、`m.avif_quality AS media_quality` 等；`photo_dict()` 调 `image_payload` |
| `posts.py:serialize_post/serialize_posts` | `cover_image` 保持不变（兼容），新增 `cover` 字段：按 `cover_image` 反查 media（批量 `WHERE filename IN (...)`，避免 N+1）→ `image_payload` |
| `routes/public.py:/api/site` | 新增 `hero_image_info`、`og_image_info`（同样按 URL→filename 反查 media；查不到为 `null`） |
| `galleries.py:media_url()` | 保持原样，只新增 `image` 字段，不破坏任何旧消费者 |

> 反查失败（外链图片、文件已被删）→ `image = null`，前端自动退回 `<img src>`。

### 3.5 前端：场景预设 + `<SmartImage>`（需求 2 的前端部分）

新增 `frontend/src/lib/images.ts`：

```ts
export interface ImageInfo {
  base: string; width: number; height: number;
  widths: number[]; formats: string[]; quality: number; placeholder?: string;
}
export const EXT: Record<string, string> = { avif: 'avif', webp: 'webp', jpeg: 'jpg' };

// 场景 → 候选宽度 + sizes（浏览器再按 DPR / 容器宽度挑最终一档）
export const SCENES = {
  thumb:  { widths: [320],                  sizes: '96px' },
  tile:   { widths: [320, 480, 720],        sizes: '(max-width:720px) 50vw, 33vw' },
  card:   { widths: [480, 720, 960],        sizes: '(max-width:720px) 100vw, 50vw' },
  hero:   { widths: [960, 1440, 1920, 2560], sizes: '100vw' },
  viewer: { widths: [960, 1440, 1920],      sizes: '(max-width:900px) 100vw, 80vw' },
  full:   { widths: [1440, 1920, 2560],     sizes: '100vw' },
  prose:  { widths: [640, 960, 1280],       sizes: '(max-width:820px) 100vw, 820px' },
} as const;
export type Scene = keyof typeof SCENES;

export function srcset(image: ImageInfo, fmt: string, widths: number[]): string {
  const ws = widths.filter((w) => w <= Math.min(image.width, Math.max(...image.widths)));
  return (ws.length ? ws : image.widths).map((w) => `${image.base}/${w}.${EXT[fmt]} ${w}w`).join(', ');
}
```

新增 `frontend/src/components/SmartImage.astro`：

```astro
---
interface Props {
  image?: ImageInfo | null;
  src?: string;              // 回退：原图 URL
  alt: string;
  scene?: Scene;
  eager?: boolean;
  class?: string;
  width?: number; height?: number;
  sizes?: string;
}
const { image, src = '', alt, scene = 'card', eager = false, ... } = Astro.props;
const preset = SCENES[scene];
const formats = image?.formats ?? [];
---
{image ? (
  <picture>
    {formats.includes('avif') && <source type="image/avif" srcset={srcset(image, 'avif', preset.widths)} sizes={sizes ?? preset.sizes} />}
    {formats.includes('webp') && <source type="image/webp" srcset={srcset(image, 'webp', preset.widths)} sizes={sizes ?? preset.sizes} />}
    <img src={image.formats.includes('jpeg') ? `${image.base}/${pick(image.widths)}.jpg` : src}
         alt={alt} width={width ?? image.width} height={height ?? image.height}
         loading={eager ? 'eager' : 'lazy'} decoding="async"
         fetchpriority={eager ? 'high' : 'auto'} class={className} />
  </picture>
) : (
  <img src={src} alt={alt} width={width} height={height}
       loading={eager ? 'eager' : 'lazy'} decoding="async" class={className} />
)}
```

**组件替换清单**（每个都传 `scene`，只有首屏元素 `eager`）：

| 组件/页面 | scene | eager |
| --- | --- | --- |
| `PhotoGrid.astro` 网格 | `tile` | 前 3 张 |
| `GalleryViewer.astro` 大图 | `viewer` | 前 2 张 |
| `GalleryViewer.astro` 缩略条 | `thumb` | 否 |
| `GalleryCard.astro` 封面 | `card` | 否 |
| `StoryCard.astro` 封面 | `card` | 文章列表前 2 张 |
| `CoverArt.astro` | `card` | 跟随 `eager` |
| `HomeHero.astro` 主视觉 | `hero` | 是（配合 `<link rel="preload">`） |
| `pages/index.astro` 内联图 | `tile` / `card` | 前 3 张 |
| `pages/search.astro` 照片结果 | `thumb` | 否 |
| `pages/admin/media.astro` + `admin-media.ts` 缩略图 | `thumb` | 否 |
| `components/admin/PostEditor.astro` 媒体选择器 | `thumb` | 否 |

**灯箱 / 大图查看器**（`lightbox.ts` / `gallery-viewer.ts`）：

- 触发元素不再只写 `data-src`，增加 `data-image={JSON.stringify(image)}`（用现有 `lib/format.ts:safeJson` 防 `</script>` 注入）。
- `lightbox.ts`：`Lightbox.astro` 改成 `<picture>` 结构（`<source data-lb-source="avif">`、`<source data-lb-source="webp">`、`<img data-lb-image>`）；`render()` 按 `data-image` 生成 `full` 场景 srcset 并同步更新 `source.srcset` 与 `img.src`（JPEG 兜底），无 `image` 时退回 `data-src`。邻居预加载也换成 AVIF 最大档。
- `gallery-viewer.ts` 的 `warm()` 已经用 `currentSrc`，无需改逻辑。

**首屏 preload**：`BaseLayout.astro` 在 `<head>` 输出（仅在拿到 `hero_image_info` 且 `hero_style='image'` 时）：

```html
<link rel="preload" as="image" type="image/avif"
      imagesrcset="/media/_v/42/xx/960.avif 960w, /media/_v/42/xx/1920.avif 1920w"
      imagesizes="100vw" />
```

（`HomeHero` 的 CSS 背景也改用 `image-set()` 输出 avif/webp/jpeg 三档，复用 `lib/images.ts` 生成的字符串。）

**其它加载优化**（低成本、顺带做）：

- 网格容器 `content-visibility: auto; contain-intrinsic-size:` 对首屏外的 tile 生效，减少布局/绘制。
- `prefers-reduced-data: reduce` 或 `Save-Data: on` 时把 `sizes` 降一档（可选）。
- 占位色：`<picture>` 外层 `background: var(--ph, #ddd)`，`image.placeholder` 有值时内联 `--ph`，避免图片解码前白块。

### 3.6 存储抽象与 S3（需求 3）

新增 `backend/app/storage.py`：

```python
class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def public_url(self, key: str) -> str:          # local → "/media/{key}"
    def presigned_url(self, key: str, expires: int) -> str | None: ...

class LocalStorage(Storage):     # root = UPLOAD_DIR；public_url = f"/media/{key}"
class S3Storage(Storage):        # boto3 client；key 前缀 = BLOG_S3_PREFIX
def get_storage() -> Storage:    # 按 config 缓存实例（配置元组变化时重建）
```

**配置**（全部环境变量，`config.py`；secret 只走环境变量，不落数据库/不暴露 API）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BLOG_STORAGE_BACKEND` | `local` | `local` / `s3` |
| `BLOG_S3_BUCKET` | — | 必填（s3 模式） |
| `BLOG_S3_REGION` | `us-east-1` | |
| `BLOG_S3_ENDPOINT_URL` | — | MinIO/R2/B2 自定义端点；AWS 留空 |
| `BLOG_S3_ACCESS_KEY_ID` / `BLOG_S3_SECRET_ACCESS_KEY` | — | 留空则走 IAM Role / 容器凭证 |
| `BLOG_S3_PREFIX` | `blog` | 桶内前缀，便于同桶多站 |
| `BLOG_S3_FORCE_PATH_STYLE` | `false` | MinIO 通常 `true` |
| `BLOG_S3_PUBLIC_BASE_URL` | — | 公开桶或 CDN 域名；设置后派生图直连，不占应用带宽 |
| `BLOG_S3_SERVE_MODE` | `proxy` | `proxy`（同源流式）/ `redirect`（302 到公开 URL 或预签名） |
| `BLOG_S3_PRESIGN_SECONDS` | `300` | redirect + 私有桶时 |
| `BLOG_IMAGE_CACHE_DIR` | `{DATA_DIR}/cache` | local 模式派生图缓存目录 |
| `BLOG_IMAGE_ENCODE_WORKERS` | `2` | 并发编码上限 |

**"可选"如何体现**：

- `local` 是默认，不装 boto3 也能跑（`import boto3` 放在 `S3Storage.__init__` 里，缺失时抛清晰错误）。
- `requirements.txt` 增加 `boto3==1.40.*`；Dockerfile 不变。
- `docker-compose.yml` 增加注释块 + 可选 MinIO 服务（`profiles: ["s3"]`，默认不启动）：

```yaml
  minio:
    image: minio/minio:latest
    profiles: ["s3"]
    command: server /data --console-address ":9001"
    environment: { MINIO_ROOT_USER: blog, MINIO_ROOT_PASSWORD: change-me-now }
    ports: ["9000:9000", "9001:9001"]
    volumes: [minio_data:/data]
```

- 同机迁移：`scripts/migrate_storage.py --from local --to s3`（遍历 `media`，上传原图、校验大小、可选 `--delete-local`；派生图不迁移，按需重建）。
- 后台「设置 → 图片」展示只读存储状态：`GET /api/admin/storage/status` → `{backend, bucket, endpoint, public_url, avif, webp, objects, bytes}`；`POST /api/admin/storage/test` 做 `head_bucket` + 一次小对象读写删。

**安全注意**：

- S3 凭证永远不进入 `settings` 表、不进入 `/api/site`、不写日志。
- `public_url` 模式要求桶策略只读、不允许列举；`proxy` 模式可保持私有桶。
- 删除媒体时 `storage.delete(key)` 失败只记日志，不阻塞 DB 删除（保持现有"删记录即视为删除"的语义）。

### 3.7 后台管理界面

**设置页新增 tab**：`frontend/src/pages/admin/settings.astro` 加

```astro
<section class="settings-panel" data-settings-panel="images">
  <!-- AVIF 开关、质量滑杆 + 数字、speed 下拉、WebP/JPEG 质量、
       尺寸阶梯文本框、最大宽度、缓存天数、预热开关 -->
  <!-- 存储状态卡片（只读）+「测试连接」按钮 -->
  <!-- 「重新优化全部图片」按钮 + 进度条 -->
</section>
```

`admin-settings.ts`：

- `numericKeys` 增加 `image_avif_quality`、`image_avif_speed`、`image_webp_quality`、`image_jpeg_quality`、`image_max_width`、`image_cache_days`；
- `booleanKeys` 增加 `image_avif_enabled`、`image_webp_enabled`、`image_jpeg_enabled`、`image_prewarm`、`image_lazy_enabled`；
- 质量滑杆与数字输入双向同步（`input[type=range]` + `input[type=number]` 同一 `data-setting` 需小改 `load/collect` 兼容，或统一用 number）；
- 「重新优化全部」调用 `POST /api/admin/media/optimize-all`，轮询 `GET /api/admin/media/optimize-status`。

**媒体库单图控制**：`pages/admin/media.astro` + `scripts/admin-media.ts` 的详情/编辑区增加

- 缩略图改 `SmartImage`（scene=`thumb`）；
- “AVIF 质量（0=继承全局）”数字输入 → `PUT /api/admin/media/{id}`；
- “重新生成”按钮 → `POST /api/admin/media/{id}/optimize`（清派生记录 + 删对象 + 预热）；
- 显示派生图数量与总体积。

**新增后台接口**（`routes/media.py`，均 `require_permission("media.manage")`）：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/admin/media/{id}/optimize` | 单图强制重建派生图 |
| `POST` | `/api/admin/media/optimize-all` | 后台任务全量预热/重建 |
| `GET` | `/api/admin/media/optimize-status` | 进行中任务、完成数、失败数 |
| `GET` | `/api/admin/storage/status` | 存储后端与能力探测 |
| `POST` | `/api/admin/storage/test` | 连接自检 |
| `GET` | `/api/admin/media/{id}/preview?quality=&width=` | （可选）调参预览 |

> 路由顺序注意：`/media/optimize-all`、`/media/optimize-status` 必须定义在 `/media/{media_id}` 之前（现有 `DEVELOPMENT.md` 已记录这个坑）。

### 3.8 回填与运维脚本

- `scripts/optimize_media.py [--force] [--media-id N] [--widths ...] [--formats ...] [--dry-run]`：直接 `import app.images`，遍历 `media` 表，生成缺失派生图，打印进度与节省空间。用于升级后一次性把老图预热好（也可只回填首屏常用档）。
- `scripts/prune_derivatives.py [--older-than DAYS]`：清理不再被引用（media 已删除 / 质量变更后的旧 hash 目录）的派生对象。
- `scripts/migrate_storage.py`：local ⇄ s3。
- `scripts/run.py`、`setup.py` 不用改（依赖仍在 `requirements.txt`）。

### 3.9 需要同步的类型与兜底

- `frontend/src/types.ts`：`ImageInfo`、`MediaItem.image`、`Photo.image`、`PostSummary.cover?`、`SiteInfo.hero_image_info?` / `og_image_info?`。
- `frontend/src/config.ts` 的 `fallbackSite`：补 `hero_image_info: null`、`og_image_info: null`（后端不可达时仍能渲染）。
- `site.settings` 里的 image_* 是 private，不进 `SiteSettings` 公开类型；`AdminSettings` 沿用 `SiteSettings & { image_*: ... }` 或新增 `ImageSettings` 接口给后台表单（`GET /api/admin/settings` 返回全部）。

---

## 4. 实施阶段与验收

> 每个阶段独立可合入、可回滚。建议按顺序做，阶段 1-2 完成即有明显收益。

### Phase 1 — 后端派生管线（无前端改动也能验证）

1. `db.py`：新表 + `_ADDED_COLUMNS` + `SCHEMA_VERSION` 9。
2. `config.py`：新环境变量与目录创建。
3. `storage.py`：`LocalStorage`（S3 先留接口/抛 NotImplemented）。
4. `images.py`：能力探测、阶梯解析、哈希、编码、payload。
5. `routes/media_serve.py`：派生图路由 + `/media/{path}` 兜底路由（替换 StaticFiles）。
6. `routes/media.py`：上传后 `BackgroundTasks` 预热；`delete_media` 清理派生。
7. 单测 `tests/test_images.py`。

**验收**：上传一张图后 `curl /media/_v/{id}/{hash}/960.avif` 返回 `image/avif` 且体积 < 原图；重复请求命中缓存；`Cache-Control` 正确；老 `/media/xxx.jpg` 仍可访问。

### Phase 2 — 序列化 + 前端组件替换（收益最大）

1. `images.image_payload` 接入 `_serialize`、`photo_dict`、`posts.serialize_*`、`/api/site`。
2. `types.ts` / `config.ts` 同步。
3. 新增 `lib/images.ts` + `components/SmartImage.astro`。
4. 替换 3.5 表格中的 11 个组件/页面。
5. 灯箱/查看器数据属性与 `Lightbox.astro` 改造。
6. `BaseLayout` hero preload + CSS `image-set()`。

**验收**：`/photos` 与相册页 Network 面板中不再出现原图（除非 Lightbox 打开）；AVIF 源命中；`npm run check` / `npm run build` 通过；无 `<picture>` 的旧布局样式回归。

### Phase 3 — S3 存储

1. `S3Storage` + `requirements.txt` + `get_storage()` 缓存。
2. `/media/{path}` 与派生图路由接入 `proxy/redirect`。
3. `.env.example`、`docker-compose.yml`（可选 MinIO profile）、`README` 部署段。
4. `scripts/migrate_storage.py`。

**验收**：`BLOG_STORAGE_BACKEND=s3` + MinIO 起站，上传/展示/删除全链路通过；切回 local 数据仍可读；私有桶 + proxy 模式不泄露凭证。

### Phase 4 — 后台控制面板、回填与文档

1. 设置页「图片」tab + 存储状态 + 优化任务。
2. 媒体库单图质量/重新生成。
3. `scripts/optimize_media.py`、`prune_derivatives.py`。
4. 更新 `docs/DEVELOPMENT.md`（§5.5/§8.7/§8.11/附录 A）、`README`、`.env.example`。
5. （可选）Markdown 正文图片的 `<picture>` 升级；关键照片 LQIP（`placeholder` 已建列）。

**验收**：`unittest` 全绿；`npm run check && npm run build`；后台改质量后刷新前台 URL 变化且图更新；回填脚本对老库可重复执行。

---

## 5. 测试计划

**后端（`backend/tests/test_images.py` + `test_storage.py`）**

- 阶梯解析：去重、排序、越界丢弃、空值回退默认。
- 质量优先级：默认 < 全局 < 单图覆盖；越界夹取。
- `variants_hash` 稳定性与变更敏感性（改质量/阶梯/格式 → 变）。
- `image_payload`：widths 不超过原图、`formats` 随能力开关、外链/缺失 → None。
- 编码冒烟：内存生成 64×64 JPEG → AVIF 输出以 `ftypavif` 开头；WebP/JPEG magic 正确；透明 PNG 保持 alpha；带 EXIF Orientation=6 的图派生后尺寸交换正确。
- 路由：非法 `fmt`/`width` → 400；不存在 media → 404；`..` 路径 → 400/404。
- `LocalStorage` key 安全（拒绝 `..`）；`S3Storage` 用 `unittest.mock` 假 client 验证 key/前缀/ContentType。
- 装饰：`delete_media` 后派生记录与对象被清理。

**前端**：`npm run check` + `npm run build`；手工回归列表（首页 / `/photos` / 相册详情 / 文章列表 / 搜索 / 后台媒体库 / Lightbox 键盘与滑动）。

**性能验收**（Chrome DevTools，Fast 4G + 4× CPU 节流）：

- `/photos` LCP 图片请求体积下降 ≥ 60%；
- 列表页不再请求 > 1MB 的图片；
- 滚动到第 2 屏才触发对应图片请求（`loading=lazy`）。

---

## 6. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| AVIF 编码 CPU 高（单张 25-200ms） | 首次访问或上传变慢 | 后台预热 + 单飞锁 + 信号量限并发；`speed` 默认 6；单图失败降级 JPEG |
| 32 位/精简 Pillow 无 AVIF | 派生失败 | 启动探测 → 只用 WebP/JPEG，后台告警 |
| 内存峰值（48MP 原图解码） | OOM | `thumbnail()` + `draft()` 先缩小解码；`MAX_PIXELS` 现有上限不变 |
| 缓存 URL 变更导致旧页面 404 | 体验问题 | hash 不校验、旧目录保留到清理脚本；页面本身每次 SSR 重新序列化 |
| 磁盘占用增长（派生图 ≈ 原图 20-40%） | 存储成本 | 删除媒体级联清理；`prune_derivatives.py`；S3 模式对象存储更便宜 |
| S3 跨域/公开桶安全 | 泄露/防盗链 | 默认 `proxy` 模式；`redirect` 仅在明确配置 `PUBLIC_BASE_URL` 时；桶列出权限关闭 |
| 现有布局回归（`<picture>` 撑破容器） | 视觉错位 | `SmartImage` 始终输出 `width/height` + `display:block;max-width:100%;height:auto`；逐组件目检 |
| 类型漂移（前后端字段） | `astro check` 失败 | 严格按"后端 schema → types.ts → config fallback"三处同步 |
| 动态 GIF 被静态化 | 动图失效 | 动图跳过派生，保留原图 URL |

**回滚**：Phase 1-2 全部为增量（新增列/表/路由/字段），关掉 `image_avif_enabled` 并把前端 `SmartImage` 的 `image` 置空即可退回纯 `<img src>`；Phase 3 切回 `BLOG_STORAGE_BACKEND=local` 即恢复本地存储（迁移脚本默认不删本地文件）。

---

## 7. 需要确认的决策点

1. **S3 配置方式**：推荐"环境变量配置 + 后台只读状态/自检"（凭证不进数据库）。若希望后台可直接填 endpoint/bucket，可把**非密钥**字段放 settings，密钥仍走 env——需要确认。
2. **质量模型**：推荐"全局默认 + 单图覆盖"；是否需要**按场景不同质量**（如缩略图 q45、大图 q62，省更多流量）？实现上只是给 `encode_variant` 多传一个覆盖参数，建议做。
3. **派生前端范围**：Markdown 正文图片是否必须也升级（需要重渲染或客户端增强，成本最高）？建议先覆盖相册/封面/首屏，正文图片列为可选。
4. **是否允许直连对象存储**：若用 CDN/公开桶，`redirect` 模式可省应用带宽但图片 URL 离开主域；默认 `proxy` 更保守。
5. **尺寸阶梯默认值**：`320,480,720,960,1440,1920` + 上限 2560 是否符合你的图片源（多为 6000px 相机原图）？如主要在 1440 屏观看，可收敛到 3 档进一步省空间。

---

## 附录 A：新增/修改文件清单

**后端新增**：`app/images.py`、`app/storage.py`、`app/routes/media_serve.py`、`tests/test_images.py`、`tests/test_storage.py`、`scripts/optimize_media.py`、`scripts/prune_derivatives.py`、`scripts/migrate_storage.py`

**后端修改**：`app/config.py`、`app/db.py`、`app/defaults.py`、`app/main.py`、`app/routes/media.py`、`app/routes/admin.py`、`app/galleries.py`、`app/posts.py`、`app/routes/public.py`、`requirements.txt`、`.env.example`、`docker-compose.yml`

**前端新增**：`src/lib/images.ts`、`src/components/SmartImage.astro`

**前端修改**：`src/types.ts`、`src/config.ts`、`src/components/{PhotoGrid,GalleryViewer,GalleryCard,StoryCard,CoverArt,HomeHero,Lightbox}.astro`、`src/pages/{index,search}.astro`、`src/pages/admin/media.astro`、`src/pages/admin/settings.astro`、`src/components/admin/PostEditor.astro`、`src/layouts/BaseLayout.astro`、`src/scripts/{lightbox,admin-media,admin-settings}.ts`

**文档**：`docs/DEVELOPMENT.md`、`docs/IMAGE-PIPELINE-PLAN.md`（本文）、`README.md`

## 附录 B：默认参数速查

```text
AVIF      quality=55  speed=6  subsampling=4:2:0
WebP      quality=80  method=4
JPEG      quality=82  progressive+optimize
阶梯      320,480,720,960,1440,1920（上限 2560；原图宽更小时自动截断）
缓存      immutable, 1 year；原图 7 days
预热      上传后后台生成 320/720/1440（启用格式）
并发      2 个编码线程
降级      AVIF 不可用 → WebP/JPEG；都不可用 → 原图
```

---

## 附录 C：最终确认的决策（2026-10 评审）

评审时对第 7 节问题的答复，已按此实现（详见 `docs/DEVELOPMENT.md` 附录 C）：

1. **S3 后台可写 + R2 适配**：存储配置（endpoint / bucket / access key / secret / 公开域名 / 前缀）全部在「设置 → 图片与存储」里填写并即时生效；secret 只存服务器，接口只回传“是否已配置”。环境变量仅作容器部署兜底。
2. **按场景分质量**：`thumb/tile/card/hero/viewer/prose/full` 各自独立的 AVIF 质量；JPEG/WebP 质量为全局兜底。
3. **Markdown 正文图片也升级**：序列化文章时把 `/media/...` 的 `<img>` 重写为 `<picture>`（AVIF/WebP + JPEG 兜底），无需重渲染历史文章。
4. **允许直连**：配置了「公开访问地址」且某张图的派生集生成完成（`ready_hash` 命中）后，`<source>` 直接指向 R2/CDN；原图与 JPEG 兜底仍走 `/media` 代理，保证私有桶与旧浏览器可用。
5. **尺寸阶梯**：小图 `720`、大图 `2560`、全屏使用**原图尺寸**（`image_max_width=0` 不限制）；更小的原图不会被放大。
6. **可选本地备份**（追加需求）：`storage_backup_local` 开启后，对象存储写入的同时在本地数据目录镜像一份（原图 + 派生图，`MirrorStorage`）；备份失败只记日志，主后端缺失对象时可从本地副本回退，切回 `local` 无需迁移。

与初版方案相比的调整：

- URL 变为 `/media/_v/{media_id}/{hash}/{scene}/{width}.{ext}`（scene 进入 URL，质量才能真正按场景区分）。
- 派生图存储在 `_derived/` 命名空间；页面 `<img>` 兜底始终使用同源代理，避免直连未生成完时 404。
- 新增 `media.ready_hash` 列：只有整套变体生成完毕才切换到直连 URL。
