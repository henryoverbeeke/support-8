import json
import os
import boto3
import uuid
import time
import hashlib
import random

dynamodb = boto3.resource('dynamodb', region_name='us-east-2')
cognito = boto3.client('cognito-idp', region_name='us-east-2')
lambda_client = boto3.client('lambda', region_name='us-east-2')
table = dynamodb.Table('Support8')


def resp(status, body):
    return {
        'statusCode': status,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
        },
        'body': json.dumps(body, default=str)
    }


def validate_cognito_token(token):
    try:
        r = cognito.get_user(AccessToken=token)
        attrs = {a['Name']: a['Value'] for a in r['UserAttributes']}
        return {'email': attrs.get('email'), 'sub': attrs.get('sub')}
    except Exception:
        return None


def get_auth(headers):
    auth_h = headers.get('Authorization') or headers.get('authorization') or ''
    if auth_h.startswith('Bearer '):
        user = validate_cognito_token(auth_h[7:])
        if user:
            return {'company_id': user['email']}
    return None


def generate_chat_code(email):
    return hashlib.sha256(email.encode()).hexdigest()[:8]


def generate_ticket_code():
    for _ in range(50):
        code = str(random.randint(1000, 9999))
        r = table.get_item(Key={'pk': f'TICKET#{code}', 'sk': 'META'})
        if 'Item' not in r:
            return code
    return str(random.randint(10000, 99999))


# ─── Auth ───

def handle_signup(body):
    email = body.get('email', '')
    password = body.get('password', '')
    company_name = body.get('company_name', email.split('@')[0])

    if not email or not password:
        return resp(400, {'error': 'Email and password required'})

    try:
        client_id = get_client_id()
        cognito.sign_up(
            ClientId=client_id, Username=email, Password=password,
            UserAttributes=[{'Name': 'email', 'Value': email}]
        )
        chat_code = generate_chat_code(email)

        with table.batch_writer() as batch:
            batch.put_item(Item={
                'pk': f'COMPANY#{email}', 'sk': 'PROFILE',
                'company_name': company_name, 'email': email,
                'chat_code': chat_code, 'created_at': int(time.time())
            })
            batch.put_item(Item={
                'pk': f'CHATCODE#{chat_code}', 'sk': 'META',
                'company_id': email, 'company_name': company_name
            })

        return resp(200, {'message': 'Account created', 'company_id': email, 'chat_code': chat_code})
    except cognito.exceptions.UsernameExistsException:
        return resp(400, {'error': 'Account already exists'})
    except Exception as e:
        return resp(500, {'error': str(e)})


def handle_login(body):
    email = body.get('email', '')
    password = body.get('password', '')
    if not email or not password:
        return resp(400, {'error': 'Email and password required'})

    try:
        client_id = get_client_id()
        r = cognito.initiate_auth(
            ClientId=client_id, AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={'USERNAME': email, 'PASSWORD': password}
        )
        auth = r['AuthenticationResult']
        return resp(200, {
            'access_token': auth['AccessToken'],
            'id_token': auth['IdToken'],
            'refresh_token': auth['RefreshToken']
        })
    except cognito.exceptions.NotAuthorizedException:
        return resp(401, {'error': 'Invalid email or password'})
    except cognito.exceptions.UserNotFoundException:
        return resp(404, {'error': 'User not found'})
    except Exception as e:
        return resp(500, {'error': str(e)})


# ─── Settings ───

ADMIN_EMAIL = 'henryoverbeeke@gmail.com'

def get_paywall_enabled():
    r = table.get_item(Key={'pk': 'SETTINGS', 'sk': 'PAYWALL'})
    if 'Item' in r:
        return bool(r['Item'].get('enabled', False))
    return False


ADMIN_TOGGLE_PASSWORD = os.environ.get('ADMIN_TOGGLE_PASSWORD', '')

def handle_toggle_paywall(auth, body):
    if auth['company_id'] != ADMIN_EMAIL:
        return resp(403, {'error': 'Admin only'})
    pw = body.get('password', '')
    if pw != ADMIN_TOGGLE_PASSWORD:
        return resp(403, {'error': 'Wrong password'})
    current = get_paywall_enabled()
    table.put_item(Item={'pk': 'SETTINGS', 'sk': 'PAYWALL', 'enabled': not current})
    return resp(200, {'paywall_enabled': not current})


def handle_get_settings():
    return resp(200, {'paywall_enabled': get_paywall_enabled()})


