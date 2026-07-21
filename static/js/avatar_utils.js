// Ham fallback avatar dung chung cho TOAN BO user (nhan vien, chu tiem, khach hang) khi chua
// co avatar that (avatar_url rong/null) - luon dung ui-avatars.com sinh anh theo ten, thay vi
// anh tinh cuc bo (de bi thieu file -> vo anh) hoac moi noi tu ve 1 kieu fallback rieng (chu
// cai dau ten, gradient...) gay khong dong nhat giao dien toan he thong.
function bpAvatarUrl(name) {
    var safeName = (name || '?').toString().trim() || '?';
    return 'https://ui-avatars.com/api/?name=' + encodeURIComponent(safeName) +
        '&background=0D8ABC&color=fff&bold=true';
}

function bpAvatarImg(name, avatarUrl, extraClass) {
    var safeName = (name || '?').toString().trim() || '?';
    var src = avatarUrl || bpAvatarUrl(safeName);
    var cls = 'w-full h-full object-cover' + (extraClass ? (' ' + extraClass) : '');
    var altText = safeName.replace(/"/g, '');
    return '<img src="' + src + '" class="' + cls + '" alt="' + altText + '" ' +
        'onerror="this.onerror=null;this.src=bpAvatarUrl(\'' + altText.replace(/'/g, "\\'") + '\');">';
}
