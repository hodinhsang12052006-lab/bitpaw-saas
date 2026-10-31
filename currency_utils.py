"""Multi-region currency formatting.

BitPaw OS stores each tenant's amounts natively in that tenant's own currency —
VN tenants in VND, US tenants in USD — there is never an FX conversion applied
anywhere in the app. This module only controls how a stored number is *rendered*,
and which currency a shop uses when it has none stored (shop_currency).
"""
import math
import re

# Currencies BitPaw formats with their own symbol — the ones an owner can pick in Brand settings -> Country & currency
# (app._REGION_CURRENCIES). Any other 3-letter code is printed with its code ('1,200.50 EUR'), never as VND.
SUPPORTED_CURRENCIES = ('USD', 'AUD', 'VND', 'CAD', 'NZD', 'GBP')
# Shop country (ai_packs.SHOP_COUNTRIES) -> its currency.
COUNTRY_CURRENCY = {'US': 'USD', 'AU': 'AUD', 'VN': 'VND', 'CA': 'CAD', 'NZ': 'NZD', 'GB': 'GBP'}
_PREFIX = {'USD': '$', 'AUD': '$', 'CAD': 'CA$', 'NZD': 'NZ$', 'GBP': '£'}
_CODE_RE = re.compile(r'[A-Z]{3}')


def shop_currency(stored=None, country=None):
    """The currency of a shop: its stored businesses.currency (any 3-letter code), else the currency of its country
    (ai_packs.shop_country: US -> USD, AU -> AUD, VN -> VND, CA -> CAD, NZ -> NZD, GB -> GBP), else USD.
    Never a silent VND: a shop with no currency and no known country ('OTHER', 'SG', nothing) is USD."""
    cur = str(stored or '').strip().upper()
    if _CODE_RE.fullmatch(cur):
        return cur
    c = str(country or '').strip().upper()
    return COUNTRY_CURRENCY.get({'UK': 'GB'}.get(c, c), 'USD')


def format_money(amount, currency=None):
    """Format a raw numeric amount in the tenant's currency.

    VND: '1.200.000đ' (period thousands separator, đ suffix, no decimals — VND
    has no minor unit in everyday display).
    USD/AUD: '$1,200.50'; CAD: 'CA$1,200.50'; NZD: 'NZ$1,200.50'; GBP: '£1,200.50' (comma thousands separator,
    2 decimals, minus sign before the symbol: '-$12.00').
    Any other 3-letter code: '1,200.50 EUR'. No / unreadable currency: USD. 'đ' is only ever used for VND.
    """
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value):
        value = 0.0
    cur = str(currency or '').strip().upper()

    if cur == 'VND':
        return f"{int(round(value)):,}".replace(',', '.') + 'đ'
    if cur not in _PREFIX and _CODE_RE.fullmatch(cur):
        return f"{value:,.2f} {cur}"
    sign = '-' if value < 0 and round(abs(value), 2) > 0 else ''
    return f"{sign}{_PREFIX.get(cur, '$')}{abs(value):,.2f}"
