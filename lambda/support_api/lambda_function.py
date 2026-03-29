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
ec2_client = boto3.client('ec2', region_name='us-east-2')
table = dynamodb.Table('Support8')

DEFAULT_EMPLOYEE_PASSWORD = 'Ee@123'
ADMIN_TOGGLE_PASSWORD = os.environ.get('ADMIN_TOGGLE_PASSWORD', '')
EMERGENCY_PASSWORD = os.environ.get('EMERGENCY_PASSWORD', '')
SUPER_ADMIN_EMAIL = 'henryoverbeeke@gmail.com'
SUPPORT8_EC2_ID = 'i-0f5c06b789f5f6629'
SUPPORT8_USERPOOL = 'us-east-2_s5ZsrYKyK'
EMERGENCY_EMAIL = 'jimmy@panic.com'
LOCKOUT_SECONDS = 10 * 24 * 60 * 60


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
        # Auto-clean ghost entries (no customer_id means it was a phantom create)
        if not item.get('customer_id'):
            table.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})
            continue

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
            'unread': item.get('unread', 0),
            'eta_target': int(item.get('eta_target', 0))
        })
    chats.sort(key=lambda c: c['updated_at'], reverse=True)
    return resp(200, {'chats': chats})


def handle_force_delete_chat(auth, body):
    """Force-delete a ghost or stuck chat session."""
    cid = auth['company_id']
    customer_id = body.get('customer_id', '')
    if not customer_id:
        return resp(400, {'error': 'customer_id required'})
    delete_chat(cid, customer_id)
    return resp(200, {'deleted': customer_id})


def handle_join_chat(auth, body):
    cid = auth['company_id']
    customer_id = body.get('customer_id', '')
    if not customer_id:
        return resp(400, {'error': 'customer_id required'})

    agent_name = auth.get('agent_name', auth['email'])
    agent_email = auth['email']

    try:
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='SET active_agents.#ae = :an',
            ExpressionAttributeNames={'#ae': agent_email},
            ExpressionAttributeValues={':an': agent_name},
            ConditionExpression='attribute_exists(customer_id)'
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return resp(404, {'error': 'Chat not found'})

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
            ExpressionAttributeNames={'#ae': agent_email},
            ConditionExpression='attribute_exists(customer_id)'
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

    try:
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='SET unread = :z',
            ExpressionAttributeValues={':z': 0},
            ConditionExpression='attribute_exists(customer_id)'
        )
    except Exception:
        pass

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

    # Verify session exists before sending
    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    if 'Item' not in session or not session['Item'].get('customer_id'):
        return resp(410, {'error': 'This chat no longer exists'})

    sender_name = auth.get('agent_name', auth['email'])
    ts = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())

    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'company', 'sender_name': sender_name,
        'message': message, 'created_at': ts
    })

    try:
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t',
            ExpressionAttributeValues={':m': message, ':s': 'company', ':t': ts},
            ConditionExpression='attribute_exists(customer_id)'
        )
    except Exception:
        pass

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
    eta_minutes = body.get('eta_minutes')

    if not priority and not status and eta_minutes is None:
        return resp(400, {'error': 'Provide priority, status, or eta_minutes to update'})

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

    if eta_minutes is not None:
        eta_val = int(eta_minutes) if eta_minutes else 0
        if eta_val > 0:
            eta_target = int(time.time() * 1000) + (eta_val * 60 * 1000)
            update_parts.append('eta_target = :eta')
            values[':eta'] = eta_target
        else:
            update_parts.append('eta_target = :eta')
            values[':eta'] = 0

    ts = int(time.time() * 1000)
    update_parts.append('updated_at = :t')
    values[':t'] = ts

    try:
        update_kwargs = {
            'Key': {'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            'UpdateExpression': 'SET ' + ', '.join(update_parts),
            'ExpressionAttributeValues': values,
            'ConditionExpression': 'attribute_exists(customer_id)'
        }
        if names:
            update_kwargs['ExpressionAttributeNames'] = names
        table.update_item(**update_kwargs)
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return resp(410, {'error': 'This chat no longer exists'})

    agent_name = auth.get('agent_name', auth['email'])
    parts = []
    if priority:
        parts.append(f'priority to {priority.upper()}')
    if status:
        parts.append(f'status to {status.replace("_", " ").title()}')
    if eta_minutes is not None:
        eta_val = int(eta_minutes) if eta_minutes else 0
        if eta_val > 0:
            if eta_val >= 60:
                h = eta_val // 60
                m = eta_val % 60
                eta_str = f'{h}h {m}m' if m else f'{h}h'
            else:
                eta_str = f'{eta_val}m'
            parts.append(f'estimated response time to {eta_str}')
        else:
            parts.append('cleared the estimated response time')
    sys_msg = f'{agent_name} updated {" and ".join(parts)}'

    msg_id = str(uuid.uuid4())
    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'system', 'sender_name': 'System',
        'message': sys_msg, 'created_at': ts
    })

    try:
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='SET last_message = :m, last_sender = :s',
            ExpressionAttributeValues={':m': sys_msg, ':s': 'system'},
            ConditionExpression='attribute_exists(customer_id)'
        )
    except Exception:
        pass

    return resp(200, {'status': 'updated', 'message': sys_msg})


