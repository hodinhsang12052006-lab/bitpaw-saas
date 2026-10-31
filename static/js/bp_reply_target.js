/* Trả lời của nhân viên trên hội thoại WEB — dùng chung cho ai_bot.html, crm_automation.html, super_admin.html.
 *
 * Hội thoại web khoá theo SĐT khách TỰ GÕ: 2 trình duyệt gõ cùng 1 số dùng chung 1 hội thoại (người gõ nhầm / cố ý gõ SĐT của
 * người khác, hay chính khách đổi máy). Mỗi tin khách mang mã băm mã chat của trình duyệt đã gửi (chat_token_hash); trang công
 * khai (/portal, widget) chỉ hiện trả lời của nhân viên cho ĐÚNG trình duyệt có mã băm của trả lời đó (server ghi mã băm của tin
 * được trả lời — app.py::_web_reply_stamp).
 *   - Nhãn ngắn "Thiết bị A / B" theo thứ tự trình duyệt nhắn lần đầu — cùng luật với app.py::_web_device_labels. KHÔNG BAO GIỜ
 *     hiện mã băm.
 *   - Đích trả lời (reply_to = created_at của tin khách): hội thoại chỉ có 1 thiết bị -> tin khách MỚI NHẤT đang hiện trên màn
 *     hình lúc bấm Gửi.
 *   - Từ 2 thiết bị trở lên ở BẤT KỲ đâu trong hội thoại (plan().mustPick — không chỉ nhắn từ sau trả lời gần nhất của nhân
 *     viên): KHÔNG có mặc định, phải chọn thiết bị trước MỖI lần gửi (trang xoá lựa chọn sau mỗi lần gửi). Người gõ SĐT của
 *     người khác có tin mới nhất, hay nhắn 1 tin ngay sau mỗi trả lời của nhân viên (trang tải lại im lặng qua SSE), thì trả
 *     lời tiếp theo vẫn không âm thầm tới trình duyệt đó. Ô chọn liệt kê MỌI thiết bị của hội thoại (tin mới nhất của từng
 *     thiết bị). Gửi bị chặn (needsPick) tới khi nhân viên tự chọn; server cũng từ chối trả lời không có reply_to trên hội
 *     thoại như vậy (409, code 'reply_target_required' — app.py::_web_reply_stamp), trang báo rõ + tải lại hội thoại để hiện
 *     thanh chọn.
 *   - Tin khách không có mã trình duyệt (cửa sổ chat cũ): trả lời cho tin đó không hiện được trên trang chat -> nói rõ cho nhân
 *     viên (gọi / nhắn SMS cho khách) thay vì im lặng như đã gửi.
 */
