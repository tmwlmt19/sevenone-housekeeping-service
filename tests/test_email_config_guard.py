"""Boot-time guard: warn when email is enabled but the link URLs baked into
welcome / password-reset emails still point at localhost (which is how the
welcome-email link once shipped dead)."""
import logging
from types import SimpleNamespace

from app.main import _warn_on_localhost_email_links


def _settings(*, resend_api_key, login_url, password_reset_url_base):
    # The guard only reads these three attributes.
    return SimpleNamespace(
        resend_api_key=resend_api_key,
        login_url=login_url,
        password_reset_url_base=password_reset_url_base,
    )


def test_warns_when_delivery_enabled_and_urls_are_localhost(caplog):
    s = _settings(
        resend_api_key="re_live",
        login_url="http://localhost:5174",
        password_reset_url_base="http://localhost:5174/reset-password",
    )
    with caplog.at_level(logging.WARNING):
        _warn_on_localhost_email_links(s)
    assert any("localhost" in r.message for r in caplog.records)
    assert any("LOGIN_URL" in r.getMessage() for r in caplog.records)


def test_silent_when_urls_are_real(caplog):
    s = _settings(
        resend_api_key="re_live",
        login_url="https://login.staging.seven1solutions.com",
        password_reset_url_base=(
            "https://login.staging.seven1solutions.com/reset-password"
        ),
    )
    with caplog.at_level(logging.WARNING):
        _warn_on_localhost_email_links(s)
    assert caplog.records == []


def test_silent_when_delivery_disabled(caplog):
    # No API key ⇒ email is a no-op ⇒ localhost URLs are harmless (dev/test).
    s = _settings(
        resend_api_key=None,
        login_url="http://localhost:5174",
        password_reset_url_base="http://localhost:5174/reset-password",
    )
    with caplog.at_level(logging.WARNING):
        _warn_on_localhost_email_links(s)
    assert caplog.records == []
