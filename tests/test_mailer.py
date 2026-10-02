"""Mailer tests with a fake SMTP connection (no real email is sent)."""
import os
import smtplib
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import mailer  # noqa: E402
from backend.config import Config  # noqa: E402

MESSAGE = {"name": "Ama Mensah", "email": "ama@example.com", "topic": "Product advice", "body": "Which serum?"}


class MailerTest(unittest.TestCase):
    def config(self, **kw):
        base = dict(smtp_host="smtp.test", smtp_port=587, smtp_user="shop@test", smtp_password="secret",
                    smtp_security="starttls", mail_from="Nyon Derma <hello@shop.test>", reply_to="care@shop.test")
        base.update(kw)
        return Config(**base)

    def test_reply_email_has_subject_recipient_and_both_parts(self):
        msg = mailer.build_reply(self.config(), MESSAGE, "Try the serum.", "https://shop.test/message.html?t=abc")
        self.assertEqual(msg["To"], "ama@example.com")
        self.assertEqual(msg["Reply-To"], "care@shop.test")
        self.assertIn("Product advice", msg["Subject"])
        types = [p.get_content_type() for p in msg.iter_parts()]
        self.assertEqual(types, ["text/plain", "text/html"])
        self.assertIn("Hi Ama", msg.get_body(("plain",)).get_content())

    def test_greeting_is_not_doubled_when_reply_already_greets(self):
        msg = mailer.build_reply(self.config(), MESSAGE, "Hi Ama,\n\nTry the serum.", "https://x")
        plain = msg.get_body(("plain",)).get_content()
        self.assertEqual(plain.count("Hi Ama"), 1)
        msg = mailer.build_reply(self.config(), MESSAGE, "Good morning Ama! Try the serum.", "https://x")
        self.assertNotIn("Hi Ama", msg.get_body(("plain",)).get_content())

    def test_sends_over_starttls_with_login(self):
        with mock.patch.object(smtplib, "SMTP") as smtp:
            conn = smtp.return_value  # smtplib.SMTP returns itself from `with`
            delivery, error = mailer.deliver(self.config(), mailer.build_reply(self.config(), MESSAGE, "Hi", "https://x"))
        self.assertEqual((delivery, error), ("sent", ""))
        smtp.assert_called_once_with("smtp.test", 587, timeout=20)
        smtp.return_value.starttls.assert_called_once()
        conn.login.assert_called_once_with("shop@test", "secret")
        conn.send_message.assert_called_once()

    def test_ssl_mode_uses_smtp_ssl(self):
        with mock.patch.object(smtplib, "SMTP_SSL") as smtp_ssl:
            delivery, _ = mailer.deliver(self.config(smtp_security="ssl", smtp_port=465), mailer.build_reply(self.config(), MESSAGE, "Hi", "https://x"))
        self.assertEqual(delivery, "sent")
        self.assertEqual(smtp_ssl.call_args[0][:2], ("smtp.test", 465))

    def test_smtp_failure_is_reported_not_raised(self):
        with mock.patch.object(smtplib, "SMTP", side_effect=smtplib.SMTPAuthenticationError(535, b"bad credentials")):
            delivery, error = mailer.deliver(self.config(), mailer.build_reply(self.config(), MESSAGE, "Hi", "https://x"))
        self.assertEqual(delivery, "failed")
        self.assertIn("bad credentials", error)


if __name__ == "__main__":
    unittest.main()
