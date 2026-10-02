"""Builds reply emails and sends them over SMTP, or writes them to the outbox folder when SMTP isn't set up."""
import html
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid, formatdate


GREETING = re.compile(r"^\s*(hi|hello|hey|dear|good (morning|afternoon|evening))\b", re.I)


def build_reply(config, message, reply_body, thread_url):
    first = (message["name"] or "there").split()[0]
    subject = f"Re: {message['topic'] or 'Your message'} — Nyon Derma"
    # Only greet if the team member didn't start with their own greeting.
    greeting = "" if GREETING.match(reply_body) else f"Hi {first},\n\n"
    text = (
        f"{greeting}{reply_body}\n\n"
        f"View the conversation and reply here:\n{thread_url}\n\n"
        "Nyon Derma\n+233 55 849 8657\n\n"
        f"---\nYou wrote:\n{message['body']}\n"
    )
    paragraphs = "".join(f"<p style=\"margin:0 0 14px\">{html.escape(p).replace(chr(10), '<br>')}</p>" for p in reply_body.split("\n\n") if p.strip())
    body_html = f"""<!doctype html><html><body style="margin:0;background:#f4f9f8;font-family:Arial,Helvetica,sans-serif;color:#23262b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:14px">
<tr><td style="padding:28px 28px 8px;font-size:20px;font-weight:bold;color:#0b4f56">Nyon Derma</td></tr>
<tr><td style="padding:8px 28px 0;font-size:15px;line-height:1.6">
{f'<p style="margin:0 0 14px">Hi {html.escape(first)},</p>' if greeting else ''}{paragraphs}
<p style="margin:22px 0"><a href="{html.escape(thread_url)}" style="background:#0099aa;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:999px;display:inline-block">View and reply</a></p>
</td></tr>
<tr><td style="padding:0 28px 26px;font-size:13px;color:#6d747c;line-height:1.5;border-top:1px solid #eaf4f3">
<p style="margin:16px 0 6px">You wrote:</p><p style="margin:0">{html.escape(message['body']).replace(chr(10), '<br>')}</p></td></tr>
</table></td></tr></table></body></html>"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.mail_from
    msg["To"] = message["email"]
    if config.reply_to:
        msg["Reply-To"] = config.reply_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="nyonderma.com")
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    return msg


def deliver(config, msg):
    """Returns (delivery, error). delivery is 'sent', 'outbox' or 'failed'."""
    if not config.email_enabled:
        os.makedirs(config.outbox_dir, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".txt"
        with open(os.path.join(config.outbox_dir, name), "w", encoding="utf-8") as f:
            f.write(_readable(msg))
        return "outbox", ""
    try:
        if config.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=ssl.create_default_context(), timeout=20)
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20)
            if config.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
        with server:
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            server.send_message(msg)
        return "sent", ""
    except (OSError, smtplib.SMTPException) as e:
        return "failed", str(e)[:300]


def _readable(msg):
    """Headers plus both bodies as plain text, so outbox files are easy to check by eye."""
    head = "".join(f"{k}: {v}\n" for k, v in msg.items())
    parts = [p.get_content() for p in msg.iter_parts()]
    return head + "\n" + "\n\n----- HTML -----\n\n".join(parts)
