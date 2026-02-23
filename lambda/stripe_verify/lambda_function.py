import json
import os
import urllib.request
import urllib.parse
import base64

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')


def lambda_handler(event, context):
    session_id = event.get('session_id', '')
    if not session_id:
        return {'verified': False, 'error': 'No session_id provided'}

    try:
        url = f'https://api.stripe.com/v1/checkout/sessions/{urllib.parse.quote(session_id)}'
        req = urllib.request.Request(url)
        credentials = base64.b64encode(f'{STRIPE_SECRET_KEY}:'.encode()).decode()
        req.add_header('Authorization', f'Basic {credentials}')

        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())

        if data.get('payment_status') == 'paid':
            return {
                'verified': True,
                'payment_status': data['payment_status'],
                'customer_email': data.get('customer_details', {}).get('email', ''),
                'amount_total': data.get('amount_total', 0)
            }

        return {
            'verified': False,
            'error': f'Payment not completed (status: {data.get("payment_status")})'
        }
    except urllib.error.HTTPError as e:
        return {'verified': False, 'error': f'Stripe API error: {e.code}'}
    except Exception as e:
        return {'verified': False, 'error': str(e)}