(function (root) {
    "use strict";

    var TEXT = {
        vi: {
            device: "Thiết bị {d}",
            noDevice: "Không rõ thiết bị",
            noDeviceHint: "Tin này gửi từ cửa sổ chat cũ (không có mã trình duyệt) — trả lời cho tin này không hiện được trên trang chat của khách.",
            to: "→ {who}",
            notOnWeb: "không hiện trên trang chat của khách",
            pickSince: "{n} thiết bị khác nhau đã nhắn bằng số này kể từ lần trả lời trước — trả lời chỉ tới:",
            pickAll: "{n} thiết bị khác nhau đã nhắn bằng số này — trả lời chỉ tới:",
            pickAria: "Chọn thiết bị nhận trả lời",
            pickPlaceholder: "— Chọn thiết bị —",
            mustPick: "Chọn thiết bị nhận trả lời trước khi gửi — trả lời không tự gửi cho tin mới nhất khi nhiều thiết bị cùng nhắn.",
            noDeviceWarn: "Tin mới nhất của khách gửi từ cửa sổ chat cũ (không có mã trình duyệt): trả lời được lưu ở đây nhưng KHÔNG hiện được trên trang chat của khách — hãy gọi hoặc nhắn SMS cho khách.",
            pickedNoDevice: "Tin này gửi từ cửa sổ chat cũ (không có mã trình duyệt): trả lời được lưu ở đây nhưng KHÔNG hiện được trên trang chat của khách — hãy gọi hoặc nhắn SMS cho khách.",
            sentTo: "Đã gửi tới {who} — chỉ thiết bị này thấy trả lời trên trang chat.",
            notShown: "Đã lưu trả lời, nhưng trả lời KHÔNG hiện trên trang chat của khách (tin của khách không có mã trình duyệt) — hãy gọi hoặc nhắn SMS cho khách."
        },
        en: {
            device: "Device {d}",
            noDevice: "Unknown device",
            noDeviceHint: "Sent from an older chat window (no browser ID) — replies to it can't appear on the customer's chat page.",
            to: "→ {who}",
            notOnWeb: "not shown on the customer's chat page",
            pickSince: "{n} different devices have messaged from this number since your last reply — your reply goes only to:",
            pickAll: "{n} different devices have messaged from this number — your reply goes only to:",
            pickAria: "Choose the device that gets this reply",
            pickPlaceholder: "— Choose a device —",
            mustPick: "Choose which device gets this reply before sending — it isn't sent to the newest message by default when several devices are messaging.",
            noDeviceWarn: "The customer's latest message came from an older chat window (no browser ID): your reply is saved here but will NOT appear on their chat page — call or text them instead.",
            pickedNoDevice: "That message came from an older chat window (no browser ID): your reply is saved here but will NOT appear on the customer's chat page — call or text them instead.",
            sentTo: "Sent to {who} — only that device sees the reply on the chat page.",
            notShown: "Reply saved, but it will NOT appear on the customer's chat page (their message has no browser ID) — call or text them instead."
        }
    };

    function tr(lang, key) { return TEXT[lang === "vi" ? "vi" : "en"][key]; }
    function letter(i) { return i < 26 ? String.fromCharCode(65 + i) : String(i + 1); }
    function hashOf(m) { var h = m && m.chat_token_hash; return typeof h === "string" ? h : null; }
    var PICK = "__pick__";   // giá trị của dòng nhắc "Chọn thiết bị" trong ô chọn (không phải thiết bị nào)

    // { mã băm -> 'A' | 'B' | ... } theo thứ tự tin khách đầu tiên của mỗi trình duyệt (tin đã xếp theo created_at tăng dần)
    function deviceMap(msgs) {
        var map = new Map();
        (Array.isArray(msgs) ? msgs : []).forEach(function (m) {
            var h = hashOf(m);
            if (m && m.sender_type === "customer" && h && !map.has(h)) map.set(h, letter(map.size));
        });
        return map;
    }

    function deviceName(device, lang) { return device ? tr(lang, "device").replace("{d}", device) : tr(lang, "noDevice"); }

    // Kế hoạch trả lời cho hội thoại đang hiện. isWeb=false (Messenger / SMS / WhatsApp...): không có thiết bị, không gửi reply_to.
    function plan(msgs, isWeb) {
        var rows = Array.isArray(msgs) ? msgs : [];
        var out = { web: !!isWeb, map: isWeb ? deviceMap(rows) : new Map(), latest: null, choices: [], choose: false, sinceCount: 0,
                    mustPick: false };
        if (!isWeb) return out;
        var lastStaff = -1;
        rows.forEach(function (m, i) { if (m && m.sender_type === "staff") lastStaff = i; });
        var since = new Map(), all = new Map();
        rows.forEach(function (m, i) {
            if (!m || m.sender_type !== "customer" || typeof m.created_at !== "string" || !m.created_at) return;
            var h = hashOf(m);
            var t = { device: h ? (out.map.get(h) || "") : "", reply_to: m.created_at,
                      preview: String(m.content || "").replace(/\s+/g, " ").trim().slice(0, 48) };
            out.latest = t;
            all.set(t.device, t);
            if (i > lastStaff) since.set(t.device, t);
        });
        var order = Array.from(out.map.values()).concat([""]);
        var pick = function (src) { return order.filter(function (d) { return src.has(d); }).map(function (d) { return src.get(d); }); };
        out.sinceCount = since.size;
        // MỌI thiết bị của hội thoại (tin mới nhất của từng thiết bị): 2 trình duyệt nhắn ngay sau trả lời gần nhất không đẩy được
        // thiết bị đã nhắn trước đó ra khỏi ô chọn
        out.choices = all.size >= 2 ? pick(all) : [];
        out.choose = out.choices.length >= 2;
        out.mustPick = all.size >= 2;   // >= 2 thiết bị trong CẢ hội thoại: không mặc định, chọn trước mỗi lần gửi (cùng luật server)
        return out;
    }

    // Đích khi bấm Gửi: thiết bị nhân viên đã chọn (nếu vẫn còn trong danh sách) hoặc tin khách mới nhất đang hiện — trừ khi
    // mustPick (>= 2 thiết bị ở bất kỳ đâu trong hội thoại): chưa chọn = null, không bao giờ âm thầm lấy tin mới nhất.
    function target(p, picked) {
        if (!p || !p.web || !p.latest) return null;
        if (p.choose && typeof picked === "string") {
            for (var i = 0; i < p.choices.length; i++) if (p.choices[i].device === picked) return p.choices[i];
        }
        return p.mustPick ? null : p.latest;
    }

    // true = phải chọn thiết bị trước khi gửi (trang chặn nút Gửi, giữ nguyên chữ đang soạn)
    function needsPick(p, picked) { return !!(p && p.web && p.latest && p.mustPick && !target(p, picked)); }

    // Nhãn của 1 tin khách: { text, title } | null (không phải hội thoại web / không phải tin khách)
    function customerTag(m, p, lang) {
        if (!p || !p.web || !m || m.sender_type !== "customer") return null;
        var h = hashOf(m), d = h ? p.map.get(h) : "";
        return d ? { text: deviceName(d, lang), title: "" } : { text: tr(lang, "noDevice"), title: tr(lang, "noDeviceHint") };
    }

    // Nhãn của 1 trả lời nhân viên: "→ Thiết bị A" / "→ không hiện trên trang chat của khách" / "" (trả lời cũ, không rõ)
    function staffTag(m, p, lang) {
        if (!p || !p.web || !m || m.sender_type !== "staff") return "";
        var h = hashOf(m);
        if (h === null) return "";
        if (!h) return tr(lang, "to").replace("{who}", tr(lang, "notOnWeb"));
        var d = p.map.get(h);
        return d ? tr(lang, "to").replace("{who}", deviceName(d, lang)) : "";
    }

    // Nhãn tạm cho trả lời vừa bấm Gửi (trước khi tải lại hội thoại): đích target() đã chọn
    function targetTag(t, lang) {
        if (!t) return "";
        return tr(lang, "to").replace("{who}", t.device ? deviceName(t.device, lang) : tr(lang, "notOnWeb"));
    }

    // Thanh phía trên ô soạn tin: chọn thiết bị (>= 2 thiết bị) / cảnh báo tin không có mã trình duyệt. Dựng bằng DOM + textContent.
    function renderBar(bar, p, picked, lang, onPick, selectClass) {
        if (!bar) return;
        while (bar.firstChild) bar.removeChild(bar.firstChild);
        var t = target(p, picked), wait = needsPick(p, picked);
        var show = wait || !!(t && (p.choose || t.device === ""));
        bar.classList.toggle("hidden", !show);
        if (!show) { bar.removeAttribute("data-reply-target"); return; }
        bar.setAttribute("data-reply-target", wait ? "pick" : (t.device || "none"));
        var doc = bar.ownerDocument || document;
        var label = doc.createElement("span");
        if (p.choose) {
            var fromSince = p.sinceCount >= 2;   // "... kể từ lần trả lời trước" đếm đúng số thiết bị đã nhắn từ lúc đó
            label.textContent = tr(lang, fromSince ? "pickSince" : "pickAll")
                .replace("{n}", String(fromSince ? p.sinceCount : p.choices.length));
            bar.appendChild(label);
            var sel = doc.createElement("select");
            sel.setAttribute("aria-label", tr(lang, "pickAria"));
            sel.setAttribute("data-reply-target-select", "1");
            if (selectClass) sel.className = selectClass;
            if (wait) {   // chưa chọn: ô chọn đứng ở dòng nhắc, không đứng sẵn ở thiết bị nào
                var ph = doc.createElement("option");
                ph.value = PICK;
                ph.textContent = tr(lang, "pickPlaceholder");
                ph.disabled = true;
                ph.selected = true;
                sel.appendChild(ph);
            }
            p.choices.forEach(function (c) {
                var o = doc.createElement("option");
                o.value = c.device;
                o.textContent = deviceName(c.device, lang) + (c.preview ? " — “" + c.preview + "”" : "");
                if (t && c.device === t.device) o.selected = true;
                sel.appendChild(o);
            });
            sel.addEventListener("change", function () { if (onPick && sel.value !== PICK) onPick(sel.value); });
            bar.appendChild(sel);
            if (wait) {
                var need = doc.createElement("span");
                need.textContent = tr(lang, "mustPick");
                bar.appendChild(need);
            } else if (t.device === "") {
                var warn = doc.createElement("span");
                warn.textContent = tr(lang, "pickedNoDevice");
                bar.appendChild(warn);
            }
        } else {
            label.textContent = tr(lang, "noDeviceWarn");
            bar.appendChild(label);
        }
    }

    // Câu báo sau khi gửi (server trả device / reply_to): { ok, text } | null
    function sentNote(res, p, lang) {
        if (!p || !p.web || !res || !Object.prototype.hasOwnProperty.call(res, "device")) return null;
        if (!res.device) return { ok: false, text: tr(lang, "notShown") };
        if (p.map.size >= 2) return { ok: true, text: tr(lang, "sentTo").replace("{who}", deviceName(res.device, lang)) };
        return null;
    }

    root.BPReplyTarget = { letter: letter, deviceMap: deviceMap, deviceName: deviceName, plan: plan, target: target, needsPick: needsPick,
                           customerTag: customerTag, staffTag: staffTag, targetTag: targetTag, renderBar: renderBar, sentNote: sentNote, text: tr };
})(typeof window !== "undefined" ? window : globalThis);
