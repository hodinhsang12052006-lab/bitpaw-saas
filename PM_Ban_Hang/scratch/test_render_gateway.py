import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/..'))

from flask import Flask, render_template

app = Flask(__name__, template_folder='../templates')

@app.route('/')
def index():
    # Mocking essential config object for the template
    mock_config = {
        'type': 'vietqr',
        'active': True,
        'is_default': True,
        'bank_code': 'MB',
        'bank_name': 'MB (Ngân hàng Quân Đội)',
        'account_number': '123456789',
        'account_holder': 'CUA HANG TEST FNB',
        'transfer_prefix': 'BITPAW'
    }
    try:
        html = render_template('payment_gateway.html', 
                               config=mock_config,
                               supabase_url='https://mock.supabase.co',
                               supabase_key='mock-key')
        print("SUCCESSFULLY RENDERED")
        return html
    except Exception as e:
        print("ERROR RENDER:", e)
        raise e

if __name__ == '__main__':
    with app.test_request_context():
        index()
