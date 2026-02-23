#!/usr/bin/env python3
"""
Support8 EC2 Processing Server
Runs on port 5000, receives support messages from Lambda,
processes them and returns responses. All requests are isolated by company_id.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import time
import hashlib

TICKET_COUNTER = {}

AUTO_RESPONSES = {
    'high': "Your high-priority ticket has been escalated. A support agent will respond within 1 hour.",
    'normal': "Your support request has been received. Expected response time: 4-8 hours.",
    'low': "Your request has been logged. We'll get back to you within 24 hours."
}

CATEGORY_KEYWORDS = {
    'billing': ['payment', 'invoice', 'charge', 'refund', 'subscription', 'price', 'cost', 'bill'],
    'technical': ['error', 'bug', 'crash', 'broken', 'not working', 'issue', 'problem', 'fail'],
    'account': ['password', 'login', 'access', 'permission', 'locked', 'reset', 'account'],
    'feature': ['feature', 'request', 'suggestion', 'improve', 'add', 'want', 'need', 'wish'],
    'general': []
}


def categorize_message(message):
    msg_lower = message.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in msg_lower:
                return category
    return 'general'


def generate_ticket_number(company_id):
    if company_id not in TICKET_COUNTER:
        TICKET_COUNTER[company_id] = 0
    TICKET_COUNTER[company_id] += 1
    prefix = hashlib.md5(company_id.encode()).hexdigest()[:4].upper()
    return f"TKT-{prefix}-{TICKET_COUNTER[company_id]:04d}"


class SupportHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/health':
            self._send(200, {'status': 'healthy', 'server': 'Support8-EC2', 'uptime': time.time()})
        elif self.path == '/stats':
            self._send(200, {
                'total_companies': len(TICKET_COUNTER),
                'total_tickets': sum(TICKET_COUNTER.values()),
                'tickets_per_company': {k: v for k, v in TICKET_COUNTER.items()}
            })
        else:
            self._send(404, {'error': 'Not found'})

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}

        if self.path == '/process':
            self._handle_process(body)
        else:
            self._send(404, {'error': 'Not found'})

    def _handle_process(self, body):
        company_id = body.get('company_id')
        message = body.get('message', '')
        priority = body.get('priority', 'normal')
        message_id = body.get('message_id', '')

        if not company_id:
            self._send(400, {'error': 'company_id is required'})
            return

        category = categorize_message(message)
        ticket_number = generate_ticket_number(company_id)
        auto_response = AUTO_RESPONSES.get(priority, AUTO_RESPONSES['normal'])

        self._send(200, {
            'status': 'processed',
            'ticket_number': ticket_number,
            'category': category,
            'response': auto_response,
            'processed_at': int(time.time()),
            'company_id': company_id,
            'message_id': message_id
        })

    def _send(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}")


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 5000), SupportHandler)
    print("Support8 EC2 Server running on port 5000")
    server.serve_forever()
