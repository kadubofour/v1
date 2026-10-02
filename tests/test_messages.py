"""Tests for the customer messages backend (contact form -> admin inbox -> email reply -> customer thread).

Run from the site folder:  python -m unittest discover -s tests -v
"""
import http.cookiejar
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import serve  # noqa: E402


class Client:
    """Tiny JSON client that keeps cookies, like a browser would."""

    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with self.opener.open(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw and r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw


class MessagesApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = serve.Config(
            admin_password="test-pass",
            data_dir=os.path.join(self.tmp, "data"),
            outbox_dir=os.path.join(self.tmp, "outbox"),
            site_url="http://shop.test",
            smtp_host="",  # not configured -> replies go to the outbox
            mail_from="Nyon Derma <hello@shop.test>",
            rate_limit_per_minute=5,
        )
        self.server = serve.make_server(0, ROOT, self.config)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.customer = Client(self.base)
        self.admin = Client(self.base)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def submit(self, client=None, **overrides):
        body = {"name": "Ama Mensah", "contact": "ama@example.com", "topic": "Product advice", "message": "Which serum suits oily skin?"}
        body.update(overrides)
        return (client or self.customer).call("POST", "/api/messages", body)

    def login(self):
        status, _ = self.admin.call("POST", "/api/admin/login", {"password": "test-pass"})
        self.assertEqual(status, 200)

    def outbox_files(self):
        d = self.config.outbox_dir
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    # ---- access control
    def test_admin_endpoints_require_login(self):
        status, _ = self.customer.call("GET", "/api/admin/messages")
        self.assertEqual(status, 401)

    def test_wrong_password_is_rejected(self):
        status, body = self.admin.call("POST", "/api/admin/login", {"password": "nope"})
        self.assertEqual(status, 401)
        status, _ = self.admin.call("GET", "/api/admin/messages")
        self.assertEqual(status, 401)

    def test_logout_ends_session(self):
        self.login()
        self.admin.call("POST", "/api/admin/logout", {})
        status, _ = self.admin.call("GET", "/api/admin/messages")
        self.assertEqual(status, 401)

    # ---- contact form
    def test_submit_validates_required_fields(self):
        status, body = self.submit(name="", contact="x", message="")
        self.assertEqual(status, 400)
        self.assertEqual(set(body["errors"]), {"name", "contact", "message"})

    def test_submitted_message_appears_in_admin_inbox(self):
        status, body = self.submit()
        self.assertEqual(status, 201)
        self.login()
        status, body = self.admin.call("GET", "/api/admin/messages")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["messages"]), 1)
        m = body["messages"][0]
        self.assertEqual(m["name"], "Ama Mensah")
        self.assertEqual(m["email"], "ama@example.com")
        self.assertEqual(m["status"], "new")
        self.assertNotIn("token", m)  # the customer's private link is never listed

    def test_phone_number_contact_is_stored_as_phone(self):
        self.submit(contact="024 111 2223")
        self.login()
        m = self.admin.call("GET", "/api/admin/messages")[1]["messages"][0]
        self.assertEqual(m["email"], "")
        self.assertEqual(m["phone"], "0241112223")

    def test_public_form_is_rate_limited(self):
        for _ in range(5):
            self.assertEqual(self.submit()[0], 201)
        self.assertEqual(self.submit()[0], 429)

    # ---- replying
    def test_reply_requires_text(self):
        self.submit()
        self.login()
        mid = self.admin.call("GET", "/api/admin/messages")[1]["messages"][0]["id"]
        status, body = self.admin.call("POST", f"/api/admin/messages/{mid}/reply", {"body": "   "})
        self.assertEqual(status, 400)

    def test_reply_goes_to_outbox_when_email_not_configured(self):
        self.submit()
        self.login()
        mid = self.admin.call("GET", "/api/admin/messages")[1]["messages"][0]["id"]
        status, body = self.admin.call("POST", f"/api/admin/messages/{mid}/reply", {"body": "Try the Ultra Posh niacinamide serum <b>daily</b>."})
        self.assertEqual(status, 201)
        self.assertEqual(body["reply"]["delivery"], "outbox")
        files = self.outbox_files()
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.config.outbox_dir, files[0]), encoding="utf-8") as f:
            eml = f.read()
        self.assertIn("To: ama@example.com", eml)
        self.assertIn("http://shop.test/message.html?t=", eml)
        self.assertIn("&lt;b&gt;daily&lt;/b&gt;", eml)  # HTML part is escaped
        status, thread = self.admin.call("GET", f"/api/admin/messages/{mid}")
        self.assertEqual(thread["message"]["status"], "replied")
        self.assertEqual(len(thread["replies"]), 1)

    def test_phone_only_reply_is_saved_but_not_emailed(self):
        self.submit(contact="0241112223")
        self.login()
        mid = self.admin.call("GET", "/api/admin/messages")[1]["messages"][0]["id"]
        status, body = self.admin.call("POST", f"/api/admin/messages/{mid}/reply", {"body": "We'll call you."})
        self.assertEqual(status, 201)
        self.assertEqual(body["reply"]["delivery"], "no_email")
        self.assertEqual(self.outbox_files(), [])
        self.assertIn("/message.html?t=", body["thread_url"])  # for sharing over WhatsApp

    # ---- customer thread
    def test_customer_can_read_and_answer_thread_with_private_link(self):
        self.submit()
        self.login()
        mid = self.admin.call("GET", "/api/admin/messages")[1]["messages"][0]["id"]
        thread_url = self.admin.call("POST", f"/api/admin/messages/{mid}/reply", {"body": "Try the serum."})[1]["thread_url"]
        token = re.search(r"t=([\w-]+)", thread_url).group(1)

        status, thread = self.customer.call("GET", f"/api/thread?t={token}")
        self.assertEqual(status, 200)
        self.assertEqual([r["author"] for r in thread["replies"]], ["staff"])
        self.assertNotIn("email", thread["message"])  # no contact details exposed on the public page

        status, _ = self.customer.call("POST", f"/api/thread/reply?t={token}", {"body": "Thanks! Is it safe in pregnancy?"})
        self.assertEqual(status, 201)
        status, admin_view = self.admin.call("GET", f"/api/admin/messages/{mid}")
        self.assertEqual(admin_view["message"]["status"], "new")  # back in the unanswered queue
        self.assertEqual([r["author"] for r in admin_view["replies"]], ["staff", "customer"])

    def test_unknown_thread_token_is_not_found(self):
        status, _ = self.customer.call("GET", "/api/thread?t=not-a-real-token")
        self.assertEqual(status, 404)

    def test_admin_can_close_and_reopen_message(self):
        self.submit()
        self.login()
        mid = self.admin.call("GET", "/api/admin/messages")[1]["messages"][0]["id"]
        self.assertEqual(self.admin.call("POST", f"/api/admin/messages/{mid}/status", {"status": "closed"})[0], 200)
        self.assertEqual(self.admin.call("GET", f"/api/admin/messages/{mid}")[1]["message"]["status"], "closed")
        self.assertEqual(self.admin.call("POST", f"/api/admin/messages/{mid}/status", {"status": "bogus"})[0], 400)

    # ---- static file safety
    def test_private_files_are_never_served(self):
        self.submit()  # makes sure the database file exists
        for path in ["/data/messages.db", "/.env", "/.env.example", "/backend/store.py", "/serve.py", "/tests/test_messages.py", "/outbox/"]:
            status, _ = self.customer.call("GET", path)
            self.assertEqual(status, 404, path)

    def test_site_pages_still_served(self):
        status, body = self.customer.call("GET", "/contact.html")
        self.assertEqual(status, 200)
        self.assertIn(b"Send us a message", body)


if __name__ == "__main__":
    unittest.main()
