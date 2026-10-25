/* promo_video.js — Video quảng cáo MIỄN PHÍ dựng ngay trong trình duyệt từ ảnh thật của tiệm (không tốn credit AI video).
   window.BitPawPromoVideo.render({scenes, photos, brand, width:720, height:1280, fps:30, bitrate:2_000_000, onProgress, signal}) -> Promise<Blob>
     - scenes: [{start, end, on_screen_text, visual:'photo'|'ai_image'|'text', photo_hint, photo?: index trong photos}] (từ /api/ai_studio/scene_plan)
     - photos: [url | File/Blob | HTMLImageElement | {src, label}] — label (tên dịch vụ/sản phẩm) để khớp với photo_hint
     - brand:  {name, cta, sub, accent:'#rrggbb'} hoặc chuỗi tên tiệm -> thẻ kết cuối video
   Đường chính: WebCodecs VideoEncoder H.264 ('avc1.42E01F') + mp4-muxer (jsdelivr) -> MP4 mà Instagram/TikTok/Facebook nhận.
   Trình duyệt không có VideoEncoder/H.264 -> canvas.captureStream + MediaRecorder (WebM; Safari ra MP4), quay theo thời gian thật.
   Video không có tiếng: nhạc có bản quyền phải chọn trong chính app TikTok/Instagram lúc đăng. */
