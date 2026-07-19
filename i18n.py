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
    lang = request.cookies.get(LANG_COOKIE_NAME)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
