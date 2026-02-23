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

DEFAULT_EMPLOYEE_PASSWORD = 'Ee@123'
ADMIN_TOGGLE_PASSWORD = os.environ.get('ADMIN_TOGGLE_PASSWORD', '')
SUPER_ADMIN_EMAIL = 'henryoverbeeke@gmail.com'


def resp(status, body):
    return {
        'statusCode': status,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'
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
            email = user['email']
            # Check if admin/company owner
            profile = table.get_item(Key={'pk': f'COMPANY#{email}', 'sk': 'PROFILE'})
            if 'Item' in profile:
                return {
                    'email': email,
                    'company_id': email,
                    'role': 'admin',
                    'name': profile['Item'].get('company_name', email),
                    'agent_name': profile['Item'].get('company_name', email)
                }
            # Check if employee
            emp_lookup = table.get_item(Key={'pk': f'EMPLOYEE_LOOKUP#{email}', 'sk': 'META'})
            if 'Item' in emp_lookup:
                emp = emp_lookup['Item']
                return {
                    'email': email,
                    'company_id': emp['company_id'],
                    'role': 'employee',
                    'name': emp.get('employee_name', email),
                    'agent_name': emp.get('employee_name', email),
                    'must_change_password': emp.get('must_change_password', False)
                }
            return {'email': email, 'company_id': email, 'role': 'unknown', 'name': email, 'agent_name': email}
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

        # Determine role + check must_change_password
        role = 'unknown'
        must_change = False
        name = email

        profile = table.get_item(Key={'pk': f'COMPANY#{email}', 'sk': 'PROFILE'})
        if 'Item' in profile:
            role = 'admin'
            name = profile['Item'].get('company_name', email)
        else:
            emp = table.get_item(Key={'pk': f'EMPLOYEE_LOOKUP#{email}', 'sk': 'META'})
            if 'Item' in emp:
                role = 'employee'
                name = emp['Item'].get('employee_name', email)
                must_change = bool(emp['Item'].get('must_change_password', False))

        return resp(200, {
            'access_token': auth['AccessToken'],
            'id_token': auth['IdToken'],
            'refresh_token': auth['RefreshToken'],
            'role': role,
            'name': name,
            'must_change_password': must_change
        })
    except cognito.exceptions.NotAuthorizedException:
        return resp(401, {'error': 'Invalid email or password'})
    except cognito.exceptions.UserNotFoundException:
        return resp(404, {'error': 'User not found'})
    except Exception as e:
        return resp(500, {'error': str(e)})


def handle_change_password(auth, body):
    old_pw = body.get('old_password', '')
    new_pw = body.get('new_password', '')
    token = body.get('access_token', '')
    if not old_pw or not new_pw or not token:
        return resp(400, {'error': 'old_password, new_password, and access_token required'})

    try:
        cognito.change_password(
            PreviousPassword=old_pw,
            ProposedPassword=new_pw,
            AccessToken=token
        )
        # Clear the must_change_password flag
        email = auth['email']
        emp = table.get_item(Key={'pk': f'EMPLOYEE_LOOKUP#{email}', 'sk': 'META'})
        if 'Item' in emp:
            cid = emp['Item']['company_id']
            table.update_item(
                Key={'pk': f'EMPLOYEE_LOOKUP#{email}', 'sk': 'META'},
                UpdateExpression='SET must_change_password = :f',
                ExpressionAttributeValues={':f': False}
            )
            table.update_item(
                Key={'pk': f'COMPANY#{cid}', 'sk': f'EMPLOYEE#{email}'},
                UpdateExpression='SET must_change_password = :f',
                ExpressionAttributeValues={':f': False}
            )
        return resp(200, {'message': 'Password changed successfully'})
    except cognito.exceptions.NotAuthorizedException:
        return resp(401, {'error': 'Current password is incorrect'})
    except Exception as e:
        return resp(500, {'error': str(e)})


# ─── Settings ───

def get_paywall_enabled():
    r = table.get_item(Key={'pk': 'SETTINGS', 'sk': 'PAYWALL'})
    if 'Item' in r:
        return bool(r['Item'].get('enabled', False))
    return False


def handle_toggle_paywall(auth, body):
    if auth['email'] != SUPER_ADMIN_EMAIL:
        return resp(403, {'error': 'Only the platform owner can toggle this'})
    pw = body.get('password', '')
    if pw != ADMIN_TOGGLE_PASSWORD:
        return resp(403, {'error': 'Wrong password'})
    current = get_paywall_enabled()
    table.put_item(Item={'pk': 'SETTINGS', 'sk': 'PAYWALL', 'enabled': not current})
    return resp(200, {'paywall_enabled': not current})


def handle_get_settings():
    return resp(200, {'paywall_enabled': get_paywall_enabled()})


def verify_stripe_session(session_id):
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
    profile = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': 'PROFILE'}).get('Item', {})
    if profile.get('paid'):
        return resp(200, {'activated': True, 'already_paid': True})

    session_id = body.get('session_id', '').strip()
    if not session_id:
        return resp(400, {'error': 'session_id required'})

    valid, detail = verify_stripe_session(session_id)
    if not valid:
        return resp(403, {'error': f'Payment verification failed: {detail}'})

    used = table.get_item(Key={'pk': f'STRIPE_SESSION#{session_id}', 'sk': 'META'})
    if 'Item' in used:
        return resp(400, {'error': 'This payment session has already been used'})

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
        'role': auth['role'],
        'is_super_admin': auth['email'] == SUPER_ADMIN_EMAIL,
        'agent_name': auth.get('agent_name', ''),
        'must_change_password': auth.get('must_change_password', False),
        'created_at': int(item.get('created_at', 0))
    })


