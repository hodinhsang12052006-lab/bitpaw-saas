"""US market payment engine — Square Sandbox integration.

Handles the USD payment flow for US tenants only (country == 'US'). Completely
separate from the existing VN payment flow (app.py /api/payment/start and
/api/payment/confirm) — no shared code path, no currency conversion between the
two markets. Real Square production credentials don't exist yet, so this module
targets the Square Sandbox environment by default and degrades to a clear,
non-crashing "not configured" response when credentials are missing — mirroring
the DummySupabaseClient / DEEPSEEK_API_KEY fallback pattern used elsewhere in
this codebase.

Square Sandbox docs: https://developer.squareup.com/docs/devtools/sandbox/payments
"""
import os
import uuid
import requests

SQUARE_ENV = os.environ.get('SQUARE_ENV', 'sandbox')
SQUARE_ACCESS_TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN')
SQUARE_LOCATION_ID = os.environ.get('SQUARE_LOCATION_ID')
SQUARE_DEVICE_ID = os.environ.get('SQUARE_DEVICE_ID')  # optional: physical Square Terminal device

SQUARE_API_BASE = (
    'https://connect.squareupsandbox.com' if SQUARE_ENV != 'production'
    else 'https://connect.squareup.com'
)
SQUARE_API_VERSION = '2024-01-18'


def is_configured():
    return bool(SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID)


def _headers():
    return {
        'Square-Version': SQUARE_API_VERSION,
        'Authorization': f'Bearer {SQUARE_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }


def _to_cents(amount_usd):
    """Square amounts are integer minor units (cents), never floats."""
    return int(round(float(amount_usd or 0) * 100))


def create_payment_link(amount_usd, txn_id, description='BitPaw POS Order'):
    """Square Checkout API — hosted payment link, works with no physical hardware.
    Docs: POST /v2/online-checkout/payment-links
    """
    if not is_configured():
        return {
            'success': False,
            'configured': False,
            'message': 'Square Sandbox chưa được cấu hình (thiếu SQUARE_ACCESS_TOKEN/SQUARE_LOCATION_ID trong .env). '
                       'Đăng ký sandbox tại https://developer.squareup.com/apps để lấy access token.'
        }
    try:
        payload = {
            'idempotency_key': uuid.uuid4().hex,
            'quick_pay': {
                'name': description,
                'price_money': {'amount': _to_cents(amount_usd), 'currency': 'USD'},
                'location_id': SQUARE_LOCATION_ID
            },
            'checkout_options': {
                'reference_id': txn_id
            }
        }
        resp = requests.post(f'{SQUARE_API_BASE}/v2/online-checkout/payment-links',
                              headers=_headers(), json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        link = data.get('payment_link', {})
        return {
            'success': True,
            'configured': True,
            'checkout_id': link.get('id'),
            'checkout_url': link.get('url'),
            'order_id': link.get('order_id')
        }
    except requests.exceptions.RequestException as e:
        return {'success': False, 'configured': True, 'message': f'Square API error: {str(e)}'}


def create_terminal_checkout(amount_usd, txn_id, note='BitPaw POS Order'):
    """Square Terminal API — pushes a checkout to a physical Square Terminal/reader.
    Docs: POST /v2/terminals/checkouts
    Only used when SQUARE_DEVICE_ID is configured (real hardware paired to the tenant).
    """
    if not is_configured() or not SQUARE_DEVICE_ID:
        return {
            'success': False,
            'configured': False,
            'message': 'Chưa cấu hình Square Terminal (thiếu SQUARE_ACCESS_TOKEN/SQUARE_LOCATION_ID/SQUARE_DEVICE_ID).'
        }
    try:
        payload = {
            'idempotency_key': uuid.uuid4().hex,
            'checkout': {
                'amount_money': {'amount': _to_cents(amount_usd), 'currency': 'USD'},
                'device_options': {'device_id': SQUARE_DEVICE_ID},
                'reference_id': txn_id,
                'note': note
            }
        }
        resp = requests.post(f'{SQUARE_API_BASE}/v2/terminals/checkouts',
                              headers=_headers(), json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        checkout = data.get('checkout', {})
        return {
            'success': True,
            'configured': True,
            'checkout_id': checkout.get('id'),
            'terminal_status': checkout.get('status'),
            'device_id': SQUARE_DEVICE_ID
        }
    except requests.exceptions.RequestException as e:
        return {'success': False, 'configured': True, 'message': f'Square API error: {str(e)}'}


def start_us_payment(amount_usd, txn_id, description='BitPaw POS Order'):
    """Entry point used by /api/us-payment/start. Prefers a physical Terminal checkout
    when a device is paired to the tenant, otherwise falls back to a hosted payment link
    (no hardware required — works today in Sandbox with no Square Terminal on hand)."""
    if SQUARE_DEVICE_ID:
        result = create_terminal_checkout(amount_usd, txn_id, note=description)
        if result.get('configured'):
            return result
    return create_payment_link(amount_usd, txn_id, description=description)
