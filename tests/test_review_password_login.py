"""審查頁登入畫面只留密碼，驗證仍走 Supabase Auth。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs" / "review"
INDEX = (REVIEW / "index.html").read_text(encoding="utf-8")
APP = (REVIEW / "app.js").read_text(encoding="utf-8")
CONFIG = (REVIEW / "config.js").read_text(encoding="utf-8")
SETUP = (REVIEW / "SETUP.md").read_text(encoding="utf-8")
PUBLIC_HOME = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
SHARED_EMAIL = "review-team@example.com"


class _LoginControls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = []
        self.buttons = []
        self.labels = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "input":
            self.inputs.append(attr)
        elif tag == "button":
            self.buttons.append(attr)
        elif tag == "label":
            self.labels.append(attr.get("for", ""))


def _login_html():
    start = INDEX.index('<div id="loginView"')
    end = INDEX.index('<div id="appView"')
    return INDEX[start:end]


def test_login_screen_has_only_a_password_field():
    controls = _LoginControls()
    controls.feed(_login_html())
    assert len(controls.inputs) == 1
    field = controls.inputs[0]
    assert field.get("id") == "passwordInput"
    assert field.get("type") == "password"
    assert controls.labels == ["passwordInput"]
    assert [button.get("id") for button in controls.buttons] == ["loginBtn"]
    login_html = _login_html().lower()
    assert "email" not in login_html
    assert 'type="email"' not in INDEX
    assert "emailInput" not in INDEX


def test_signin_uses_config_email_and_typed_password():
    assert 'TEAM_LOGIN_EMAIL: "%s"' % SHARED_EMAIL in CONFIG
    assert "cfg.TEAM_LOGIN_EMAIL" in APP
    assert "signInWithPassword({ email: email, password: password })" in APP
    assert "emailInput" not in APP
    assert '.from("team_members")' in APP
    assert "invalid login credentials" in APP
    assert "invalid_credentials" in APP
    assert "密碼不正確" in APP


def test_review_frontend_does_not_store_a_password():
    combined = "\n".join([INDEX, APP, CONFIG])
    assert "sb_secret_" not in combined
    assert "SUPABASE_SERVICE_ROLE" not in combined
    assert re.search(
        r"(?i)(password|passwd|secret)\s*[:=]\s*['\"][^'\"]+['\"]",
        combined,
    ) is None
    assert SHARED_EMAIL in CONFIG
    assert "sb_publishable_" in CONFIG


def test_setup_explains_the_shared_account():
    assert SHARED_EMAIL in SETUP
    assert "TEAM_LOGIN_EMAIL" in SETUP
    assert "team_members" in SETUP
    assert "Auto Confirm User" in SETUP
    assert "ptt_review_answers" in SETUP


def test_public_home_is_not_a_password_gate():
    assert "研究小組入口" in PUBLIC_HOME
    assert "passwordInput" not in PUBLIC_HOME
    assert "signInWithPassword" not in PUBLIC_HOME
    assert 'href="https://ccf540123.github.io/anti-scam/review/"' in PUBLIC_HOME