# ─── Employee management (admin only) ───

def handle_create_employee(auth, body):
    if auth['role'] != 'admin':
        return resp(403, {'error': 'Admin only'})

    cid = auth['company_id']
    emp_email = body.get('email', '').strip().lower()
    emp_name = body.get('name', '').strip()

    if not emp_email or not emp_name:
        return resp(400, {'error': 'Employee email and name required'})

    # Check if already exists
    existing = table.get_item(Key={'pk': f'EMPLOYEE_LOOKUP#{emp_email}', 'sk': 'META'})
    if 'Item' in existing:
        return resp(400, {'error': 'Employee already exists'})

    try:
        client_id = get_client_id()
        cognito.sign_up(
            ClientId=client_id, Username=emp_email, Password=DEFAULT_EMPLOYEE_PASSWORD,
            UserAttributes=[{'Name': 'email', 'Value': emp_email}]
        )
    except cognito.exceptions.UsernameExistsException:
        pass
    except Exception as e:
        return resp(500, {'error': f'Failed to create user: {str(e)}'})

    ts = int(time.time())
    with table.batch_writer() as batch:
        batch.put_item(Item={
            'pk': f'COMPANY#{cid}', 'sk': f'EMPLOYEE#{emp_email}',
            'employee_email': emp_email, 'employee_name': emp_name,
            'must_change_password': True, 'created_at': ts,
            'active_chat': '', 'last_active': 0
        })
        batch.put_item(Item={
            'pk': f'EMPLOYEE_LOOKUP#{emp_email}', 'sk': 'META',
            'company_id': cid, 'employee_name': emp_name,
            'must_change_password': True
        })

    return resp(200, {
        'employee_email': emp_email,
        'employee_name': emp_name,
        'default_password': DEFAULT_EMPLOYEE_PASSWORD
    })


def handle_list_employees(auth):
    if auth['role'] != 'admin':
        return resp(403, {'error': 'Admin only'})

    cid = auth['company_id']
    r = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'COMPANY#{cid}', ':prefix': 'EMPLOYEE#'}
    )
    employees = []
    for item in r.get('Items', []):
        employees.append({
            'email': item.get('employee_email', ''),
            'name': item.get('employee_name', ''),
            'must_change_password': bool(item.get('must_change_password', False)),
            'default_password': DEFAULT_EMPLOYEE_PASSWORD if item.get('must_change_password') else None,
            'active_chat': item.get('active_chat', ''),
            'last_active': int(item.get('last_active', 0)),
            'created_at': int(item.get('created_at', 0))
        })
    return resp(200, {'employees': employees})


def handle_delete_employee(auth, body):
    if auth['role'] != 'admin':
        return resp(403, {'error': 'Admin only'})

    cid = auth['company_id']
    emp_email = body.get('email', '').strip().lower()
    if not emp_email:
        return resp(400, {'error': 'Employee email required'})

    table.delete_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'EMPLOYEE#{emp_email}'})
    table.delete_item(Key={'pk': f'EMPLOYEE_LOOKUP#{emp_email}', 'sk': 'META'})

    try:
        pool_id = get_user_pool_id()
        if pool_id:
            cognito.admin_delete_user(UserPoolId=pool_id, Username=emp_email)
    except Exception:
        pass

    return resp(200, {'deleted': emp_email})


# ─── Chat with agent tracking ───

def handle_get_chats(auth):
    cid = auth['company_id']
    r = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'COMPANY#{cid}', ':prefix': 'CHATSESSION#'},
        ScanIndexForward=False
    )
    chats = []
    for item in r.get('Items', []):
        agents = item.get('active_agents', {})
        if isinstance(agents, set):
            agents = list(agents)
        elif isinstance(agents, dict):
            agents = list(agents.keys()) if agents else []

        chats.append({
            'customer_id': item.get('customer_id', ''),
            'customer_name': item.get('customer_name', ''),
            'ticket_code': item.get('ticket_code', ''),
            'last_message': item.get('last_message', ''),
            'last_sender': item.get('last_sender', ''),
            'priority': item.get('priority', 'normal'),
            'status': item.get('status', 'open'),
            'active_agents': agents,
            'updated_at': int(item.get('updated_at', 0)),
            'created_at': int(item.get('created_at', 0)),
            'unread': item.get('unread', 0)
        })
    chats.sort(key=lambda c: c['updated_at'], reverse=True)
    return resp(200, {'chats': chats})


