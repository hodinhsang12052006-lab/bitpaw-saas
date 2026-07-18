"""Multi-region currency formatting.

BitPaw OS stores each tenant's amounts natively in that tenant's own currency —
VN tenants in VND, US tenants in USD — there is never an FX conversion applied
anywhere in the app. This module only controls how a stored number is *rendered*.
"""

def format_money(amount, currency='VND'):
    """Format a raw numeric amount according to the tenant's currency.

    VND: '1.200.000đ' (period thousands separator, đ suffix, no decimals — VND
    has no minor unit in everyday display).
    USD: '$1,200.50' (comma thousands separator, 2 decimals, $ prefix).
    """
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0

    if (currency or 'VND').upper() == 'USD':
        return f"${value:,.2f}"

    # VND
    return f"{int(round(value)):,}".replace(',', '.') + 'đ'