def verify_stripe_session(session_id):
    """Invoke the StripeVerify Lambda to check payment status."""
    try:
        r = lambda_client.invoke(
            FunctionName='Support8_StripeVerify',
            InvocationType='RequestResponse',
            Payload=json.dumps({'session_id': session_id})
        )
        result = json.loads(r['Payload'].read().decode())
        if result.get('verified'):
            return True, result
        return False, result.get('error', 'Verification failed')
    except Exception as e:
        return False, str(e)


def handle_activate(auth, body):
    cid = auth['company_id']

    # Already paid? Skip verification.
    profile = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': 'PROFILE'}).get('Item', {})
    if profile.get('paid'):
        return resp(200, {'activated': True, 'already_paid': True})

    session_id = body.get('session_id', '').strip()
    if not session_id:
        return resp(400, {'error': 'session_id required'})

    valid, detail = verify_stripe_session(session_id)
    if not valid:
        return resp(403, {'error': f'Payment verification failed: {detail}'})

    # Prevent session reuse: check if this session was already used
    used = table.get_item(Key={'pk': f'STRIPE_SESSION#{session_id}', 'sk': 'META'})
    if 'Item' in used:
        return resp(400, {'error': 'This payment session has already been used'})

    # Mark session as used
    table.put_item(Item={
        'pk': f'STRIPE_SESSION#{session_id}', 'sk': 'META',
        'company_id': cid, 'activated_at': int(time.time())
    })

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': 'PROFILE'},
        UpdateExpression='SET paid = :t, stripe_session = :s, paid_at = :ts',
        ExpressionAttributeValues={':t': True, ':s': session_id, ':ts': int(time.time())}
    )
    return resp(200, {'activated': True, 'company_id': cid})


# ─── Company (authenticated) ───

def handle_get_company(auth):
    cid = auth['company_id']
    r = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': 'PROFILE'})
    if 'Item' not in r:
        return resp(404, {'error': 'Company not found'})
    item = r['Item']
    return resp(200, {
        'company_id': cid,
        'company_name': item.get('company_name', ''),
        'chat_code': item.get('chat_code', ''),
        'paid': bool(item.get('paid', False)),
        'is_admin': cid == ADMIN_EMAIL,
        'created_at': int(item.get('created_at', 0))
    })


def handle_get_chats(auth):
    cid = auth['company_id']
    r = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'COMPANY#{cid}', ':prefix': 'CHATSESSION#'},
        ScanIndexForward=False
    )
    chats = []
    for item in r.get('Items', []):
        chats.append({
            'customer_id': item.get('customer_id', ''),
            'customer_name': item.get('customer_name', ''),
            'ticket_code': item.get('ticket_code', ''),
            'last_message': item.get('last_message', ''),
            'last_sender': item.get('last_sender', ''),
            'priority': item.get('priority', 'normal'),
            'status': item.get('status', 'open'),
            'updated_at': int(item.get('updated_at', 0)),
            'created_at': int(item.get('created_at', 0)),
            'unread': item.get('unread', 0)
        })
    chats.sort(key=lambda c: c['updated_at'], reverse=True)
    return resp(200, {'chats': chats})


def handle_get_chat_messages(auth, params):
    cid = auth['company_id']
    customer_id = params.get('customer_id', '')
    if not customer_id:
        return resp(400, {'error': 'customer_id required'})

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET unread = :z',
        ExpressionAttributeValues={':z': 0}
    )

    r = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'CHAT#{cid}#{customer_id}', ':prefix': 'MSG#'},
        ScanIndexForward=True
    )
    messages = []
    for item in r.get('Items', []):
        messages.append({
            'sender': item.get('sender', ''),
            'sender_name': item.get('sender_name', ''),
            'message': item.get('message', ''),
            'created_at': int(item.get('created_at', 0))
        })
    return resp(200, {'messages': messages})


def handle_company_send(auth, body):
    cid = auth['company_id']
    customer_id = body.get('customer_id', '')
    message = body.get('message', '').strip()
    if not customer_id or not message:
        return resp(400, {'error': 'customer_id and message required'})

    company = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': 'PROFILE'}).get('Item', {})
    company_name = company.get('company_name', cid)

    ts = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())

    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'company', 'sender_name': company_name,
        'message': message, 'created_at': ts
    })

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t',
        ExpressionAttributeValues={':m': message, ':s': 'company', ':t': ts}
    )

    return resp(200, {'status': 'sent', 'created_at': ts})


def delete_chat(cid, customer_id):
    """Delete session, all messages, and ticket code lookup."""
    # Get the ticket code from the session first
    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    ticket_code = ''
    if 'Item' in session:
        ticket_code = session['Item'].get('ticket_code', '')

    # Delete all messages
    msgs = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'CHAT#{cid}#{customer_id}', ':prefix': 'MSG#'},
        ProjectionExpression='pk, sk'
    )
    with table.batch_writer() as batch:
        for item in msgs.get('Items', []):
            batch.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})

    # Delete the session
    table.delete_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})

    # Delete the ticket code lookup
    if ticket_code:
        table.delete_item(Key={'pk': f'TICKET#{ticket_code}', 'sk': 'META'})