def handle_join_chat(auth, body):
    cid = auth['company_id']
    customer_id = body.get('customer_id', '')
    if not customer_id:
        return resp(400, {'error': 'customer_id required'})

    agent_name = auth.get('agent_name', auth['email'])
    agent_email = auth['email']

    # Add to active_agents map on the session
    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET active_agents.#ae = :an',
        ExpressionAttributeNames={'#ae': agent_email},
        ExpressionAttributeValues={':an': agent_name}
    )

    # Track on employee record
    if auth['role'] == 'employee':
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'EMPLOYEE#{agent_email}'},
            UpdateExpression='SET active_chat = :c, last_active = :t',
            ExpressionAttributeValues={':c': customer_id, ':t': int(time.time())}
        )

    return resp(200, {'joined': customer_id})


def handle_leave_chat(auth, body):
    cid = auth['company_id']
    customer_id = body.get('customer_id', '')
    if not customer_id:
        return resp(400, {'error': 'customer_id required'})

    agent_email = auth['email']

    try:
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='REMOVE active_agents.#ae',
            ExpressionAttributeNames={'#ae': agent_email}
        )
    except Exception:
        pass

    if auth['role'] == 'employee':
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'EMPLOYEE#{agent_email}'},
            UpdateExpression='SET active_chat = :e',
            ExpressionAttributeValues={':e': ''}
        )

    return resp(200, {'left': customer_id})


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

    sender_name = auth.get('agent_name', auth['email'])
    ts = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())

    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'company', 'sender_name': sender_name,
        'message': message, 'created_at': ts
    })

    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t',
        ExpressionAttributeValues={':m': message, ':s': 'company', ':t': ts}
    )

    return resp(200, {'status': 'sent', 'created_at': ts})


def delete_chat(cid, customer_id):
    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    ticket_code = ''
    if 'Item' in session:
        ticket_code = session['Item'].get('ticket_code', '')

    msgs = table.query(
        KeyConditionExpression='pk = :pk AND begins_with(sk, :prefix)',
        ExpressionAttributeValues={':pk': f'CHAT#{cid}#{customer_id}', ':prefix': 'MSG#'},
        ProjectionExpression='pk, sk'
    )
    with table.batch_writer() as batch:
        for item in msgs.get('Items', []):
            batch.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})

    table.delete_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})

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

    agent_name = auth.get('agent_name', auth['email'])
    parts = []
    if priority:
        parts.append(f'priority to {priority.upper()}')
    if status:
        parts.append(f'status to {status.replace("_", " ").title()}')
    sys_msg = f'{agent_name} updated {" and ".join(parts)}'

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
        batch.put_item(Item={
            'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}',
            'customer_id': customer_id, 'customer_name': customer_name,
            'ticket_code': ticket_code,
            'last_message': f'{customer_name} started a chat',
            'last_sender': 'system', 'unread': 1,
            'priority': 'normal', 'status': 'open',
            'active_agents': {},
            'created_at': ts, 'updated_at': ts
        })
        batch.put_item(Item={
            'pk': f'TICKET#{ticket_code}', 'sk': 'META',
            'company_id': cid, 'customer_id': customer_id,
            'customer_name': customer_name, 'chat_code': code
        })
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

    company = resolve_chat_code(item.get('chat_code', ''))
    company_name = company.get('company_name', '') if company else ''

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

    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    if 'Item' not in session:
        return resp(410, {'error': 'closed', 'closed': True})

    si = session['Item']
    session_info = {
        'priority': si.get('priority', 'normal'),
        'status': si.get('status', 'open'),
        'ticket_code': si.get('ticket_code', '')
    }

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
    if path == '/chat/join' and method == 'POST':
        return handle_join_chat(auth, body)
    if path == '/chat/leave' and method == 'POST':
        return handle_leave_chat(auth, body)
    if path == '/auth/change-password' and method == 'POST':
        return handle_change_password(auth, body)
    if path == '/admin/toggle-paywall' and method == 'POST':
        return handle_toggle_paywall(auth, body)
    if path == '/company/activate' and method == 'POST':
        return handle_activate(auth, body)
    if path == '/employees' and method == 'GET':
        return handle_list_employees(auth)
    if path == '/employees/create' and method == 'POST':
        return handle_create_employee(auth, body)
    if path == '/employees/delete' and method == 'POST':
        return handle_delete_employee(auth, body)

    return resp(404, {'error': f'Not found: {method} {path}'})
