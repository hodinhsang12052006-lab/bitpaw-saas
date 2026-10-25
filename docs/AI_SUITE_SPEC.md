# BitPaw AI suite — build spec (2026-10-25)

Owner's vision: (1) unified inbox — DONE (`inbox_channels.py`); (2) **AI social manager**: connects the shop's
Facebook Page, Instagram, YouTube, TikTok, Google Business Profile; AI plans the week, writes per-platform captions,
picks best times "by algorithm" (learned from the shop's own real metrics, industry defaults until enough data),
publishes images/videos on schedule, tracks REAL performance; (3) **AI Studio** makes real images AND real short
videos (AI clips, animated shop photos, free promo videos rendered in the browser from the shop's photos).

Hard rules (owner): no fake metrics/badges/claims anywhere; honest states ("needs Meta App Review", "private until
TikTok audit"); tenant currency; VI + EN UI; no OpenAI. Local and production SHARE one MongoDB — never let a local
run publish real shops' posts or write test junk that production crons would pick up. Paid AI calls cost real money:
every external base URL is env-overridable so tests run against local mocks; quotas per plan; usage ledger.

Code style: Python 3.12, Flask blueprints, pymongo, `requests` (timeouts always), comments in Vietnamese like the
rest of the repo (short, explain WHY). Files written with CRLF are fine either way. No new pip deps (no Pillow,
no boto3). Frontend: Tailwind classes ONLY if already in `static/css/tailwind.output.css` (it is prebuilt — prefer
a page-local `<style>` with your own classes, as `templates/inbox_channels.html` does), Font Awesome 6.4, CDN
scripts only from cdnjs/jsdelivr/unpkg (CSP). Global CSRF: a patched `fetch` adds `X-CSRFToken` automatically.

---------------------------------------------------------------------------------------------------------------
## 0. Shared conventions

- Time: store scheduling times as **timezone-aware UTC `datetime`** objects in Mongo (NOT iso strings). Shop
  timezone via `messaging.get_settings(bid)['timezone']` (fallback by currency: AUD→Australia/Sydney,
  USD→America/Los_Angeles, VND→Asia/Ho_Chi_Minh). API JSON returns ISO 8601 with `Z`.
- IDs: `next_mongo_id('<collection>')` from `mongo_client` (ints) for docs; GridFS ids are ObjectId strings.
- Business id in routes: `session.get('business_id') or session['user_id']`.
- Errors: raise/return codes the UI can translate: `{"success": false, "code": "<code>", "message": "<English>",
  "detail": ...}` (pattern: `inbox_channels.ChannelError.as_dict()`).
- Secrets at rest: `nurture_channel_tokens.encrypt_secret/decrypt_secret`.
- Test safety switch (both media + social): `def test_mode()` = any of `REPLICATE_API_BASE`, `SOCIAL_META_API_BASE`,
  `SOCIAL_GOOGLE_API_BASE`, `SOCIAL_GOOGLE_OAUTH_BASE`, `SOCIAL_TIKTOK_API_BASE`, `SOCIAL_GBP_API_BASE` is set.
  In test mode, background/multi-tenant work only touches `business_id in SOCIAL_TEST_BUSINESS_IDS` (comma list).
  Multi-tenant cron work (social tick) refuses to run unless `VERCEL_ENV == 'production'` or
  `SOCIAL_ALLOW_TICK=1` (and then still obeys the test-mode business filter).

## 1. `media_store.py` (NEW) — durable media in GridFS + public signed URLs

Vercel caps request/response bodies at 4.5 MB, so: keep generated videos small (5–8 s, ≤ 720p ≈ 1–4 MB), serve
with HTTP Range in ≤ 3.5 MB slices, and upload big browser files in chunks.

```
MAX_IMAGE_BYTES = 8_000_000; MAX_VIDEO_BYTES = 30_000_000; SLICE = 3_500_000
KINDS = {'ai_image','ai_video','promo_video','social_upload'}       # all 'publicly shareable by signed link'
def sniff(data) -> 'image/jpeg'|'image/png'|'image/webp'|'video/mp4'|'video/webm'|None   # magic bytes only
def save_bytes(business_id, data, kind, filename=None, meta=None) -> dict  # {file_id, content_type, size, url, public_url}
def fetch_to_store(business_id, url, kind, allowed_hosts, max_bytes, meta=None) -> dict
    # https only (http allowed only for 127.0.0.1/localhost when test_mode()), host must end with one of
    # allowed_hosts, stream with size cap, sniff content type, then save_bytes
def get(file_id, business_id=None) -> GridOut|None          # business check when business_id given
def public_token(file_id) -> str   # f"{file_id}.{hmac_sha256(FLASK_SECRET_KEY, 'media|'+file_id)[:24]}"
def public_url(file_id, ext) -> str  # '/m/<token>.<ext>' (relative; callers prefix PUBLIC base when a platform needs it)
def absolute_public_url(file_id, ext, base) -> str
def delete(file_id, business_id) -> bool
def usage_bytes(business_id) -> int
media_bp = Blueprint('media_store', __name__)
  GET /m/<token>.<ext>   public (no login): verify HMAC, kind in KINDS, Range support (206, Content-Range,
                         Accept-Ranges), each response ≤ SLICE bytes (open-ended ranges are capped; a request
                         WITHOUT Range for a file > SLICE gets 200 only if size ≤ 4_400_000 else 206 of the first
                         slice — document why), Content-Type from stored sniffed type, `Cache-Control: public,
                         max-age=31536000, immutable` (set it so app.py's no-store after_request can be skipped:
                         also set `response.headers['X-Media-Cache'] = '1'`; app.py will be patched by the
                         integrator to not override when that header is present).
  POST /api/media/upload/init   {kind:'promo_video'|'social_upload', size, content_type}  -> {upload_id}
  POST /api/media/upload/<upload_id>/chunk?index=N   raw body (≤ 3_500_000 bytes)        -> {received}
  POST /api/media/upload/<upload_id>/finish                                               -> {file_id, url, public_url}
       (login_required; chunks kept in db.media_upload_chunks with TTL-ish cleanup; finish concatenates, sniffs
        type (must match image/* or video/mp4|webm), enforces caps, saves via save_bytes, deletes chunks)
```
GridFS bucket: reuse `GridFS(db, collection='media')` (same as app.py `media_fs`). Store metadata fields:
`business_id, kind, content_type, size, source ('replicate'|'browser'|'upload'), job_id, created_at`.

## 2. `ai_media.py` (NEW) — Replicate image/video generation as async jobs + quotas

```
REPLICATE_API = os.environ.get('REPLICATE_API_BASE', 'https://api.replicate.com').rstrip('/')
OUTPUT_HOSTS = ('replicate.delivery', 'replicate.com') + ('127.0.0.1', 'localhost' only in test_mode)
MODELS = {   # official models → POST /v1/models/{owner}/{name}/predictions (no version hash)
  'image': {
    'draft':  {'model': 'black-forest-labs/flux-schnell', 'price': 0.003, 'input': lambda p,a: {prompt, aspect_ratio:a, output_format:'jpg', num_outputs:1}},
    'hd':     {'model': 'black-forest-labs/flux-1.1-pro', 'price': 0.04,  'input': {prompt, aspect_ratio, output_format:'jpg', safety_tolerance:2}},
    'poster': {'model': 'ideogram-ai/ideogram-v3-turbo',  'price': 0.03,  'input': {prompt, aspect_ratio}},   # text inside image
  },
  'video': {  # 9:16 default, 5 s; image_url optional (animate a photo)
    'draft':    {'model': 'wan-video/wan-2.2-t2v-fast' / i2v: 'wan-video/wan-2.2-i2v-fast', 'price_per_video': 0.065, 480p, interpolate_output: True},
    'standard': {'model': 'bytedance/seedance-1-pro-fast', 'price_per_second': 0.025, resolution '720p', duration 5, aspect_ratio '9:16', image (optional)},
    'premium':  {'model': 'google/veo-3.1-fast', 'price_per_second': 0.15, duration 4|8, aspect_ratio '9:16', generate_audio True, image (optional)},
  }}
```
(Builders must send only documented input names; keep the table in one place so the owner can swap models.)

Collections:
- `db.ai_media_jobs` {id, business_id, kind 'image'|'video', preset, model, prompt, source_text, aspect, duration,
  image_file_id, status 'queued'|'running'|'succeeded'|'failed'|'canceled', prediction_id, cost_estimate_usd,
  file_id, content_type, public_url, error {code,message}, is_ai_generated True, created_by user_id,
  created_at (UTC dt), updated_at, completed_at, qa_test (bool, set when test_mode())}
- `db.ai_usage` {business_id, kind 'image'|'video'|'text', units (images or seconds or tokens), cost_usd, model,
  job_id, created_at} — written once per succeeded job (idempotent: unique on job_id via check-before-insert).

Functions:
```
def quota_status(business_id) -> {'plan', 'images': {'used','limit'}, 'video_seconds': {...}, 'month'}   # limits from plans.AI_MEDIA_QUOTA
def estimate(kind, preset, duration) -> float USD
def create_job(business_id, user_id, kind, preset, prompt, aspect='9:16', duration=5, image_file_id=None,
               base_url=None) -> job dict
    # validates preset/aspect/duration; checks quota (raises MediaError('quota_exceeded')); if image_file_id:
    # the image must belong to the business (GridFS meta) — pass it to Replicate as a data: URI when ≤ 1 MB else
    # as absolute public URL (needs base_url); creates prediction with header `Prefer: wait=5` for images
    # (images usually finish in-request), webhook=f"{base_url}/api/ai_studio/replicate_webhook?job={id}" +
    # webhook_events_filter ['completed'] ONLY when base_url is https (skip locally); header 'Cancel-After: 15m'
    # for video. If the create response is already 'succeeded', persist immediately.
def refresh_job(job_id) -> job     # GET /v1/predictions/{id}; on succeeded → fetch_to_store(output url) →
                                   # status succeeded + file_id/public_url + usage row; on failed/canceled → error.
                                   # Atomic: find_one_and_update guarded by status so two refreshes never double-store.
def verify_webhook(raw_body, headers) -> bool   # Replicate/Svix scheme: signed = f"{webhook-id}.{webhook-timestamp}.{body}";
                                   # key = base64decode(secret.split('_',1)[1]); expected = base64(hmac_sha256(key, signed));
                                   # header webhook-signature has space-separated 'v1,<sig>' entries; constant-time compare;
                                   # reject timestamps older than 5 min. Secret: env REPLICATE_WEBHOOK_SECRET or
                                   # GET {REPLICATE_API}/v1/webhooks/default/secret (cache in-process).
def prompt_from_text(business_id, text, kind, lang) -> str   # DeepSeek turns a caption/script into an English
                                   # visual prompt (reuse ai_studio_bp._derive_image_prompt idea + brand DNA from
                                   # db.ai_brand_profiles; never ask for text inside the image except preset 'poster').
class MediaError(Exception): code, message
```

## 3. `ai_studio_bp.py` (MODIFY — same owner as §1–2)

Keep existing routes working (`generate_text`, `brand`). Fix: clamp `temperature` 0–1.2, `max_tokens` ≤ 2000,
bad numbers → 400; log text usage to `db.ai_usage` (kind 'text', units = max_tokens requested, cost 0 — DeepSeek
cost tracked elsewhere). New routes (all `login_required`; generation routes `role_required('admin','super_admin')`
is NOT required — staff with AI Studio access may generate; rate limit via `limiter` is applied by integrator):
```
POST /api/ai_studio/media/jobs     {kind, preset, prompt?, from_text?, aspect?, duration?, image_file_id?} -> {success, job, quota}
GET  /api/ai_studio/media/jobs/<id>  -> {success, job}     (calls refresh_job when status queued/running and
                                                            updated_at older than 4 s)
GET  /api/ai_studio/media?kind=&limit=   -> {success, items:[{id, kind, preset, prompt, status, public_url, url,
                                            content_type, created_at, cost_estimate_usd, source}], quota}
                                            (succeeded jobs + promo_video/social_upload files of the shop)
DELETE /api/ai_studio/media/<file_id>   -> deletes the shop's file (+ marks job deleted)
GET  /api/ai_studio/quota            -> quota_status
POST /api/ai_studio/replicate_webhook?job=<id>   PUBLIC (integrator adds CSRF exemption): verify_webhook → refresh_job
POST /api/ai_studio/generate_image   (legacy) → create_job(kind='image', preset='draft') and return the job
GET  /api/ai_studio/media_history    (legacy) → same as /media
POST /api/ai_studio/scene_plan {topic|script, seconds (10–30), lang} -> {scenes:[{start,end,on_screen_text,
     voiceover, visual:'photo'|'ai_image'|'text', photo_hint}], title, caption}   (DeepSeek JSON; grounded in
     _business_facts; used by the browser promo-video renderer)
```

## 4. Social manager backend (NEW files: `social_accounts.py`, `social_publisher.py`, `social_planner.py`, `social_bp.py`)

### 4.1 `social_accounts.py`
`db.social_accounts` {business_id, platform 'facebook'|'instagram'|'youtube'|'tiktok'|'google_business', status
'connected'|'needs_reconnect'|'disconnected', account_name, external_id (page id / ig user id / channel id /
open_id / 'accounts/x/locations/y'), token_enc, refresh_token_enc, token_expires_at (UTC dt), scopes [str],
connected_via 'inbox'|'token'|'oauth', connected_at, updated_at, last_error {code,message,at}}.
```
PLATFORMS = ('facebook','instagram','youtube','tiktok','google_business')
def connect_from_inbox(bid, platform)   # facebook ← inbox 'messenger' connection (page token + page id);
                                        # instagram ← inbox 'instagram' connection; verify with GET /{id}?fields=...
def connect_token(bid, platform, fields) # facebook/instagram: paste Page token (+ ig user id); verify with provider
def oauth_start_url(bid, platform, redirect_uri, state) / oauth_finish(bid, platform, code, redirect_uri)
   # youtube + google_business: Google OAuth (GOOGLE_CLIENT_ID/SECRET), access_type=offline, prompt=consent,
   #   scopes youtube: 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
   #   gbp: 'https://www.googleapis.com/auth/business.manage'; token URL base SOCIAL_GOOGLE_OAUTH_BASE.
   # tiktok: TikTok OAuth v2 (TIKTOK_CLIENT_KEY/SECRET), scopes 'user.info.basic,video.publish,video.upload',
   #   authorize https://www.tiktok.com/v2/auth/authorize/, token {SOCIAL_TIKTOK_API_BASE}/v2/oauth/token/.
   # Missing env creds → raise SocialError('app_not_configured') so the UI says "BitPaw's <platform> app is not
   #   set up yet" (owner must create the developer app) — never pretend.
def access_token(acc) -> str            # decrypt; refresh Google/TikTok tokens when expiring (< 5 min)
def public_status(bid) -> {platform: {connected, status, account_name, external_id, connected_via, last_error,
                                      requirements: [honest notes e.g. 'Meta App Review: pages_manage_posts'],
                                      can_oauth: bool (env creds present), inbox_available: bool}}
def disconnect(bid, platform); mark_needs_reconnect(bid, platform, err)
```

### 4.2 `social_publisher.py`
`db.social_posts` {id, business_id, status 'draft'|'pending_approval'|'scheduled'|'publishing'|'published'|
'partial'|'failed'|'canceled', created_by 'owner'|'ai', plan_id, caption (base), captions {platform: text},
title (YouTube), hashtags [str], link, media [{file_id, content_type, kind}], media_type 'text'|'image'|'video',
targets [{platform, status 'pending'|'processing'|'scheduled_remote'|'published'|'failed'|'skipped',
remote_id, container_id, permalink, error {code,message}, attempts, next_attempt_at, published_at, options {...}}],
scheduled_at (UTC dt|None = asap after approval), approved_by, approved_at, lease_owner, lease_until,
is_ai_generated, qa_test, created_at, updated_at}.
TikTok target options (required by TikTok's Direct Post guidelines, chosen by the owner per post, no defaults):
`privacy_level`, `disable_comment`, `disable_duet`, `disable_stitch`, `brand_content_toggle`,
`brand_organic_toggle`; AI-generated media → `is_aigc: true`.

Adapters (all base URLs env-overridable; Graph version constant `GRAPH_V = os.environ.get('SOCIAL_GRAPH_VERSION','v23.0')`):
- facebook: text → `POST /{page}/feed` {message, link?}; image → `POST /{page}/photos` multipart `source` bytes +
  `caption` (or `url`); video → `POST {video host}/{page}/videos` multipart `source` + `description`
  (video host = SOCIAL_META_VIDEO_BASE or graph-video.facebook.com; in test mode same as SOCIAL_META_API_BASE).
  If scheduled_at ≥ now+12 min: send `published=false` + `scheduled_publish_time=<unix>` → target
  'scheduled_remote' (Meta publishes on time); later `check` confirms via GET `/{id}?fields=is_published,permalink_url`.
- instagram: needs a public HTTPS URL for media (`absolute_public_url`) — JPEG for images; image →
  `POST /{ig}/media` {image_url, caption} → `POST /{ig}/media_publish` {creation_id}; video → {media_type:'REELS',
  video_url, caption, share_to_feed:true} → target 'processing' with container_id; `check` polls
  `GET /{container}?fields=status_code` until FINISHED → media_publish; ERROR → failed. Before publish read
  `GET /{ig}/content_publishing_limit` and skip with code 'ig_daily_limit' when quota_usage ≥ config.total.
  Text-only posts → target 'skipped' code 'ig_needs_media'.
- youtube (video only): resumable upload `POST {SOCIAL_GOOGLE_API_BASE}/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`
  JSON {snippet:{title, description, tags, categoryId:'22'}, status:{privacyStatus, selfDeclaredMadeForKids:false,
  containsSyntheticMedia: is_ai_generated, publishAt (if scheduled ≥ 15 min ahead: privacyStatus 'private')}}
  → Location → `PUT` bytes. Note in status: until Google audits BitPaw's app, uploads are private.
- tiktok (video only, never autopilot): `POST /v2/post/publish/creator_info/query/` (check privacy options +
  max duration) → `POST /v2/post/publish/video/init/` {post_info:{title, privacy_level, disable_comment,
  disable_duet, disable_stitch, brand_content_toggle, brand_organic_toggle, is_aigc}, source_info:{source:
  'FILE_UPLOAD', video_size, chunk_size: video_size, total_chunk_count: 1}} → `PUT upload_url` with
  `Content-Range: bytes 0-{n-1}/{n}`, `Content-Type: video/mp4` → target 'processing' with publish_id; `check`:
  `POST /v2/post/publish/status/fetch/` → PUBLISH_COMPLETE / FAILED.
- google_business: `POST {SOCIAL_GBP_API_BASE}/v4/{external_id}/localPosts` {languageCode, summary (≤1500, no
  hashtags), topicType:'STANDARD', callToAction:{actionType:'BOOK', url: booking link} when available,
  media:[{mediaFormat:'PHOTO', sourceUrl}] for images}. Video → skipped code 'gbp_no_video'.

Engine:
```
def create_post(bid, user_id, data) / update_post / approve(bid, post_id, user_id) / cancel / delete
def run_due(business_id=None, limit=10, now=None, worker='<host-pid>') -> {claimed, published, failed, processing}
   # claim: find_one_and_update({status in ['scheduled'] and scheduled_at<=now, or status in ['publishing','partial']
   #   with any target processing/pending and next_attempt_at<=now, lease_until missing or < now}, set lease 5 min)
   # per target: skip done ones; call adapter; transient errors (HTTP 5xx, Meta codes 1,2,4,17,32,341,80001,
   #   TikTok rate limit) → attempts+1, next_attempt_at = now + 2^attempts min (max 5 attempts);
   #   permanent (190 / invalid_grant / 401) → account needs_reconnect + target failed; release lease when done.
   # obey test-mode business filter (§0). Post status: all done → 'published'; some failed → 'partial';
   #   all failed → 'failed'; any processing/scheduled_remote → stays 'publishing'.
def sync_metrics(business_id=None, max_targets=30) -> int   # REAL numbers only; db.social_post_metrics
   # {business_id, post_id, platform, remote_id, fetched_at, metrics:{views, reach, likes, comments, shares, saves,
   #  clicks?}} — include only fields the API returned. FB: GET /{post-id}/insights?metric=post_media_view,
   #  post_total_media_view_unique (+ /{post-id}?fields=likes.summary(true),comments.summary(true),shares);
   #  IG: GET /{media-id}/insights?metric=views,reach,likes,comments,shares,saved; YouTube: videos?part=statistics;
   #  TikTok: POST /v2/video/query/ {filters:{video_ids}} fields view_count,like_count,comment_count,share_count.
```

### 4.3 `social_planner.py`
```
INDUSTRY_PRIORS = {industry: {platform: [(weekday 0=Mon, hour_local, weight)]}}  # sourced defaults (cite in comments)
FREQUENCY = {platform: per-week guidance for local businesses}                   # sourced defaults
def best_times(bid, platform, n=3) -> {'source': 'learned'|'default', 'slots': [{weekday, hour, score}],
     'sample_size', 'note'}   # learned = engagement per post (likes+comments+shares+saves)/max(reach or views,1)
     # by (weekday, 3-hour block) from db.social_post_metrics joined with posts, empirical-Bayes shrink toward the
     # prior with k=5; 'learned' only when ≥ 10 published posts with metrics on that platform.
def next_slot(bid, platform, after_utc) -> UTC datetime   # next best slot ≥ after (+30 min), in shop timezone
def captions(bid, base_text, platforms, lang) -> {platform: text, 'youtube_title': ...}   # DeepSeek JSON;
     # IG: ≤2200 chars + 3–8 relevant hashtags; FB: plain + link; TikTok: ≤150 chars punchy; YT title ≤ 90 +
     # description; GBP: ≤ 1500, no hashtags, ends with booking CTA. Grounded in ai_studio_bp._business_facts and
     # brand DNA; never invent prices/offers/reviews.
def weekly_plan(bid, user_id, start_date_local, platforms, posts_per_week, lang) -> plan dict + creates posts in
     status 'pending_approval', created_by 'ai', plan_id. Content mix from REAL data: services with prices,
     active promotions (db.promotions active), real product photos (GridFS kind product_image → media),
     tips/education; each post gets next best slot per platform; media: real photo when available, otherwise
     media_type 'text' with an 'image_prompt' suggestion field (no automatic paid generation).
def performance_review(bid, lang) -> {'enough_data': bool, 'text', 'top_posts': [...], 'metrics_window'}
     # if < 3 posts with metrics: enough_data False and a plain honest message WITHOUT calling the AI.
```

### 4.4 `social_bp.py` routes (blueprint; page + API; integrator registers it and the gates)
```
GET  /social                                   page (templates/social.html), login_required
GET  /api/social/accounts                      -> {success, data: public_status}
POST /api/social/accounts/<platform>           {action:'connect_inbox'|'connect_token'|'disconnect', fields?}  admin only
GET  /social/oauth/<platform>/start            -> redirect to provider (state in session, 10 min TTL)
GET  /social/oauth/<platform>/callback         -> finish, redirect /social?connected=<platform> | ?error=<code>
GET  /api/social/posts?from=&to=&status=       -> {success, data:[post...]}  (ISO times, media with urls)
POST /api/social/posts                         {caption, captions?, title?, link?, media_file_ids[], targets:
                                                [{platform, options?}], scheduled_at? (ISO with offset), status:
                                                'draft'|'scheduled'} -> {success, post}
PUT  /api/social/posts/<id>                    edit while draft/pending_approval/scheduled
POST /api/social/posts/<id>/approve            pending_approval → scheduled (admin)
POST /api/social/posts/<id>/cancel | /publish_now (runs run_due for this post synchronously, ≤ 25 s)
DELETE /api/social/posts/<id>
POST /api/social/plan/week                     {start_date, platforms[], posts_per_week, lang} -> {success, plan, posts}
POST /api/social/captions                      {text, platforms[], lang} -> {success, captions}
GET  /api/social/best_times?platform=          -> best_times
GET  /api/social/insights?days=30              -> {success, totals per platform, posts:[{post, metrics, fetched_at}]}
POST /api/social/review                        {lang} -> performance_review
POST /api/social/pump                          logged-in shop only, at most once / 2 min / shop: run_due(bid) + sync_metrics(bid, 10)
GET|POST /api/cron/social_tick                 Bearer CRON_SECRET (hmac.compare_digest); obeys §0 production/test
                                               guards; run_due(None, 25) + sync_metrics(None, 40); returns counts
```

## 5. Frontend
- `templates/social.html` (NEW): tabs Calendar (week grid in shop time + list), Compose (base caption → "AI:
  write for each platform", per-platform caption editors, media picker = AI Studio gallery + shop photos +
  upload, platform toggles with connected state, schedule: now / pick time / "best time" chips from
  /api/social/best_times with 'learned' vs 'default' label, TikTok compliance block shown only when TikTok is a
  target: privacy dropdown with NO default, comment/duet/stitch toggles off by default, branded-content
  disclosure, "By posting you agree to TikTok's Music Usage Confirmation"), Approvals (AI drafts: edit / approve /
  reject, approve all), Accounts (cards per platform with honest requirements), Performance (real metrics or an
  empty state; best-times table; "AI review" button). VI/EN via a page `const T={en,vi}` like
  `templates/inbox_channels.html`; include `components/app_sidebar.html`; mobile 390 px without horizontal scroll.
- `templates/ai-studio.html` (REWORK): add **Images** and **Video** studios (quality presets with price + remaining
  quota, aspect presets, "from my script" button, progress polling, gallery from /api/ai_studio/media, download,
  "Use in a post" → `/social?compose=1&media=<file_id>`); Video modes: AI clip (draft/standard/premium), Animate a
  photo (pick from shop photos / gallery / upload), **Free promo video** rendered in the browser (WebCodecs
  VideoEncoder H.264 + `mp4-muxer` from jsdelivr; fallback MediaRecorder WebM) at 720×1280, ~2 Mbps, from the
  scene plan (/api/ai_studio/scene_plan) + the shop's photos + on-screen text, then chunk-upload via
  /api/media/upload/*. Remove fake UI: 'Load Algorithm' tabs, 'ANTI-BOT WARMUP ON', 'Ecosystem Connected', the
  always-on 'Unique (Brand Match)' badge, '10K/500' numbers in the phone preview; fix overclaiming labels; make the
  tools reachable below 1024 px. Keep existing working text tools.

## 6. Integration (done by the integrator, not by module authors)
app.py: register `media_bp`, `social_bp`; CSRF-exempt `ai_studio.replicate_webhook`, `social.cron_social_tick`;
`limiter` on generation routes; skip no-store for `X-Media-Cache`; sidebar entry "Social / Đăng bài"; plans.py:
`('/api/ai_studio','ai_studio')`, `('/social','marketing_pro')`, `('/api/social','marketing_pro')`,
`AI_MEDIA_QUOTA`; pump hook in the sidebar; vercel.json unchanged (owner adds cron-job.org for /api/cron/social_tick).