def handle_update_chat(auth, body):
    cid = auth['company_id']
    customer_id = body.get('customer_id', '')
    if not customer_id:
        return resp(400, {'error': 'customer_id required'})

    priority = body.get('priority')
    status = body.get('status')

    if not priority and not status:
        return resp(400, {'error': 'Provide priority or status to update'})

    # If closing, delete everything
    if status == 'closed':
        delete_chat(cid, customer_id)
        return resp(200, {'status': 'closed', 'message': 'Ticket closed and deleted'})

    update_parts = []
    values = {}
    names = {}

    if priority:
        update_parts.append('#p = :p')
        values[':p'] = priority
        names['#p'] = 'priority'

    if status:
        update_parts.append('#st = :st')
        values[':st'] = status
        names['#st'] = 'status'

    ts = int(time.time() * 1000)
    update_parts.append('updated_at = :t')
    values[':t'] = ts

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET ' + ', '.join(update_parts),
        ExpressionAttributeValues=values,
        ExpressionAttributeNames=names if names else None
    )

    company = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': 'PROFILE'}).get('Item', {})
    company_name = company.get('company_name', cid)

    parts = []
    if priority:
        parts.append(f'priority to {priority.upper()}')
    if status:
        parts.append(f'status to {status.replace("_", " ").title()}')
    sys_msg = f'{company_name} updated {" and ".join(parts)}'

    msg_id = str(uuid.uuid4())
    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'system', 'sender_name': 'System',
        'message': sys_msg, 'created_at': ts
    })

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET last_message = :m, last_sender = :s',
        ExpressionAttributeValues={':m': sys_msg, ':s': 'system'}
    )

    return resp(200, {'status': 'updated', 'message': sys_msg})


# ─── Public customer routes ───

def resolve_chat_code(code):
    r = table.get_item(Key={'pk': f'CHATCODE#{code}', 'sk': 'META'})
    if 'Item' in r:
        return r['Item']
    return None


def handle_public_start_chat(body):
    code = body.get('code', '')
    customer_name = body.get('name', 'Customer')

    company = resolve_chat_code(code)
    if not company:
        return resp(404, {'error': 'Invalid chat link'})

    cid = company['company_id']
    customer_id = str(uuid.uuid4())[:12]
    ticket_code = generate_ticket_code()
    ts = int(time.time() * 1000)

    with table.batch_writer() as batch:
        # Chat session
        batch.put_item(Item={
            'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}',
            'customer_id': customer_id, 'customer_name': customer_name,
            'ticket_code': ticket_code,
            'last_message': f'{customer_name} started a chat',
            'last_sender': 'system', 'unread': 1,
            'priority': 'normal', 'status': 'open',
            'created_at': ts, 'updated_at': ts
        })
        # Ticket code lookup
        batch.put_item(Item={
            'pk': f'TICKET#{ticket_code}', 'sk': 'META',
            'company_id': cid, 'customer_id': customer_id,
            'customer_name': customer_name, 'chat_code': code
        })
        # System message
        batch.put_item(Item={
            'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#system',
            'sender': 'system', 'sender_name': 'System',
            'message': f'{customer_name} started a conversation',
            'created_at': ts
        })

    return resp(200, {
        'customer_id': customer_id,
        'ticket_code': ticket_code,
        'company_name': company.get('company_name', ''),
        'created_at': ts
    })


def handle_public_lookup(body):
    ticket_code = body.get('ticket_code', '').strip()
    if not ticket_code:
        return resp(400, {'error': 'Ticket code required'})

    r = table.get_item(Key={'pk': f'TICKET#{ticket_code}', 'sk': 'META'})
    if 'Item' not in r:
        return resp(404, {'error': 'Ticket not found. It may have been closed.'})

    item = r['Item']
    cid = item['company_id']
    customer_id = item['customer_id']

    # Get company name
    company = resolve_chat_code(item.get('chat_code', ''))
    company_name = company.get('company_name', '') if company else ''

    # Get session info
    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    if 'Item' not in session:
        return resp(404, {'error': 'Ticket not found. It may have been closed.'})

    si = session['Item']
    return resp(200, {
        'customer_id': customer_id,
        'customer_name': item.get('customer_name', ''),
        'ticket_code': ticket_code,
        'chat_code': item.get('chat_code', ''),
        'company_name': company_name,
        'priority': si.get('priority', 'normal'),
        'status': si.get('status', 'open')
    })