(function (global) {
  'use strict';

  var MUXER_URL = 'https://cdn.jsdelivr.net/npm/mp4-muxer@5/build/mp4-muxer.min.js';
  // Baseline 3.1 trước (đúng hợp đồng, máy nào cũng phát). 720×1280@30 chạm đúng trần level 3.1 nên vài bộ mã hoá
  // từ chối -> thử level/profile cao hơn trước khi phải rơi về WebM.
  var AVC_CODECS = ['avc1.42E01F', 'avc1.42E020', 'avc1.4D401F', 'avc1.640028'];
  var FADE = 0.5;          // giây chồng mờ giữa 2 cảnh
  var END_CARD = 2.6;      // giây thẻ kết (tên tiệm)
  var MAX_TOTAL = 60;      // trần độ dài: 60 s × 2 Mbps ≈ 15 MB, còn dưới MAX_VIDEO_BYTES 30 MB của media_store
  var MAX_SCENES = 20;
  var MAX_PHOTOS = 12;     // mỗi ảnh giữ ~10 MB RAM sau khi giải mã — điện thoại yếu không chịu nổi nhiều hơn
  var MAX_IMG_SIDE = 1600; // thu nhỏ trước khi vẽ: đủ nét cho 1280 px có zoom 16 %, vẽ mỗi khung nhanh hơn
  var FONT = 'Inter, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
  var DEFAULT_ACCENT = '#22d3ee';

  function err(code, message) { var e = new Error(message || code); e.code = code; return e; }
  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function easeOutCubic(t) { t = clamp(t, 0, 1); return 1 - Math.pow(1 - t, 3); }
  function easeInOutSine(t) { t = clamp(t, 0, 1); return -(Math.cos(Math.PI * t) - 1) / 2; }
  function even(n) { n = Math.round(Number(n) || 0); return n % 2 ? n + 1 : n; }   // H.264 cần kích thước chẵn
  // Ngẫu nhiên CỐ ĐỊNH theo số cảnh: render lại cùng kịch bản ra cùng chuyển động
  function rand(seed) { var x = Math.sin(seed * 9301 + 49297) * 233280; return x - Math.floor(x); }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function checkAbort(signal) { if (signal && signal.aborted) throw err('aborted', 'Cancelled'); }

  // ---------- màu ----------
  function rgb(hex) {
    var m = /^#([0-9a-f]{6})$/i.exec(String(hex || ''));
    var n = parseInt(m ? m[1] : DEFAULT_ACCENT.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgba(hex, a) { var c = rgb(hex); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  function darken(hex, k) { var c = rgb(hex); return 'rgb(' + c.map(function (v) { return Math.round(v * (1 - k)); }).join(',') + ')'; }

  // ---------- kịch bản ----------
  // Xếp các cảnh nối liền từ 0 s (AI đôi khi trả mốc trùng/hở), mỗi cảnh 1.2–8 s, tổng ≤ MAX_TOTAL
  function normalizeScenes(scenes) {
    var out = [], clock = 0;
    (Array.isArray(scenes) ? scenes : []).slice(0, MAX_SCENES).forEach(function (sc) {
      if (!sc || typeof sc !== 'object') return;
      var s = Number(sc.start), e = Number(sc.end);
      var len = (isFinite(s) && isFinite(e) && e > s) ? e - s : 3;
      len = clamp(len, 1.2, 8);
      if (clock + len > MAX_TOTAL + 1e-6) return;
      var visual = sc.visual === 'text' ? 'text' : (sc.visual === 'ai_image' ? 'ai_image' : 'photo');
      var photo = (sc.photo === '' || sc.photo == null) ? null : Number(sc.photo);
      out.push({
        kind: 'scene', start: clock, end: clock + len, visual: visual,
        text: String(sc.on_screen_text || sc.text || '').replace(/\s+/g, ' ').trim().slice(0, 140),
        hint: String(sc.photo_hint || ''), photo: isFinite(photo) ? photo : null,
      });
      clock += len;
    });
    return out;
  }

  function hasEndCard(brand) { return !!(brand && (String(brand.name || '').trim() || String(brand.cta || '').trim())); }

  function planDuration(scenes, brand) {
    var items = normalizeScenes(scenes);
    if (!items.length) return 0;
    var b = typeof brand === 'string' ? { name: brand } : (brand || {});
    return items[items.length - 1].end + (hasEndCard(b) ? END_CARD : 0);
  }

  function tokens(s) {
    return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .split(/[^a-z0-9]+/).filter(function (w) { return w.length > 2; });
  }

  // Ảnh cho từng cảnh: chủ tiệm chọn tay (photo = index) > khớp photo_hint với tên ảnh > xoay vòng, tránh lặp liền nhau
  function assignPhotos(items, photos) {
    var avail = [];
    photos.forEach(function (p, i) { if (p && p.img) avail.push(i); });
    var used = {}, rr = 0, last = -1;
    items.forEach(function (it) {
      it.img = null;
      if (it.kind !== 'scene' || it.visual === 'text' || !avail.length) return;
      var pick = -1;
      if (it.photo != null && photos[it.photo] && photos[it.photo].img) pick = it.photo;
      if (pick < 0) {
        var ht = tokens(it.hint + ' ' + it.text), bestScore = 0;
        if (ht.length) avail.forEach(function (i) {
          var pt = tokens(photos[i].label), sc = 0;
          ht.forEach(function (w) { if (pt.indexOf(w) >= 0) sc += 1; });
          sc -= (used[i] || 0) * 0.6 + (i === last ? 0.5 : 0);
          if (sc > bestScore) { bestScore = sc; pick = i; }
        });
      }
      if (pick < 0) {
        // ảnh chưa dùng trước, rồi mới quay vòng
        var fresh = avail.filter(function (i) { return !used[i]; });
        pick = fresh.length ? fresh[0] : avail[rr++ % avail.length];
        if (pick === last && avail.length > 1) pick = avail[(avail.indexOf(pick) + 1) % avail.length];
      }
      it.img = photos[pick].img;
      used[pick] = (used[pick] || 0) + 1;
      last = pick;
    });
  }

  // ---------- chữ ----------
  function wrapLines(ctx, text, maxW) {
    var words = String(text || '').split(/\s+/).filter(Boolean), lines = [], cur = '';
    words.forEach(function (w) {
      // 1 từ dài hơn cả dòng (link, hashtag) -> cắt theo ký tự
      while (ctx.measureText(w).width > maxW && w.length > 1) {
        var k = w.length - 1;
        while (k > 1 && ctx.measureText(w.slice(0, k)).width > maxW) k--;
        if (cur) { lines.push(cur); cur = ''; }
        lines.push(w.slice(0, k)); w = w.slice(k);
      }
      var test = cur ? cur + ' ' + w : w;
      if (ctx.measureText(test).width <= maxW) cur = test;
      else { if (cur) lines.push(cur); cur = w; }
    });
    if (cur) lines.push(cur);
    return lines;
  }

  // Cỡ chữ lớn nhất vừa maxLines dòng — chữ phải đọc được trên điện thoại khi lướt nhanh
  function fitText(ctx, text, maxW, maxLines, big, small, weight) {
    var step = Math.max(2, Math.round(big / 24));
    for (var size = big; size >= small; size -= step) {
      ctx.font = weight + ' ' + size + 'px ' + FONT;
      var lines = wrapLines(ctx, text, maxW);
      if (lines.length <= maxLines) return { size: size, lines: lines, weight: weight };
    }
    ctx.font = weight + ' ' + small + 'px ' + FONT;
    var l = wrapLines(ctx, text, maxW);
    if (l.length > maxLines) {
      l = l.slice(0, maxLines);
      l[maxLines - 1] = l[maxLines - 1].replace(/\s*\S*$/, '') + '\u2026';
    }
    return { size: small, lines: l, weight: weight };
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  // ---------- ảnh ----------
  function makeCanvas(w, h) {
    if (typeof document !== 'undefined' && document.createElement) {
      var c = document.createElement('canvas'); c.width = w; c.height = h; return c;
    }
    if (typeof OffscreenCanvas !== 'undefined') return new OffscreenCanvas(w, h);
    throw err('unsupported', 'No canvas');
  }

  // Thu nhỏ vào canvas riêng + kiểm tra "tainted": ảnh khác domain không cho CORS thì VideoFrame sẽ ném SecurityError
  // giữa chừng -> bỏ ảnh đó ngay từ đầu thay vì hỏng cả video.
  function normalizeImage(img) {
    var w = img.naturalWidth || img.videoWidth || img.width, h = img.naturalHeight || img.videoHeight || img.height;
    if (!w || !h) return null;
    var s = Math.min(1, MAX_IMG_SIDE / Math.max(w, h));
    var c = makeCanvas(Math.max(1, Math.round(w * s)), Math.max(1, Math.round(h * s)));
    var x = c.getContext('2d');
    x.imageSmoothingQuality = 'high';
    x.drawImage(img, 0, 0, c.width, c.height);
    try { x.getImageData(0, 0, 1, 1); } catch (e) { return null; }
    return c;
  }

  function loadOne(src) {
    return new Promise(function (resolve) {
      var revoke = null, timer = null;
      function done(v) {
        clearTimeout(timer);
        var out = null;
        try { out = v ? normalizeImage(v) : null; } catch (e) { out = null; }
        if (revoke) { try { URL.revokeObjectURL(revoke); } catch (e) { /* bỏ qua */ } }
        resolve(out);
      }
      try {
        if (!src) return resolve(null);
        if (typeof ImageBitmap !== 'undefined' && src instanceof ImageBitmap) return done(src);
        if (typeof HTMLCanvasElement !== 'undefined' && src instanceof HTMLCanvasElement) return done(src);
        if (typeof HTMLImageElement !== 'undefined' && src instanceof HTMLImageElement && src.complete && src.naturalWidth) return done(src);
        var url = src;
        if (typeof Blob !== 'undefined' && src instanceof Blob) { url = URL.createObjectURL(src); revoke = url; }
        if (typeof url !== 'string') return resolve(null);
        var img = new Image();
        img.decoding = 'async';
        // ảnh khác domain (vd ảnh sản phẩm dán link ngoài): xin CORS để canvas không bị "tainted"
        if (/^https?:/i.test(url) && typeof location !== 'undefined' && url.indexOf(location.origin + '/') !== 0) img.crossOrigin = 'anonymous';
        timer = setTimeout(function () { done(null); }, 20000);
        img.onload = function () { done(img); };
        img.onerror = function () { done(null); };
        img.src = url;
      } catch (e) { resolve(null); }
    });
  }

  function loadPhotos(list, onProgress, signal) {
    var items = (Array.isArray(list) ? list : []).slice(0, MAX_PHOTOS).map(function (p) {
      if (p && typeof p === 'object' && !(typeof Blob !== 'undefined' && p instanceof Blob) && ('src' in p || 'file' in p)) {
        return { src: p.file || p.src, label: String(p.label || p.name || '') };
      }
      return { src: p, label: (p && p.name) ? String(p.name) : '' };
    });
    var done = 0;
    return Promise.all(items.map(function (p) {
      return loadOne(p.src).then(function (img) {
        done += 1;
        onProgress({ phase: 'loading', progress: items.length ? done / items.length : 1 });
        return { img: img, label: p.label };
      });
    })).then(function (out) { checkAbort(signal); return out; });
  }

  function loadFonts() {
    if (typeof document === 'undefined' || !document.fonts || !document.fonts.load) return Promise.resolve();
    var want = Promise.all([document.fonts.load('800 64px Inter'), document.fonts.load('600 40px Inter')]).catch(function () {});
    return Promise.race([want, sleep(2500)]);
  }

  // ---------- dựng kế hoạch khung hình ----------
  function buildPlan(opts, photos) {
    var W = even(clamp(Number(opts.width) || 720, 240, 1920));
    var H = even(clamp(Number(opts.height) || 1280, 240, 1920));
    var fps = Math.round(clamp(Number(opts.fps) || 30, 10, 60));
    var u = Math.min(W, H) / 720;
    var brand = typeof opts.brand === 'string' ? { name: opts.brand } : (opts.brand || {});
    var accent = /^#[0-9a-f]{6}$/i.test(brand.accent || '') ? brand.accent : DEFAULT_ACCENT;
    var items = normalizeScenes(opts.scenes);
    if (!items.length) throw err('no_scenes', 'No scenes to render');
    assignPhotos(items, photos || []);
    items.forEach(function (it, i) {
      var zin = i % 2 === 0;   // xen kẽ zoom vào / lùi ra cho đỡ đơn điệu
      it.kb = {
        z0: zin ? 1.0 : 1.16, z1: zin ? 1.16 : 1.0,
        x0: (rand(i + 1) - 0.5) * 1.4, y0: (rand(i + 7) - 0.5) * 0.8,
        x1: (rand(i + 13) - 0.5) * 1.4, y1: (rand(i + 19) - 0.5) * 0.8,
      };
    });
    var name = String(brand.name || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    var cta = String(brand.cta || '').replace(/\s+/g, ' ').trim().slice(0, 90);
    var sub = String(brand.sub || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    var end = items[items.length - 1].end;
    if (name || cta) items.push({ kind: 'end', start: end, end: end + END_CARD, text: '', visual: 'text', img: null });

    // đo chữ 1 lần cho mỗi cảnh (đo lại mỗi khung hình sẽ chậm gấp nhiều lần)
    var mctx = makeCanvas(8, 8).getContext('2d');
    items.forEach(function (it) {
      if (it.kind === 'end') {
        it.fitName = name ? fitText(mctx, name, W - 120 * u, 2, Math.round(96 * u), Math.round(48 * u), 800) : null;
        it.fitCta = cta ? fitText(mctx, cta, W - 140 * u, 3, Math.round(44 * u), Math.round(30 * u), 600) : null;
        it.fitSub = sub ? fitText(mctx, sub, W - 140 * u, 2, Math.round(30 * u), Math.round(24 * u), 500) : null;
      } else if (it.text) {
        it.fit = it.img
          // chừa lề phải ~150 px cho cột nút like/share của TikTok/Reels
          ? fitText(mctx, it.text, W - 150 * u, 4, Math.round(68 * u), Math.round(40 * u), 800)
          : fitText(mctx, it.text, W - 112 * u, 6, Math.round(84 * u), Math.round(44 * u), 800);
      }
    });
    mctx.font = '700 ' + Math.round(30 * u) + 'px ' + FONT;
    var mark = name;
    while (mark && mctx.measureText(mark).width > W * 0.6) mark = mark.slice(0, -2);
    if (mark && mark !== name) mark = mark.replace(/\s+$/, '') + '\u2026';
    return {
      W: W, H: H, fps: fps, u: u, accent: accent, items: items, mark: mark,
      brand: { name: name, cta: cta, sub: sub },
      duration: items[items.length - 1].end,
      photosLoaded: (photos || []).filter(function (p) { return p && p.img; }).length,
      photosFailed: (photos || []).filter(function (p) { return p && !p.img; }).length,
    };
  }

  // ---------- vẽ 1 khung hình ----------
  function drawCover(ctx, img, W, H, zoom, fx, fy) {
    var iw = img.width, ih = img.height;
    var s = Math.max(W / iw, H / ih) * zoom;
    var dw = iw * s, dh = ih * s, ox = (dw - W) / 2, oy = (dh - H) / 2;
    ctx.drawImage(img, -ox + clamp(fx, -1, 1) * ox, -oy + clamp(fy, -1, 1) * oy, dw, dh);
  }

  function drawLines(ctx, fit, x, y, lh, align) {
    ctx.font = fit.weight + ' ' + fit.size + 'px ' + FONT;
    ctx.textAlign = align; ctx.textBaseline = 'top';
    fit.lines.forEach(function (ln, i) { ctx.fillText(ln, x, y + i * lh); });
  }

  function drawPhotoScene(ctx, P, it, t) {
    var span = it.end - it.start + FADE;
    var e = easeInOutSine((t - (it.start - FADE)) / span);   // chuyển động liền mạch cả lúc đang chồng mờ
    drawCover(ctx, it.img, P.W, P.H, lerp(it.kb.z0, it.kb.z1, e), lerp(it.kb.x0, it.kb.x1, e), lerp(it.kb.y0, it.kb.y1, e));
    // dải tối dưới đáy cho chữ trắng luôn đọc được dù ảnh sáng
    var g = ctx.createLinearGradient(0, P.H * 0.4, 0, P.H);
    g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(0.55, 'rgba(0,0,0,0.55)'); g.addColorStop(1, 'rgba(0,0,0,0.82)');
    ctx.fillStyle = g; ctx.fillRect(0, P.H * 0.4, P.W, P.H * 0.6);
    var top = ctx.createLinearGradient(0, 0, 0, P.H * 0.18);
    top.addColorStop(0, 'rgba(0,0,0,0.45)'); top.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = top; ctx.fillRect(0, 0, P.W, P.H * 0.18);
    if (!it.fit) return;
    var k = easeOutCubic((t - it.start) / 0.45);
    if (k <= 0) return;
    var u = P.u, lh = Math.round(it.fit.size * 1.16), blockH = it.fit.lines.length * lh;
    var x = 56 * u, y = P.H * 0.78 - blockH + (1 - k) * 28 * u;
    ctx.save();
    ctx.globalAlpha *= k;
    ctx.fillStyle = P.accent;
    roundRect(ctx, x, y - 26 * u, 64 * u, 8 * u, 4 * u); ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.shadowColor = 'rgba(0,0,0,0.6)'; ctx.shadowBlur = 14 * u; ctx.shadowOffsetY = 2 * u;
    drawLines(ctx, it.fit, x, y, lh, 'left');
    ctx.restore();
  }

  function drawTextScene(ctx, P, it, t) {
    var g = ctx.createLinearGradient(0, 0, P.W * 0.4, P.H);
    g.addColorStop(0, darken(P.accent, 0.62)); g.addColorStop(1, '#07070d');
    ctx.fillStyle = g; ctx.fillRect(0, 0, P.W, P.H);
    // quầng màu trôi chậm để cảnh chữ không đứng im
    var p = clamp((t - (it.start - FADE)) / (it.end - it.start + FADE), 0, 1);
    var cx = P.W * (0.25 + 0.5 * p), cy = P.H * (0.32 + 0.08 * Math.sin(p * Math.PI));
    var r = ctx.createRadialGradient(cx, cy, 0, cx, cy, P.W * 0.95);
    r.addColorStop(0, rgba(P.accent, 0.32)); r.addColorStop(1, rgba(P.accent, 0));
    ctx.fillStyle = r; ctx.fillRect(0, 0, P.W, P.H);
    if (!it.fit) return;
    var k = easeOutCubic((t - it.start) / 0.45);
    if (k <= 0) return;
    var u = P.u, lh = Math.round(it.fit.size * 1.14), blockH = it.fit.lines.length * lh;
    var y = P.H * 0.47 - blockH / 2 + (1 - k) * 24 * u;
    ctx.save();
    ctx.globalAlpha *= k;
    ctx.fillStyle = P.accent;
    roundRect(ctx, P.W / 2 - 36 * u, y - 34 * u, 72 * u, 8 * u, 4 * u); ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.shadowColor = 'rgba(0,0,0,0.45)'; ctx.shadowBlur = 12 * u; ctx.shadowOffsetY = 2 * u;
    drawLines(ctx, it.fit, P.W / 2, y, lh, 'center');
    ctx.restore();
  }

  function drawEndCard(ctx, P, it, t) {
    ctx.fillStyle = '#08080f'; ctx.fillRect(0, 0, P.W, P.H);
    var r = ctx.createRadialGradient(P.W / 2, P.H * 0.42, 0, P.W / 2, P.H * 0.42, P.W * 0.85);
    r.addColorStop(0, rgba(P.accent, 0.28)); r.addColorStop(1, rgba(P.accent, 0));
    ctx.fillStyle = r; ctx.fillRect(0, 0, P.W, P.H);
    var k = easeOutCubic((t - it.start) / 0.6), u = P.u;
    var nameH = it.fitName ? it.fitName.lines.length * Math.round(it.fitName.size * 1.1) : 0;
    var ctaH = it.fitCta ? it.fitCta.lines.length * Math.round(it.fitCta.size * 1.3) : 0;
    var subH = it.fitSub ? it.fitSub.lines.length * Math.round(it.fitSub.size * 1.3) : 0;
    var gap = 40 * u, total = nameH + (nameH && ctaH ? gap + 8 * u : 0) + ctaH + (subH ? 24 * u + subH : 0);
    var y = P.H * 0.46 - total / 2;
    ctx.save();
    ctx.globalAlpha *= k;
    ctx.translate(P.W / 2, P.H * 0.46); ctx.scale(0.96 + 0.04 * k, 0.96 + 0.04 * k); ctx.translate(-P.W / 2, -P.H * 0.46);
    if (it.fitName) {
      ctx.fillStyle = '#ffffff';
      drawLines(ctx, it.fitName, P.W / 2, y, Math.round(it.fitName.size * 1.1), 'center');
      y += nameH;
      if (ctaH) {
        ctx.fillStyle = P.accent;
        roundRect(ctx, P.W / 2 - 40 * u, y + gap / 2 - 4 * u, 80 * u, 8 * u, 4 * u); ctx.fill();
        y += gap + 8 * u;
      }
    }
    if (it.fitCta) {
      ctx.fillStyle = 'rgba(255,255,255,0.88)';
      drawLines(ctx, it.fitCta, P.W / 2, y, Math.round(it.fitCta.size * 1.3), 'center');
      y += ctaH;
    }
    if (it.fitSub) {
      ctx.fillStyle = 'rgba(255,255,255,0.62)';
      drawLines(ctx, it.fitSub, P.W / 2, y + 24 * u, Math.round(it.fitSub.size * 1.3), 'center');
    }
    ctx.restore();
  }

  function drawItem(ctx, P, i, t, alpha) {
    var it = P.items[i];
    if (!it || alpha <= 0) return;
    ctx.save();
    ctx.globalAlpha = alpha;
    if (it.kind === 'end') drawEndCard(ctx, P, it, t);
    else if (it.img) drawPhotoScene(ctx, P, it, t);
    else drawTextScene(ctx, P, it, t);
    ctx.restore();
  }

  function indexAt(P, t) {
    for (var i = 0; i < P.items.length; i++) if (t < P.items[i].end) return i;
    return P.items.length - 1;
  }

  function drawFrame(ctx, P, t) {
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#07070d'; ctx.fillRect(0, 0, P.W, P.H);
    ctx.imageSmoothingQuality = 'high';
    var i = indexAt(P, t), it = P.items[i], nx = P.items[i + 1], a = 0;
    drawItem(ctx, P, i, t, 1);
    if (nx && t > it.end - FADE) { a = easeInOutSine((t - (it.end - FADE)) / FADE); drawItem(ctx, P, i + 1, t, a); }
    // tên tiệm nhỏ góc trên (vẽ 1 lần trên cùng, mờ dần khi sang thẻ kết)
    var wm = it.kind === 'end' ? 0 : (nx && nx.kind === 'end' ? 1 - a : 1);
    if (P.mark && wm > 0) {
      ctx.save();
      ctx.globalAlpha = 0.92 * wm;
      ctx.font = '700 ' + Math.round(30 * P.u) + 'px ' + FONT;
      ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillStyle = '#ffffff';
      ctx.shadowColor = 'rgba(0,0,0,0.55)'; ctx.shadowBlur = 10 * P.u;
      ctx.fillText(P.mark, 48 * P.u, 64 * P.u);
      ctx.restore();
    }
  }

  // ---------- WebCodecs + mp4-muxer ----------
  var muxerPromise = null;
  function loadMuxer() {
    if (global.Mp4Muxer && global.Mp4Muxer.Muxer) return Promise.resolve(global.Mp4Muxer);
    if (muxerPromise) return muxerPromise;
    muxerPromise = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = MUXER_URL; s.async = true;
      var t = setTimeout(function () { reject(err('muxer_load', 'mp4-muxer did not load')); }, 20000);
      s.onload = function () {
        clearTimeout(t);
        if (global.Mp4Muxer && global.Mp4Muxer.Muxer) resolve(global.Mp4Muxer); else reject(err('muxer_load', 'mp4-muxer missing'));
      };
      s.onerror = function () { clearTimeout(t); reject(err('muxer_load', 'mp4-muxer did not load')); };
      document.head.appendChild(s);
    }).catch(function (e) { muxerPromise = null; throw e; });
    return muxerPromise;
  }

  function pickAvcConfig(w, h, fps, bitrate) {
    if (typeof VideoEncoder === 'undefined' || typeof VideoFrame === 'undefined' || !VideoEncoder.isConfigSupported) return Promise.resolve(null);
    var i = 0;
    function next() {
      if (i >= AVC_CODECS.length) return Promise.resolve(null);
      var cfg = { codec: AVC_CODECS[i++], width: w, height: h, bitrate: bitrate, framerate: fps, avc: { format: 'avc' } };
      return VideoEncoder.isConfigSupported(cfg).then(function (s) {
        return (s && s.supported) ? (s.config || cfg) : next();
      }, next);
    }
    return next();
  }

  // Nhường luồng cho giao diện cập nhật thanh tiến độ — MessageChannel không bị trình duyệt bóp 1 s như setTimeout ở tab ẩn
  var mc = null, mcQueue = [];
  function yieldToUI() {
    return new Promise(function (r) {
      if (typeof MessageChannel === 'undefined') return setTimeout(r, 0);
      if (!mc) { mc = new MessageChannel(); mc.port1.onmessage = function () { var f = mcQueue.shift(); if (f) f(); }; }
      mcQueue.push(r); mc.port2.postMessage(0);
    });
  }

  function drain(enc) {
    return new Promise(function (resolve) {
      var fired = false;
      function fin() { if (fired) return; fired = true; try { enc.removeEventListener('dequeue', fin); } catch (e) { /* trình duyệt cũ */ } resolve(); }
      try { enc.addEventListener('dequeue', fin); } catch (e) { /* trình duyệt cũ */ }
      setTimeout(fin, 30);
    }).then(function () { if (enc.state === 'configured' && enc.encodeQueueSize > 6) return drain(enc); });
  }

  function encodeMp4(P, cfg, M, onProgress, signal) {
    var target = new M.ArrayBufferTarget();
    var muxer = new M.Muxer({ target: target, video: { codec: 'avc', width: P.W, height: P.H, frameRate: P.fps }, fastStart: 'in-memory' });
    var failure = null;
    var enc = new VideoEncoder({
      output: function (chunk, meta) { try { muxer.addVideoChunk(chunk, meta); } catch (e) { failure = e; } },
      error: function (e) { failure = e; },
    });
    enc.configure(cfg);
    var cv = makeCanvas(P.W, P.H), ctx = cv.getContext('2d', { alpha: false });
    var total = Math.max(1, Math.round(P.duration * P.fps)), us = 1e6 / P.fps, gop = P.fps * 2, i = 0;

    function step() {
      // vẽ + mã hoá vài khung rồi nhường giao diện
      for (var n = 0; n < 6 && i < total; n++, i++) {
        if (failure) throw failure;
        checkAbort(signal);
        drawFrame(ctx, P, i / P.fps);
        var frame = new VideoFrame(cv, { timestamp: Math.round(i * us), duration: Math.round(us) });
        try { enc.encode(frame, { keyFrame: i % gop === 0 }); } finally { frame.close(); }
      }
      onProgress({ phase: 'encoding', progress: i / total, frame: i, frames: total, format: 'mp4' });
      if (i >= total) return Promise.resolve();
      var wait = enc.encodeQueueSize > 6 ? drain(enc) : Promise.resolve();
      return wait.then(yieldToUI).then(step);
    }

    // Promise.resolve().then(step): lỗi ngay ở lô khung đầu cũng thành promise bị reject -> encoder vẫn được đóng
    return Promise.resolve().then(step).then(function () { return enc.flush(); }).then(function () {
      if (failure) throw failure;
      try { enc.close(); } catch (e) { /* đã đóng */ }
      onProgress({ phase: 'finishing', progress: 1, format: 'mp4' });
      muxer.finalize();
      return new Blob([target.buffer], { type: 'video/mp4' });
    }, function (e) {
      try { if (enc.state !== 'closed') enc.close(); } catch (x) { /* đã đóng */ }
      throw e;
    });
  }

  // ---------- dự phòng: MediaRecorder (quay theo thời gian thật) ----------
  function recorderMime() {
    if (typeof MediaRecorder === 'undefined') return null;
    var list = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4;codecs=avc1', 'video/mp4'];
    for (var i = 0; i < list.length; i++) {
      try { if (!MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(list[i])) return list[i]; } catch (e) { /* thử loại khác */ }
    }
    return '';
  }

  function recorderSupported() {
    if (typeof MediaRecorder === 'undefined' || typeof document === 'undefined') return false;
    var c = document.createElement('canvas');
    return typeof c.captureStream === 'function';
  }

  function recordWithMediaRecorder(P, bitrate, onProgress, signal) {
    return new Promise(function (resolve, reject) {
      var cv = makeCanvas(P.W, P.H), ctx = cv.getContext('2d');
      drawFrame(ctx, P, 0);
      var stream, rec, mime = recorderMime();
      try {
        stream = cv.captureStream(P.fps);
        rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: bitrate } : { videoBitsPerSecond: bitrate });
      } catch (e) { reject(err('unsupported', 'MediaRecorder unavailable')); return; }
      var chunks = [], failed = null, stopped = false, t0 = 0;
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onerror = function (e) { failed = (e && e.error) || err('encoder_error', 'Recording failed'); stop(); };
      rec.onstop = function () {
        try { stream.getTracks().forEach(function (tr) { tr.stop(); }); } catch (e) { /* đã dừng */ }
        if (failed) return reject(failed);
        var type = String(rec.mimeType || mime || 'video/webm').split(';')[0];
        resolve(new Blob(chunks, { type: type }));
      };
      function stop() { if (stopped) return; stopped = true; try { if (rec.state !== 'inactive') rec.stop(); } catch (e) { reject(e); } }
      function schedule() {
        // tab ẩn thì requestAnimationFrame dừng hẳn -> dùng setTimeout (bị bóp chậm nhưng không đứng hình)
        if (typeof document !== 'undefined' && document.hidden) setTimeout(tick, 1000 / P.fps);
        else requestAnimationFrame(tick);
      }
      function tick() {
        if (stopped) return;
        if (signal && signal.aborted) { failed = err('aborted', 'Cancelled'); stop(); return; }
        var t = (performance.now() - t0) / 1000;
        if (t >= P.duration) {
          drawFrame(ctx, P, P.duration - 0.001);
          onProgress({ phase: 'finishing', progress: 1, format: 'webm' });
          setTimeout(stop, 150);   // giữ khung cuối 1 nhịp cho bộ ghi kịp lấy
          return;
        }
        drawFrame(ctx, P, t);
        onProgress({ phase: 'recording', progress: t / P.duration, format: (mime || '').indexOf('mp4') >= 0 ? 'mp4' : 'webm' });
        schedule();
      }
      rec.start(500);
      t0 = performance.now();
      schedule();
    });
  }

  // ---------- API công khai ----------
  function supports() {
    return {
      webcodecs: typeof VideoEncoder !== 'undefined' && typeof VideoFrame !== 'undefined',
      recorder: recorderSupported(),
    };
  }

  function canMakeMp4(w, h, fps, bitrate) {
    return pickAvcConfig(even(w || 720), even(h || 1280), fps || 30, bitrate || 2000000).then(function (c) { return !!c; });
  }

  var api = {
    lastInfo: null,
    supports: supports,
    canMakeMp4: canMakeMp4,
    planDuration: planDuration,
    render: function (opts) {
      opts = opts || {};
      var onProgress = typeof opts.onProgress === 'function' ? function (p) { try { opts.onProgress(p); } catch (e) { /* lỗi giao diện không được làm hỏng video */ } } : function () {};
      var signal = opts.signal;
      var bitrate = Math.round(clamp(Number(opts.bitrate) || 2000000, 300000, 8000000));
      var P = null, codec = null;
      onProgress({ phase: 'loading', progress: 0 });
      return loadFonts()
        .then(function () { checkAbort(signal); return loadPhotos(opts.photos, onProgress, signal); })
        .then(function (photos) {
          P = buildPlan(opts, photos);
          return opts.forceFallback ? null : pickAvcConfig(P.W, P.H, P.fps, bitrate);
        })
        .then(function (cfg) {
          if (!cfg) return null;
          codec = cfg.codec;
          return loadMuxer().then(function (M) { return encodeMp4(P, cfg, M, onProgress, signal); })
            .catch(function (e) {
              if (e && e.code === 'aborted') throw e;
              // CDN bị chặn / bộ mã hoá lỗi giữa chừng -> vẫn còn đường MediaRecorder
              if (global.console) console.warn('[promo_video] MP4 path failed, falling back:', e);
              codec = null;
              return null;
            });
        })
        .then(function (blob) {
          if (blob) return blob;
          if (!recorderSupported()) throw err('unsupported', 'This browser cannot make videos');
          codec = 'mediarecorder';
          return recordWithMediaRecorder(P, bitrate, onProgress, signal);
        })
        .then(function (blob) {
          api.lastInfo = {
            duration: P.duration, width: P.W, height: P.H, fps: P.fps, codec: codec, type: blob.type, size: blob.size,
            scenes: P.items.filter(function (x) { return x.kind === 'scene'; }).length,
            photosLoaded: P.photosLoaded, photosFailed: P.photosFailed,
          };
          onProgress({ phase: 'done', progress: 1, format: /mp4/.test(blob.type) ? 'mp4' : 'webm' });
          return blob;
        });
    },
    // cho test offline (node) — không phải API ổn định
    _internal: {
      normalizeScenes: normalizeScenes, assignPhotos: assignPhotos, wrapLines: wrapLines, fitText: fitText,
      buildPlan: buildPlan, drawFrame: drawFrame, indexAt: indexAt, planDuration: planDuration,
      AVC_CODECS: AVC_CODECS, MUXER_URL: MUXER_URL, END_CARD: END_CARD, FADE: FADE,
    },
  };

  global.BitPawPromoVideo = api;
})(typeof window !== 'undefined' ? window : globalThis);
