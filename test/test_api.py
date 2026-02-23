#!/usr/bin/env python3
"""
Support8 API End-to-End Test
Tests signup, login, token generation, message sending, and API token auth.
Uses henryoverbeeke@gmail.com as the test account.
"""

import requests
import json
import sys
import time

API_BASE = "https://mfvollvrkc.execute-api.us-east-2.amazonaws.com/prod"

EMAIL = "henryoverbeeke@gmail.com"
PASSWORD = "Test1234"
COMPANY = "Henry's Company"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    print(f"\n{CYAN}{BOLD}TEST: {name}{RESET}")
    try:
        result = fn()
        if result:
            print(f"  {GREEN}PASSED{RESET}")
            passed += 1
        else:
            print(f"  {RED}FAILED{RESET}")
            failed += 1
    except Exception as e:
        print(f"  {RED}FAILED: {e}{RESET}")
        failed += 1


def post(path, data=None, headers=None):
    r = requests.post(f"{API_BASE}{path}", json=data, headers=headers or {})
    body = r.json()
    print(f"  {YELLOW}POST {path} -> {r.status_code}{RESET}")
    print(f"  {json.dumps(body, indent=2)[:300]}")
    return r.status_code, body


def get(path, headers=None):
    r = requests.get(f"{API_BASE}{path}", headers=headers or {})
    body = r.json()
    print(f"  {YELLOW}GET {path} -> {r.status_code}{RESET}")
    print(f"  {json.dumps(body, indent=2)[:300]}")
    return r.status_code, body


print(f"\n{'='*60}")
print(f"{BOLD}Support8 API Test Suite{RESET}")
print(f"API: {API_BASE}")
print(f"Account: {EMAIL}")
print(f"{'='*60}")


# --- Test 1: Sign Up ---
access_token = None
api_token = None

def test_signup():
    code, body = post("/auth/signup", {
        "email": EMAIL,
        "password": PASSWORD,
        "company_name": COMPANY
    })
    return code == 200 or "already exists" in body.get("error", "")

test("Sign Up", test_signup)


# --- Test 2: Login ---
def test_login():
    global access_token
    code, body = post("/auth/login", {"email": EMAIL, "password": PASSWORD})
    if code == 200 and body.get("access_token"):
        access_token = body["access_token"]
        return True
    return False

test("Login", test_login)


# --- Test 3: Get Company Info ---
def test_company():
    code, body = get("/company", {"Authorization": f"Bearer {access_token}"})
    return code == 200 and body.get("company_id") == EMAIL

test("Get Company Info", test_company)


# --- Test 4: Generate API Token ---
def test_gen_token():
    global api_token
    code, body = post("/token/generate", headers={"Authorization": f"Bearer {access_token}"})
    if code == 200 and body.get("api_token"):
        api_token = body["api_token"]
        return True
    return False

test("Generate API Token", test_gen_token)


# --- Test 5: Get API Token ---
def test_get_token():
    code, body = get("/token", {"Authorization": f"Bearer {access_token}"})
    return code == 200 and body.get("api_token")

test("Get API Token", test_get_token)


# --- Test 6: Send Message via Bearer Auth ---
def test_send_bearer():
    code, body = post("/support/message", {
        "subject": "Test Ticket via Bearer",
        "message": "I have a billing issue with my subscription payment",
        "priority": "high"
    }, {"Authorization": f"Bearer {access_token}"})
    return code == 200 and body.get("message_id") and body.get("ticket_number")

test("Send Message (Bearer Auth)", test_send_bearer)


# --- Test 7: Send Message via API Token ---
def test_send_api_token():
    code, body = post("/support/message", {
        "subject": "Test Ticket via API Token",
        "message": "There is a technical error crashing my application",
        "priority": "normal"
    }, {"X-Api-Token": api_token})
    return code == 200 and body.get("message_id") and body.get("category") == "technical"

test("Send Message (API Token Auth)", test_send_api_token)


# --- Test 8: Get Messages (should have 2) ---
def test_get_messages():
    code, body = get("/support/messages", {"Authorization": f"Bearer {access_token}"})
    return code == 200 and body.get("count", 0) >= 2

test("Get Messages (should have >= 2)", test_get_messages)


# --- Test 9: Get Messages via API Token ---
def test_get_messages_api():
    code, body = get("/support/messages", {"X-Api-Token": api_token})
    return code == 200 and body.get("count", 0) >= 2

test("Get Messages via API Token", test_get_messages_api)


# --- Test 10: Unauthorized request ---
def test_unauthorized():
    code, body = get("/support/messages")
    return code == 401

test("Unauthorized Request Rejected", test_unauthorized)


# --- Test 11: Company isolation (different token shouldn't see messages) ---
def test_isolation():
    code, body = get("/support/messages", {"X-Api-Token": "fake-token-12345"})
    return code == 401

test("Company Isolation (fake token rejected)", test_isolation)


# --- Summary ---
print(f"\n{'='*60}")
total = passed + failed
print(f"{BOLD}Results: {passed}/{total} passed{RESET}")
if failed:
    print(f"{RED}{failed} test(s) failed{RESET}")
else:
    print(f"{GREEN}All tests passed!{RESET}")
print(f"{'='*60}")

if api_token:
    print(f"\n{CYAN}Your API Token:{RESET} {api_token}")
    print(f"{CYAN}Use it like:{RESET}")
    print(f'  curl {API_BASE}/support/messages -H "X-Api-Token: {api_token}"')

sys.exit(1 if failed else 0)