def handle_public_send(body):
    code = body.get('code', '')
    customer_id = body.get('customer_id', '')
    message = body.get('message', '').strip()
    customer_name = body.get('name', 'Customer')

    if not code or not customer_id or not message:
        return resp(400, {'error': 'code, customer_id, and message required'})

    company = resolve_chat_code(code)
    if not company:
        return resp(404, {'error': 'Invalid chat link'})

    cid = company['company_id']

    # Check if session still exists (not closed)
    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    if 'Item' not in session:
        return resp(410, {'error': 'This ticket has been closed.'})

    ts = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())

    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'customer', 'sender_name': customer_name,
        'message': message, 'created_at': ts
    })

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t, unread = unread + :one',
        ExpressionAttributeValues={':m': message, ':s': 'customer', ':t': ts, ':one': 1}
    )

    return resp(200, {'status': 'sent', 'created_at': ts})


def handle_public_messages(params):
    code = params.get('code', '')
    customer_id = params.get('customer_id', '')

    if not code or not customer_id:
        return resp(400, {'error': 'code and customer_id required'})

    company = resolve_chat_code(code)
    if not company:
        return resp(404, {'error': 'Invalid chat link'})

    cid = company['company_id']

    # Check if session still exists
    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    if 'Item' not in session:
        return resp(410, {'error': 'closed', 'closed': True})

    si = session['Item']
    session_info = {'priority': si.get('priority', 'normal'), 'status': si.get('status', 'open'), 'ticket_code': si.get('ticket_code', '')}

    r = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'CHAT#{cid}#{customer_id}', ':prefix': 'MSG#'},
        ScanIndexForward=True
    )
    messages = []
    for item in r.get('Items', []):
        messages.append({
            'sender': item.get('sender', ''),
            'sender_name': item.get('sender_name', ''),
            'message': item.get('message', ''),
            'created_at': int(item.get('created_at', 0))
        })

    return resp(200, {'messages': messages, 'company_name': company.get('company_name', ''), 'session': session_info})


# ─── Cognito helpers ───

_pool_id = None
_client_id = None

def get_user_pool_id():
    global _pool_id
    if _pool_id:
        return _pool_id
    r = cognito.list_user_pools(MaxResults=60)
    for p in r['UserPools']:
        if p['Name'] == 'Support8_UserPool':
            _pool_id = p['Id']
            return _pool_id
    return None

def get_client_id():
    global _client_id
    if _client_id:
        return _client_id
    pid = get_user_pool_id()
    if not pid:
        return None
    r = cognito.list_user_pool_clients(UserPoolId=pid, MaxResults=10)
    for c in r['UserPoolClients']:
        if c['ClientName'] == 'Support8_AppClient':
            _client_id = c['ClientId']
            return _client_id
    return None


# ─── Router ───

def lambda_handler(event, context):
    method = event.get('httpMethod', 'GET')
    path = event.get('path', '/')
    headers = event.get('headers') or {}
    params = event.get('queryStringParameters') or {}
    body = {}

    if method == 'OPTIONS':
        return resp(200, {})

    if event.get('body'):
        try:
            body = json.loads(event['body'])
        except Exception:
            body = {}

    # Public routes
    if path == '/settings' and method == 'GET':
        return handle_get_settings()
    if path == '/auth/signup' and method == 'POST':
        return handle_signup(body)
    if path == '/auth/login' and method == 'POST':
        return handle_login(body)
    if path == '/public/chat/start' and method == 'POST':
        return handle_public_start_chat(body)
    if path == '/public/chat/lookup' and method == 'POST':
        return handle_public_lookup(body)
    if path == '/public/chat/send' and method == 'POST':
        return handle_public_send(body)
    if path == '/public/chat/messages' and method == 'GET':
        return handle_public_messages(params)

    # Authenticated routes
    auth = get_auth(headers)
    if not auth:
        return resp(401, {'error': 'Unauthorized'})

    if path == '/company' and method == 'GET':
        return handle_get_company(auth)
    if path == '/chats' and method == 'GET':
        return handle_get_chats(auth)
    if path == '/chat/messages' and method == 'GET':
        return handle_get_chat_messages(auth, params)
    if path == '/chat/send' and method == 'POST':
        return handle_company_send(auth, body)
    if path == '/chat/update' and method == 'POST':
        return handle_update_chat(auth, body)
    if path == '/admin/toggle-paywall' and method == 'POST':
        return handle_toggle_paywall(auth, body)
    if path == '/company/activate' and method == 'POST':
        return handle_activate(auth, body)

    return resp(404, {'error': f'Not found: {method} {path}'})
