"""JSON API for the contact form, the admin inbox and the customer's private conversation page.

Each handler takes (app, request) and returns (status, body_dict). `request` carries parsed JSON,
query params, the client IP and whether the caller has an admin session.
"""
import re
from dataclasses import dataclass, field

from . import mailer
from .store import STATUSES, split_contact

LIMITS = {"name": 100, "topic": 60, "message": 5000, "reply": 5000}


@dataclass
class Request:
    method: str
    path: str
    query: dict
    json: dict
    ip: str
    is_admin: bool = False
    params: dict = field(default_factory=dict)


def _text(value, limit):
    return str(value or "").strip()[:limit]


def thread_url(app, message):
    return f"{app.config.site_url}/message.html?t={message['token']}"


def public_message(m):
    """What the customer sees on their conversation page: no contact details, no internal fields."""
    return {"name": m["name"].split()[0] if m["name"] else "", "topic": m["topic"], "body": m["body"], "status": m["status"], "created_at": m["created_at"]}


def admin_message(m):
    return {k: v for k, v in m.items() if k != "token"}


# ---------------- public ----------------
def submit_message(app, req):
    if not app.allow(req.ip, "submit"):
        return 429, {"error": "Too many messages. Please wait a minute and try again."}
    name = _text(req.json.get("name"), LIMITS["name"])
    contact = _text(req.json.get("contact"), 120)
    topic = _text(req.json.get("topic"), LIMITS["topic"])
    body = _text(req.json.get("message"), LIMITS["message"])
    email, phone = split_contact(contact)
    errors = {}
    if len(name) < 2:
        errors["name"] = "Enter your name."
    if not email and len(re.sub(r"\D", "", phone)) < 9:
        errors["contact"] = "Enter a valid email address or phone number."
    if len(body) < 3:
        errors["message"] = "Write a short message."
    if errors:
        return 400, {"errors": errors}
    mid = app.store.create_message(name, contact, topic, body)
    return 201, {"ok": True, "id": mid}


def get_thread(app, req):
    m = app.store.get_by_token(req.query.get("t", ""))
    if not m:
        return 404, {"error": "This conversation link isn't valid."}
    replies = [{"author": r["author"], "body": r["body"], "created_at": r["created_at"]} for r in app.store.replies(m["id"])]
    return 200, {"message": public_message(m), "replies": replies}


def customer_reply(app, req):
    if not app.allow(req.ip, "submit"):
        return 429, {"error": "Too many messages. Please wait a minute and try again."}
    m = app.store.get_by_token(req.query.get("t", ""))
    if not m:
        return 404, {"error": "This conversation link isn't valid."}
    body = _text(req.json.get("body"), LIMITS["reply"])
    if len(body) < 2:
        return 400, {"errors": {"body": "Write a reply before sending."}}
    reply = app.store.add_reply(m["id"], "customer", body)
    return 201, {"reply": {"author": "customer", "body": reply["body"], "created_at": reply["created_at"]}}


# ---------------- admin ----------------
def login(app, req):
    if not app.allow(req.ip, "login", per_minute=10):
        return 429, {"error": "Too many attempts. Wait a minute and try again."}
    if not app.check_password(str(req.json.get("password", ""))):
        return 401, {"error": "That password isn't right."}
    return 200, {"ok": True, "_session": app.new_session()}


def logout(app, req):
    return 200, {"ok": True, "_end_session": True}


def session(app, req):
    return 200, {"ok": True, "email_enabled": app.config.email_enabled}


def list_messages(app, req):
    return 200, {"messages": [admin_message(m) for m in app.store.list_messages()], "email_enabled": app.config.email_enabled}


def _message_or_404(app, req):
    try:
        return app.store.get_message(int(req.params["id"]))
    except (KeyError, ValueError):
        return None


def get_message(app, req):
    m = _message_or_404(app, req)
    if not m:
        return 404, {"error": "Message not found."}
    return 200, {"message": admin_message(m), "replies": app.store.replies(m["id"]), "thread_url": thread_url(app, m)}


def reply(app, req):
    m = _message_or_404(app, req)
    if not m:
        return 404, {"error": "Message not found."}
    body = _text(req.json.get("body"), LIMITS["reply"])
    if len(body) < 2:
        return 400, {"errors": {"body": "Write a reply before sending."}}
    url = thread_url(app, m)
    if not m["email"]:
        saved = app.store.add_reply(m["id"], "staff", body, delivery="no_email")
        return 201, {"reply": saved, "thread_url": url}
    saved = app.store.add_reply(m["id"], "staff", body, delivery="sending")
    delivery, error = mailer.deliver(app.config, mailer.build_reply(app.config, m, body, url))
    app.store.update_delivery(saved["id"], delivery, error)
    saved.update(delivery=delivery, error=error)
    return 201, {"reply": saved, "thread_url": url}


def set_status(app, req):
    m = _message_or_404(app, req)
    if not m:
        return 404, {"error": "Message not found."}
    status = req.json.get("status")
    if status not in STATUSES:
        return 400, {"error": f"Status must be one of: {', '.join(STATUSES)}."}
    app.store.set_status(m["id"], status)
    return 200, {"ok": True}


# (method, pattern, handler, admin_only)
ROUTES = [
    ("POST", r"^/api/messages$", submit_message, False),
    ("GET", r"^/api/thread$", get_thread, False),
    ("POST", r"^/api/thread/reply$", customer_reply, False),
    ("POST", r"^/api/admin/login$", login, False),
    ("POST", r"^/api/admin/logout$", logout, False),
    ("GET", r"^/api/admin/session$", session, True),
    ("GET", r"^/api/admin/messages$", list_messages, True),
    ("GET", r"^/api/admin/messages/(?P<id>\d+)$", get_message, True),
    ("POST", r"^/api/admin/messages/(?P<id>\d+)/reply$", reply, True),
    ("POST", r"^/api/admin/messages/(?P<id>\d+)/status$", set_status, True),
]
