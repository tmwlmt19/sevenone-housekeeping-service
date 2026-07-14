"""Transactional email.

The provider (Resend today) sits behind this module so swapping it later is a
one-file change. When `resend_api_key` is unset the send is a logged no-op, so
dev/test never hit the network — only prod with a real key delivers mail.
"""
import logging

from anyio import to_thread

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _text_body(reset_url: str, ttl_minutes: int) -> str:
    return (
        "You (or someone using your email) asked to reset your SevenOne "
        "password.\n\n"
        f"Open this link to choose a new password (expires in {ttl_minutes} "
        f"minutes):\n{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email — your "
        "password won't change."
    )


def _html_body(reset_url: str, ttl_minutes: int) -> str:
    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        'line-height:1.5;color:#111">'
        "<h2>Reset your SevenOne password</h2>"
        "<p>You (or someone using your email) asked to reset your SevenOne "
        "password.</p>"
        f'<p><a href="{reset_url}" style="display:inline-block;padding:10px '
        '16px;background:#111;color:#fff;border-radius:6px;'
        'text-decoration:none">Choose a new password</a></p>'
        f"<p>This link expires in {ttl_minutes} minutes.</p>"
        "<p style=\"color:#666;font-size:13px\">If you didn't request this, "
        "you can safely ignore this email — your password won't change.</p>"
        "</div>"
    )


async def send_password_reset_email(*, to: str, reset_url: str) -> None:
    """Send the password-reset link. No-op (logged) when no provider is set."""
    ttl = settings.password_reset_token_ttl_minutes
    if not settings.resend_api_key:
        logger.info(
            "Email disabled (no RESEND_API_KEY set); would send reset link "
            "to %s: %s",
            to,
            reset_url,
        )
        return

    # Imported lazily so the SDK isn't required in dev/test environments.
    import resend

    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.email_from,
        "to": [to],
        "subject": "Reset your SevenOne password",
        "html": _html_body(reset_url, ttl),
        "text": _text_body(reset_url, ttl),
    }
    # The Resend SDK is synchronous; run it off the event loop.
    await to_thread.run_sync(lambda: resend.Emails.send(params))
