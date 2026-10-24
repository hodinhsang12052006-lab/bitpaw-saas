/* bp-currency.js (Pha 28) — tiệm Mỹ/Úc (USD/AUD) vẫn thấy nhãn tiền Việt ở vài trang cũ: "Amount (VND)", "Budget (VNĐ)",
   "VND/Month", ô nhập có chữ "₫" bên cạnh. app.py::_inject_pwa_head chỉ nạp file này khi tiền tệ của tiệm KHÁC VND
   (window.BP_CURRENCY), nên tiệm Việt Nam không bị đụng tới. Chỉ đổi NHÃN đơn vị; số tiền do từng trang tự định dạng.
   Có thêm window.bpMoney(v) cho trang cần định dạng số theo tiền tệ của tiệm. */
(function () {
  var CUR = String(window.BP_CURRENCY || '').toUpperCase();
  if (!CUR || CUR === 'VND') return;
  var SYM = '$';
  window.bpMoney = function (v) {
    var n = Number(v) || 0;
    return (n < 0 ? '-' : '') + SYM + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var RULES = [
    [/\((?:VND|VNĐ|vnđ|vnd)\)/g, '(' + CUR + ')'],
    [/\((?:₫|đ)\)/g, '(' + SYM + ')'],
    [/\b(?:VND|VNĐ)\s*\/\s*/g, CUR + '/'],
  ];
  var LONE = /^\s*(₫|đ|VND|VNĐ)\s*$/;
  function fixText(s) {
    if (!s || !/VND|VNĐ|vnd|vnđ|₫|đ/.test(s)) return s;
    if (LONE.test(s)) return s.replace(/₫|đ/, SYM).replace(/VNĐ|VND/, CUR);
    for (var i = 0; i < RULES.length; i++) s = s.replace(RULES[i][0], RULES[i][1]);
    return s;
  }
  function walk(root) {
    if (!root) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) { var p = n.parentNode && n.parentNode.nodeName; return (p === 'SCRIPT' || p === 'STYLE' || p === 'TEXTAREA') ? 2 : 1; }
    });
    var n, t;
    while ((n = w.nextNode())) { t = fixText(n.nodeValue); if (t !== n.nodeValue) n.nodeValue = t; }
    var els = root.querySelectorAll ? root.querySelectorAll('[placeholder]') : [];
    for (var i = 0; i < els.length; i++) { t = fixText(els[i].getAttribute('placeholder')); if (t !== els[i].getAttribute('placeholder')) els[i].setAttribute('placeholder', t); }
  }
  var pending = false;
  function schedule() { if (pending) return; pending = true; setTimeout(function () { pending = false; walk(document.body); }, 120); }
  function start() {
    walk(document.body);
    // trang đổi ngôn ngữ / vẽ lại bảng bằng JS -> sửa lại nhãn (gom nhiều thay đổi thành 1 lần)
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
