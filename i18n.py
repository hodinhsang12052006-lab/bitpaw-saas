import json
import os

_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'translations')
SUPPORTED_LANGS = ('en', 'vi')
DEFAULT_LANG = 'en'
LANG_COOKIE_NAME = 'bitpaw_lang'

_cache = {}


def get_translations(lang):
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    if lang not in _cache:
        path = os.path.join(_BASE_DIR, f'{lang}.json')
        with open(path, encoding='utf-8') as f:
            _cache[lang] = json.load(f)
    return _cache[lang]


def resolve_lang(request):
    """Uu tien 1: cookie bitpaw_lang (nguoi dung da tu chon truoc do, vd bam nut doi ngon
    ngu). Uu tien 2: header Accept-Language trinh duyet gui (chi dung cho khach lan dau,
    chua tung co cookie). Uu tien 3: DEFAULT_LANG. Truoc day ham nay CHUA doc Accept-Language
    o buoc nao ca -- neu Safari/iPhone bi ep hien sai ngon ngu thi nguyen nhan that su la
    the <html lang="vi"> hardcode cung trong moi template (xem template <html lang> fix),
    khong phai do server doc nham header nay."""
    cookie_lang = request.cookies.get(LANG_COOKIE_NAME)
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang
    best_match = request.accept_languages.best_match(SUPPORTED_LANGS)
    if best_match:
        return best_match
    return DEFAULT_LANG
