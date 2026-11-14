"""
Viavios transactional email: templates + delivery.

Every email the app sends is rendered here, recorded in the EmailOutbox
table by main.py, and delivered through one of two transports:

- SMTP, when SMTP_HOST, SMTP_USER and SMTP_PASS are set in the environment
  (any SMTP provider works — Gmail with an app password, Resend, SES, ...).
  FROM_EMAIL sets the From header; SMTP_PORT defaults to 587 and
  SMTP_USE_TLS defaults to on (set it to 0 only for a local test sink).
- Outbox-only, when no SMTP is configured: the email is still generated and
  stored with status "stored", visible to the user in their account's email
  history. Nothing is silently dropped; connecting a sender later is purely
  an environment change, no code change.

Delivery failures never raise into the calling request — an email problem
must never break a signup, a checkout, or an account change.
"""
import os, smtplib
from email.message import EmailMessage

BRAND = "Viavios"
TAGLINE = "The way of life — your memoir, legacy book, chronicle, or testament, in your own words."


def _shell(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#FAF6EE;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FAF6EE;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#FFFDF8;border:1px solid #E3D5B8;border-radius:10px;overflow:hidden;">
<tr><td style="background:#2F4A3C;padding:20px 28px;">
<span style="font-family:Georgia,'Times New Roman',serif;font-size:26px;letter-spacing:2px;color:#E7C877;">VIAVIOS</span>
</td></tr>
<tr><td style="padding:28px;font-family:Georgia,'Times New Roman',serif;color:#2B2118;font-size:16px;line-height:1.6;">
<h1 style="font-size:22px;margin:0 0 14px 0;color:#2F4A3C;">{title}</h1>
{body_html}
</td></tr>
<tr><td style="padding:18px 28px;border-top:1px solid #E3D5B8;font-family:Georgia,serif;font-size:12px;color:#8a7a5f;">
{BRAND} — {TAGLINE}<br/>You are receiving this because you have a {BRAND} account.
</td></tr>
</table>
</td></tr></table>
</body></html>"""


def _p(text: str) -> str:
    return f"<p style=\"margin:0 0 12px 0;\">{text}</p>"


def render_email(kind: str, ctx: dict):
    """Return (subject, text, html) for an email kind. ctx carries the facts."""
    name = ctx.get("name") or "friend"
    first = name.split()[0] if name else "friend"

    if kind == "welcome":
        subject = f"Welcome to {BRAND}, {first}"
        text = (f"Dear {name},\n\n"
                f"Welcome to {BRAND}. This is where your life becomes a book — a memoir, a legacy book, "
                f"a chronicle, or a testament — written, photographed, or spoken in your own way.\n\n"
                f"Your account is ready. When you are, start your first book and write the first page. "
                f"There is no deadline and no audience unless you choose one.\n\n"
                f"With warmth,\nThe {BRAND} team")
        html = _shell(f"Welcome to {BRAND}, {first}",
                      _p(f"Dear {name},") +
                      _p("This is where your life becomes a book — a memoir, a legacy book, a chronicle, "
                         "or a testament — written, photographed, or spoken in your own way.") +
                      _p("Your account is ready. When you are, start your first book and write the first page. "
                         "There is no deadline, and no audience unless you choose one.") +
                      _p("With warmth,<br/>The Viavios team"))
        return subject, text, html

    if kind == "next_steps":
        subject = f"Your first steps in {BRAND}"
        steps = [
            ("Start your book", "Choose the kind — Memoir, Legacy, Chronicle, Testament, or a Photo Story told in pictures."),
            ("Add a little at a time", "A chapter, a photograph, a voice note, a letter. Ten minutes counts."),
            ("Bring your family in", "Share privately with the people the story is for — only they can read it."),
            ("Keep it, print it, pass it on", "Read it in the app, export it, print it as a real book, or leave it as a testament."),
        ]
        text_steps = "\n".join(f"{i+1}. {t} — {d}" for i, (t, d) in enumerate(steps))
        text = (f"Dear {name},\n\nHere is how most people begin:\n\n{text_steps}\n\n"
                f"One page today is a book someday.\n\nThe {BRAND} team")
        html_steps = "".join(
            f"<p style=\"margin:0 0 10px 0;\"><strong style=\"color:#6E2434;\">{i+1}. {t}.</strong> {d}</p>"
            for i, (t, d) in enumerate(steps))
        html = _shell("Your first steps",
                      _p(f"Dear {name},") + _p("Here is how most people begin:") + html_steps +
                      _p("One page today is a book someday."))
        return subject, text, html

    if kind == "payment_receipt":
        plan_name = ctx.get("plan_name", "Viavios plan")
        price = ctx.get("price", "")
        when = ctx.get("date", "")
        simulated = ctx.get("simulated", False)
        subject = f"Your {BRAND} receipt — {plan_name}"
        demo_note_text = "\nNote: this was a demonstration checkout — no card was charged.\n" if simulated else ""
        demo_note_html = _p("<em>Note: this was a demonstration checkout — no card was charged.</em>") if simulated else ""
        text = (f"Dear {name},\n\nThank you. Here is your receipt.\n\n"
                f"Plan: {plan_name}\nAmount: {price}\nDate: {when}\n"
                f"{demo_note_text}\nYour plan is active on your account now.\n\nThe {BRAND} team")
        html = _shell("Your receipt",
                      _p(f"Dear {name},") + _p("Thank you. Here is your receipt.") +
                      f"<p style=\"margin:0 0 12px 0;\"><strong>Plan:</strong> {plan_name}<br/>"
                      f"<strong>Amount:</strong> {price}<br/><strong>Date:</strong> {when}</p>" +
                      demo_note_html + _p("Your plan is active on your account now."))
        return subject, text, html

    if kind == "account_updated":
        changes = ctx.get("changes", "your account details")
        subject = f"Your {BRAND} account was updated"
        text = (f"Dear {name},\n\nThis confirms a change to your {BRAND} account: {changes}.\n\n"
                f"If this was you, no action is needed. If it was not you, sign in and change your "
                f"password right away, and contact us.\n\nThe {BRAND} team")
        html = _shell("Account updated",
                      _p(f"Dear {name},") +
                      _p(f"This confirms a change to your account: <strong>{changes}</strong>.") +
                      _p("If this was you, no action is needed. If it was not you, sign in and change "
                         "your password right away, and contact us."))
        return subject, text, html

    if kind == "account_cancelled":
        subject = f"Your {BRAND} account has been closed"
        text = (f"Dear {name},\n\nYour {BRAND} account has been closed, as requested. Your books, "
                f"chapters, photos, and letters have been deleted.\n\nIf you ever want to begin again, "
                f"you are welcome back — a life story is never really finished.\n\nWith thanks for the time you spent with us,\nThe {BRAND} team")
        html = _shell("Account closed",
                      _p(f"Dear {name},") +
                      _p("Your account has been closed, as requested. Your books, chapters, photos, "
                         "and letters have been deleted.") +
                      _p("If you ever want to begin again, you are welcome back — a life story is "
                         "never really finished.") +
                      _p("With thanks for the time you spent with us,<br/>The Viavios team"))
        return subject, text, html

    if kind == "app_update":
        subject = ctx.get("subject") or f"News from {BRAND}"
        message = ctx.get("message", "")
        text = f"Dear {name},\n\n{message}\n\nThe {BRAND} team"
        html = _shell(subject, _p(f"Dear {name},") + _p(message.replace("\n", "<br/>")))
        return subject, text, html

    raise ValueError(f"Unknown email kind: {kind}")


def smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"))


def deliver(to_email: str, subject: str, text: str, html: str):
    """Deliver one email. Returns (status, error): status is 'sent' when an
    SMTP server accepted it, 'stored' when no sender is configured (outbox
    only), or 'failed' with a short error string."""
    if not smtp_configured():
        return "stored", None
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    sender = os.environ.get("FROM_EMAIL", f"{BRAND} <{user}>")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            if os.environ.get("SMTP_USE_TLS", "1") != "0":
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return "sent", None
    except Exception as e:  # delivery must never break the caller's request
        return "failed", str(e)[:300]
