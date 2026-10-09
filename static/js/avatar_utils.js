// Ham fallback avatar dung chung cho TOAN BO user (nhan vien, chu tiem, khach hang) khi chua
// co avatar that (avatar_url rong/null) - luon dung ui-avatars.com sinh anh theo ten, thay vi
// anh tinh cuc bo (de bi thieu file -> vo anh) hoac moi noi tu ve 1 kieu fallback rieng (chu
// cai dau ten, gradient...) gay khong dong nhat giao dien toan he thong.
function bpAvatarUrl(name) {
    var safeName = (name || '?').toString().trim() || '?';
    return 'https://ui-avatars.com/api/?name=' + encodeURIComponent(safeName) +
        '&background=0D8ABC&color=fff&bold=true';
}

function bpEscAttr(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

// Chi chap nhan URL http(s), duong dan tuong doi, hoac data:image/* — chan javascript:, data:text/html...
function bpSafeImgSrc(url) {
    var u = (url == null ? '' : String(url)).trim();
    if (!u) return '';
    if (/^https?:\/\//i.test(u) || /^data:image\//i.test(u)) return u;
    if (/^\/\//.test(u)) return u; // protocol-relative
    if (/^[a-z][a-z0-9+.\-]*:/i.test(u)) return ''; // scheme khac (javascript:, data:text...) -> bo
    return u; // duong dan tuong doi
}

function bpAvatarImg(name, avatarUrl, extraClass) {
    var safeName = (name || '?').toString().trim() || '?';
    var src = bpSafeImgSrc(avatarUrl) || bpAvatarUrl(safeName);
    var cls = 'w-full h-full object-cover' + (extraClass ? (' ' + extraClass) : '');
    var jsName = safeName.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, ' ');
    return '<img src="' + bpEscAttr(src) + '" class="' + bpEscAttr(cls) + '" alt="' + bpEscAttr(safeName) + '" ' +
        'onerror="this.onerror=null;this.src=bpAvatarUrl(\'' + bpEscAttr(jsName) + '\');">';
}