# ─── Public customer routes ───

def resolve_chat_code(code):
    r = table.get_item(Key={'pk': f'CHATCODE#{code}', 'sk': 'META'})
    if 'Item' in r:
        return r['Item']
    return None


def handle_public_start_chat(body, source_ip=''):
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
            'customer_ip': source_ip,
            'ticket_code': ticket_code,
            'last_message': f'{customer_name} started a chat',
            'last_sender': 'system', 'unread': 1,
            'priority': 'normal', 'status': 'waiting',
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


def handle_public_send(body, source_ip=''):
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

    if session['Item'].get('disabled'):
        return resp(403, {'error': 'This conversation has been disabled.'})

    ts = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())

    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'customer', 'sender_name': customer_name,
        'message': message, 'created_at': ts
    })

    try:
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t, unread = unread + :one',
            ExpressionAttributeValues={':m': message, ':s': 'customer', ':t': ts, ':one': 1},
            ConditionExpression='attribute_exists(customer_id)'
        )
    except Exception:
        pass

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
        'ticket_code': si.get('ticket_code', ''),
        'eta_target': int(si.get('eta_target', 0))
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


# ─── Super Admin helpers ───

def _require_super_admin(auth, body):
    if auth['email'] != SUPER_ADMIN_EMAIL:
        return resp(403, {'error': 'Super admin access required'})
    return None


