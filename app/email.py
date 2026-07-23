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


def _welcome_text_body(
    *, name: str, email: str, temp_password: str, login_url: str
) -> str:
    return (
        f"Hi {name},\n\n"
        "An account has been created for you on SevenOne Housekeeping.\n\n"
        f"Sign in here: {login_url}\n"
        f"Email: {email}\n"
        f"Temporary password: {temp_password}\n\n"
        "For your security you'll be asked to choose a new password the first "
        "time you sign in.\n"
    )


def _welcome_html_body(
    *, name: str, email: str, temp_password: str, login_url: str
) -> str:
    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        'line-height:1.5;color:#111">'
        f"<h2>Welcome to SevenOne, {name}</h2>"
        "<p>An account has been created for you on SevenOne Housekeeping. "
        "Use the temporary password below to sign in.</p>"
        '<p style="margin:16px 0;padding:12px 16px;background:#f4f4f5;'
        'border-radius:6px">'
        f"<strong>Email:</strong> {email}<br>"
        f"<strong>Temporary password:</strong> "
        f'<code style="font-size:15px">{temp_password}</code></p>'
        f'<p><a href="{login_url}" style="display:inline-block;padding:10px '
        '16px;background:#111;color:#fff;border-radius:6px;'
        'text-decoration:none">Sign in to SevenOne</a></p>'
        '<p style="color:#666;font-size:13px">For your security you\'ll be '
        "asked to choose a new password the first time you sign in.</p>"
        "</div>"
    )


async def send_welcome_email(
    *, to: str, name: str, temp_password: str
) -> None:
    """Send a new user their temporary password + sign-in link. No-op (logged)
    when no provider is set. Raises on provider failure; callers that create
    users should treat delivery as best-effort so a mail hiccup never rolls back
    or fails the account creation itself."""
    login_url = settings.login_url
    if not settings.resend_api_key:
        logger.info(
            "Email disabled (no RESEND_API_KEY set); would send welcome email "
            "to %s (%s)",
            to,
            name,
        )
        return

    # Imported lazily so the SDK isn't required in dev/test environments.
    import resend

    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.email_from,
        "to": [to],
        "subject": "Welcome to SevenOne — your account is ready",
        "html": _welcome_html_body(
            name=name, email=to, temp_password=temp_password, login_url=login_url
        ),
        "text": _welcome_text_body(
            name=name, email=to, temp_password=temp_password, login_url=login_url
        ),
    }
    # The Resend SDK is synchronous; run it off the event loop.
    await to_thread.run_sync(lambda: resend.Emails.send(params))


async def send_welcome_email_best_effort(
    *, to: str, name: str, temp_password: str
) -> None:
    """Send a welcome email, swallowing (and logging) any provider error. The
    user already exists by the time we get here, so a delivery failure must not
    surface to the caller — it would wrongly imply the account wasn't created."""
    try:
        await send_welcome_email(to=to, name=name, temp_password=temp_password)
    except Exception:  # noqa: BLE001 - delivery is best-effort
        logger.exception("Failed to send welcome email to %s", to)


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