def _require_super_admin_pw(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    pw = body.get('password', '')
    if pw != ADMIN_TOGGLE_PASSWORD:
        return resp(403, {'error': 'Wrong password'})
    return None


# ─── Admin: User Management ───

def handle_admin_list_users(auth):
    err = _require_super_admin(auth, {})
    if err:
        return err
    try:
        users = []
        paginator = cognito.get_paginator('list_users')
        for page in paginator.paginate(UserPoolId=SUPPORT8_USERPOOL):
            for u in page.get('Users', []):
                attrs = {a['Name']: a['Value'] for a in u.get('Attributes', [])}
                users.append({
                    'username': u['Username'],
                    'email': attrs.get('email', u['Username']),
                    'status': u.get('UserStatus', ''),
                    'enabled': u.get('Enabled', True),
                    'created': str(u.get('UserCreateDate', '')),
                    'modified': str(u.get('UserLastModifiedDate', ''))
                })
        return resp(200, {'users': users})
    except Exception as e:
        return resp(500, {'error': str(e)})


def handle_admin_delete_user(auth, body):
    err = _require_super_admin_pw(auth, body)
    if err:
        return err
    target_email = body.get('email', '').strip().lower()
    if not target_email:
        return resp(400, {'error': 'email required'})
    if target_email == SUPER_ADMIN_EMAIL:
        return resp(400, {'error': 'Cannot delete super admin'})

    try:
        cognito.admin_delete_user(UserPoolId=SUPPORT8_USERPOOL, Username=target_email)
    except Exception:
        pass

    table.delete_item(Key={'pk': f'COMPANY#{target_email}', 'sk': 'PROFILE'})
    table.delete_item(Key={'pk': f'EMPLOYEE_LOOKUP#{target_email}', 'sk': 'META'})

    return resp(200, {'deleted': target_email})


# ─── Admin: Emergency Mode ───

def handle_admin_emergency_status(auth):
    err = _require_super_admin(auth, {})
    if err:
        return err
    item = table.get_item(Key={'pk': 'SETTINGS', 'sk': 'EMERGENCY'}).get('Item', {})
    return resp(200, {
        'active': bool(item.get('active', False)),
        'message': item.get('message', ''),
        'activated_at': int(item.get('activated_at', 0))
    })


def handle_admin_emergency_activate(auth, body):
    err = _require_super_admin_pw(auth, body)
    if err:
        return err
    message = body.get('message', 'Service temporarily unavailable.')
    table.put_item(Item={
        'pk': 'SETTINGS', 'sk': 'EMERGENCY',
        'active': True, 'message': message,
        'activated_at': int(time.time())
    })
    return resp(200, {'active': True, 'message': message})


def handle_admin_emergency_deactivate(auth, body):
    err = _require_super_admin_pw(auth, body)
    if err:
        return err
    table.put_item(Item={
        'pk': 'SETTINGS', 'sk': 'EMERGENCY',
        'active': False, 'message': '', 'activated_at': 0
    })
    return resp(200, {'active': False})


# ─── Admin: AutoBot System ───

def handle_admin_all_chats(auth):
    err = _require_super_admin(auth, {})
    if err:
        return err
    r = table.scan(
        FilterExpression='begins_with(sk, :prefix) AND attribute_exists(customer_id)',
        ExpressionAttributeValues={':prefix': 'CHATSESSION#'}
    )
    chats = []
    for item in r.get('Items', []):
        cid = item['pk'].replace('COMPANY#', '')
        chats.append({
            'company_id': cid,
            'customer_id': item.get('customer_id', ''),
            'customer_name': item.get('customer_name', ''),
            'customer_ip': item.get('customer_ip', ''),
            'ticket_code': item.get('ticket_code', ''),
            'last_message': item.get('last_message', ''),
            'priority': item.get('priority', 'normal'),
            'status': item.get('status', 'open'),
            'disabled': bool(item.get('disabled', False)),
            'updated_at': int(item.get('updated_at', 0)),
            'created_at': int(item.get('created_at', 0))
        })
    chats.sort(key=lambda c: c['updated_at'], reverse=True)
    return resp(200, {'chats': chats})


def handle_admin_autobot_send(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    cid = body.get('company_id', '')
    customer_id = body.get('customer_id', '')
    message = body.get('message', '').strip()
    if not cid or not customer_id or not message:
        return resp(400, {'error': 'company_id, customer_id, and message required'})

    session = table.get_item(Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'})
    if 'Item' not in session:
        return resp(404, {'error': 'Chat not found'})

    ts = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())
    table.put_item(Item={
        'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
        'sender': 'company', 'sender_name': 'AutoBot',
        'message': message, 'created_at': ts
    })
    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t',
        ExpressionAttributeValues={':m': message, ':s': 'company', ':t': ts}
    )
    return resp(200, {'sent': True, 'created_at': ts})


def handle_admin_autobot_mass(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    message = body.get('message', '').strip()
    if not message:
        return resp(400, {'error': 'message required'})

    r = table.scan(
        FilterExpression='begins_with(sk, :prefix) AND attribute_exists(customer_id)',
        ExpressionAttributeValues={':prefix': 'CHATSESSION#'}
    )
    sent_count = 0
    ts = int(time.time() * 1000)
    for item in r.get('Items', []):
        cid = item['pk'].replace('COMPANY#', '')
        customer_id = item.get('customer_id', '')
        if not customer_id:
            continue
        msg_id = str(uuid.uuid4())
        table.put_item(Item={
            'pk': f'CHAT#{cid}#{customer_id}', 'sk': f'MSG#{ts}#{msg_id}',
            'sender': 'company', 'sender_name': 'AutoBot',
            'message': message, 'created_at': ts
        })
        table.update_item(
            Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
            UpdateExpression='SET last_message = :m, last_sender = :s, updated_at = :t',
            ExpressionAttributeValues={':m': message, ':s': 'company', ':t': ts}
        )
        sent_count += 1
    return resp(200, {'sent_count': sent_count})


def handle_admin_chat_disable(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    cid = body.get('company_id', '')
    customer_id = body.get('customer_id', '')
    if not cid or not customer_id:
        return resp(400, {'error': 'company_id and customer_id required'})
    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET disabled = :t',
        ExpressionAttributeValues={':t': True}
    )
    return resp(200, {'disabled': True})


def handle_admin_chat_enable(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    cid = body.get('company_id', '')
    customer_id = body.get('customer_id', '')
    if not cid or not customer_id:
        return resp(400, {'error': 'company_id and customer_id required'})
    table.update_item(
        Key={'pk': f'COMPANY#{cid}', 'sk': f'CHATSESSION#{customer_id}'},
        UpdateExpression='SET disabled = :f',
        ExpressionAttributeValues={':f': False}
    )
    return resp(200, {'disabled': False})


# ─── Admin: IP Management ───

def handle_admin_list_ips(auth):
    err = _require_super_admin(auth, {})
    if err:
        return err
    blocked = table.scan(
        FilterExpression='begins_with(pk, :prefix)',
        ExpressionAttributeValues={':prefix': 'BLOCKED_IP#'}
    )
    blocked_ips = []
    for item in blocked.get('Items', []):
        blocked_ips.append({
            'ip': item['pk'].replace('BLOCKED_IP#', ''),
            'blocked_at': int(item.get('blocked_at', 0)),
            'reason': item.get('reason', '')
        })

    tracked = table.scan(
        FilterExpression='begins_with(sk, :prefix) AND attribute_exists(customer_ip)',
        ExpressionAttributeValues={':prefix': 'CHATSESSION#'},
        ProjectionExpression='customer_id, customer_name, customer_ip, pk, updated_at'
    )
    ip_map = {}
    for item in tracked.get('Items', []):
        ip = item.get('customer_ip', '')
        if not ip:
            continue
        if ip not in ip_map:
            ip_map[ip] = {'ip': ip, 'sessions': [], 'blocked': False}
        ip_map[ip]['sessions'].append({
            'customer_id': item.get('customer_id', ''),
            'customer_name': item.get('customer_name', ''),
            'company_id': item['pk'].replace('COMPANY#', ''),
            'updated_at': int(item.get('updated_at', 0))
        })
    for bip in blocked_ips:
        if bip['ip'] in ip_map:
            ip_map[bip['ip']]['blocked'] = True
        else:
            ip_map[bip['ip']] = {'ip': bip['ip'], 'sessions': [], 'blocked': True}

    return resp(200, {'ips': list(ip_map.values()), 'blocked_ips': blocked_ips})


def handle_admin_block_ip(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    ip = body.get('ip', '').strip()
    reason = body.get('reason', '')
    if not ip:
        return resp(400, {'error': 'ip required'})
    table.put_item(Item={
        'pk': f'BLOCKED_IP#{ip}', 'sk': 'META',
        'blocked_at': int(time.time()), 'reason': reason
    })
    return resp(200, {'blocked': ip})


def handle_admin_unblock_ip(auth, body):
    err = _require_super_admin(auth, body)
    if err:
        return err
    ip = body.get('ip', '').strip()
    if not ip:
        return resp(400, {'error': 'ip required'})
    table.delete_item(Key={'pk': f'BLOCKED_IP#{ip}', 'sk': 'META'})
    return resp(200, {'unblocked': ip})


# ─── IP & Emergency checks for public routes ───

def _check_ip_blocked(source_ip):
    if not source_ip:
        return False
    item = table.get_item(Key={'pk': f'BLOCKED_IP#{source_ip}', 'sk': 'META'})
    return 'Item' in item


def _check_emergency_mode():
    item = table.get_item(Key={'pk': 'SETTINGS', 'sk': 'EMERGENCY'}).get('Item', {})
    if item.get('active'):
        return item.get('message', 'Service temporarily unavailable.')
    return None


# ─── Router ───

def handle_emergency_check_lockout(body):
    email = (body.get('email') or '').strip().lower()
    if email != EMERGENCY_EMAIL:
        return resp(403, {'error': 'Access denied'})

    item = table.get_item(Key={'pk': 'EMERGENCY:LOCKOUT', 'sk': 'STATUS'}).get('Item')
    if item:
        locked_until = item.get('locked_until', 0)
        if locked_until > int(time.time()):
            remaining = locked_until - int(time.time())
            days = remaining // 86400
            return resp(403, {'locked': True, 'days_remaining': days + 1})
    return resp(200, {'locked': False})


def handle_emergency_verify(body):
    email = (body.get('email') or '').strip().lower()
    password = body.get('password', '')

    if email != EMERGENCY_EMAIL:
        return resp(403, {'error': 'Access denied'})

    item = table.get_item(Key={'pk': 'EMERGENCY:LOCKOUT', 'sk': 'STATUS'}).get('Item')
    if item:
        locked_until = item.get('locked_until', 0)
        if locked_until > int(time.time()):
            remaining = locked_until - int(time.time())
            days = remaining // 86400
            return resp(403, {'error': f'Locked out for {days + 1} more days', 'locked': True})

    attempts = int((item or {}).get('attempts', 0)) if item else 0

    if password != EMERGENCY_PASSWORD:
        attempts += 1
        if attempts >= 2:
            table.put_item(Item={
                'pk': 'EMERGENCY:LOCKOUT', 'sk': 'STATUS',
                'attempts': attempts,
                'locked_until': int(time.time()) + LOCKOUT_SECONDS
            })
            return resp(403, {'error': 'Too many attempts. Locked for 10 days.', 'locked': True})
        else:
            table.put_item(Item={
                'pk': 'EMERGENCY:LOCKOUT', 'sk': 'STATUS',
                'attempts': attempts,
                'locked_until': 0
            })
            return resp(401, {'error': f'Wrong password. {2 - attempts} attempt(s) remaining.', 'attempts_left': 2 - attempts})

    table.delete_item(Key={'pk': 'EMERGENCY:LOCKOUT', 'sk': 'STATUS'})
    token = hashlib.sha256(f'{email}{time.time()}{random.random()}'.encode()).hexdigest()
    table.put_item(Item={
        'pk': 'EMERGENCY:TOKEN', 'sk': token,
        'created_at': int(time.time()),
        'ttl': int(time.time()) + 3600
    })
    return resp(200, {'verified': True, 'emergency_token': token})


def _check_emergency_token(body):
    token = body.get('emergency_token', '')
    item = table.get_item(Key={'pk': 'EMERGENCY:TOKEN', 'sk': token}).get('Item')
    if not item:
        return False
    if item.get('ttl', 0) < int(time.time()):
        return False
    return True


def handle_emergency_stop_ec2(body):
    if not _check_emergency_token(body):
        return resp(403, {'error': 'Invalid or expired token'})
    try:
        ec2_client.stop_instances(InstanceIds=[SUPPORT8_EC2_ID])
        return resp(200, {'success': True, 'message': 'EC2 instance stopping'})
    except Exception as e:
        return resp(500, {'error': str(e)})


def handle_emergency_disable_cognito(body):
    if not _check_emergency_token(body):
        return resp(403, {'error': 'Invalid or expired token'})
    try:
        disabled = []
        paginator = cognito.get_paginator('list_users')
        for page in paginator.paginate(UserPoolId=SUPPORT8_USERPOOL):
            for user in page.get('Users', []):
                username = user['Username']
                if user.get('Enabled', True):
                    cognito.admin_disable_user(UserPoolId=SUPPORT8_USERPOOL, Username=username)
                    disabled.append(username)
        return resp(200, {'success': True, 'disabled_count': len(disabled)})
    except Exception as e:
        return resp(500, {'error': str(e)})


def handle_emergency_enable_cognito(body):
    if not _check_emergency_token(body):
        return resp(403, {'error': 'Invalid or expired token'})
    try:
        enabled = []
        paginator = cognito.get_paginator('list_users')
        for page in paginator.paginate(UserPoolId=SUPPORT8_USERPOOL):
            for user in page.get('Users', []):
                username = user['Username']
                if not user.get('Enabled', True):
                    cognito.admin_enable_user(UserPoolId=SUPPORT8_USERPOOL, Username=username)
                    enabled.append(username)
        return resp(200, {'success': True, 'enabled_count': len(enabled)})
    except Exception as e:
        return resp(500, {'error': str(e)})


def lambda_handler(event, context):
    method = event.get('httpMethod', 'GET')
    path = event.get('path', '/')
    headers = event.get('headers') or {}
    params = event.get('queryStringParameters') or {}
    body = {}
    source_ip = ''
    try:
        source_ip = event.get('requestContext', {}).get('identity', {}).get('sourceIp', '')
    except Exception:
        pass

    if method == 'OPTIONS':
        return resp(200, {})

    if event.get('body'):
        try:
            body = json.loads(event['body'])
        except Exception:
            body = {}

    # Emergency routes (no auth required, token-based)
    if path == '/emergency/check-lockout' and method == 'POST':
        return handle_emergency_check_lockout(body)
    if path == '/emergency/verify' and method == 'POST':
        return handle_emergency_verify(body)
    if path == '/emergency/stop-ec2' and method == 'POST':
        return handle_emergency_stop_ec2(body)
    if path == '/emergency/disable-cognito' and method == 'POST':
        return handle_emergency_disable_cognito(body)
    if path == '/emergency/enable-cognito' and method == 'POST':
        return handle_emergency_enable_cognito(body)

    # Public routes -- check IP block and emergency mode
    if path.startswith('/public/chat/'):
        if _check_ip_blocked(source_ip):
            return resp(403, {'error': 'Access denied'})
        em = _check_emergency_mode()
        if em:
            return resp(503, {'error': em, 'emergency': True})

    if path == '/settings' and method == 'GET':
        return handle_get_settings()
    if path == '/auth/signup' and method == 'POST':
        return handle_signup(body)
    if path == '/auth/login' and method == 'POST':
        return handle_login(body)
    if path == '/public/chat/start' and method == 'POST':
        return handle_public_start_chat(body, source_ip)
    if path == '/public/chat/lookup' and method == 'POST':
        return handle_public_lookup(body)
    if path == '/public/chat/send' and method == 'POST':
        return handle_public_send(body, source_ip)
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
    if path == '/chat/force-delete' and method == 'POST':
        return handle_force_delete_chat(auth, body)
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

    # Super admin panel routes
    if path == '/admin/users' and method == 'GET':
        return handle_admin_list_users(auth)
    if path == '/admin/users/delete' and method == 'POST':
        return handle_admin_delete_user(auth, body)
    if path == '/admin/emergency/status' and method == 'GET':
        return handle_admin_emergency_status(auth)
    if path == '/admin/emergency/activate' and method == 'POST':
        return handle_admin_emergency_activate(auth, body)
    if path == '/admin/emergency/deactivate' and method == 'POST':
        return handle_admin_emergency_deactivate(auth, body)
    if path == '/admin/chats/all' and method == 'GET':
        return handle_admin_all_chats(auth)
    if path == '/admin/autobot/send' and method == 'POST':
        return handle_admin_autobot_send(auth, body)
    if path == '/admin/autobot/mass' and method == 'POST':
        return handle_admin_autobot_mass(auth, body)
    if path == '/admin/chats/disable' and method == 'POST':
        return handle_admin_chat_disable(auth, body)
    if path == '/admin/chats/enable' and method == 'POST':
        return handle_admin_chat_enable(auth, body)
    if path == '/admin/ips' and method == 'GET':
        return handle_admin_list_ips(auth)
    if path == '/admin/ips/block' and method == 'POST':
        return handle_admin_block_ip(auth, body)
    if path == '/admin/ips/unblock' and method == 'POST':
        return handle_admin_unblock_ip(auth, body)

    return resp(404, {'error': f'Not found: {method} {path}'})
