"""Nexora — hardening middleware.

1. SecurityHeadersMiddleware
   Adds a strict Content-Security-Policy with a fresh per-request nonce
   (usable in templates as {{ csp_nonce }}), plus Referrer-Policy and
   Permissions-Policy headers. The Django admin keeps its own slightly more
   permissive policy so its inline widgets keep working.
2. LoginThrottleMiddleware
   Sliding-window brute-force protection on the login form, keyed by both
   remote IP *and* submitted username. Successful logins reset the counters.
"""
from __future__ import annotations

import secrets
import threading
import time

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import Resolver404, resolve


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


class SecurityHeadersMiddleware:
    """Append security headers to every response and mint a CSP nonce."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(18)
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            nonce = request.csp_nonce
            if request.path.startswith("/admin"):
                policy = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; font-src 'self' data:; "
                    "frame-ancestors 'none'; object-src 'none'; "
                    "base-uri 'self'; form-action 'self'"
                )
            else:
                policy = (
                    "default-src 'self'; "
                    "script-src 'self' 'nonce-%s'; "
                    "style-src 'self' 'nonce-%s'; "
                    "img-src 'self' data:; font-src 'self'; "
                    "frame-ancestors 'none'; object-src 'none'; "
                    "base-uri 'self'; form-action 'self'"
                ) % (nonce, nonce)
                if not settings.DEBUG:
                    policy += "; upgrade-insecure-requests"
            response["Content-Security-Policy"] = policy
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response


def site_processor(request):
    """Context processor: expose app metadata + CSP nonce to templates."""
    ctx = {
        "APP_NAME": settings.APP_NAME,
        "APP_TAGLINE": settings.APP_TAGLINE,
        "csp_nonce": getattr(request, "csp_nonce", ""),
        "ui_theme": "void",
        "ui_lang": "en",
        "nav": [],
    }
    try:
        from .models import Company, Profile
        company = Company.get()
        ctx["company"] = company
        ctx["ui_theme"] = company.theme or "void"
        ctx["ui_lang"] = company.language or "en"
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            profile = Profile.objects.filter(user=user).first()
            if profile:
                ctx["ui_theme"] = profile.theme or ctx["ui_theme"]
                ctx["ui_lang"] = profile.language or ctx["ui_lang"]
    except Exception:
        ctx["company"] = None
    return ctx


# ------------------------------------------------------------------ throttling
_ATTEMPTS = {}          # key -> [timestamps]
_LOCK = threading.Lock()


def _prune(key: tuple):
    window = settings.AUTH_LOGIN_WINDOW_SECONDS
    cutoff = time.monotonic() - window
    stamps = _ATTEMPTS.get(key, [])
    _ATTEMPTS[key] = [t for t in stamps if t > cutoff]


def _blocked(key: tuple) -> bool:
    with _LOCK:
        _prune(key)
        return len(_ATTEMPTS.get(key, [])) >= settings.AUTH_LOGIN_MAX_ATTEMPTS


def _record(key: tuple) -> None:
    with _LOCK:
        _prune(key)
        _ATTEMPTS.setdefault(key, []).append(time.monotonic())


def reset_throttle() -> None:
    """Test helper / manual reset."""
    with _LOCK:
        _ATTEMPTS.clear()


def _clear(key: tuple) -> None:
    with _LOCK:
        _ATTEMPTS.pop(key, None)


@user_logged_in.connect
def _on_login_success(sender, request, user, **kwargs):
    ip = _client_ip(request)
    _clear(("ip", ip))
    _clear(("user", getattr(user, "username", "").lower()))


class LoginThrottleMiddleware:
    """429 responses after N failed login attempts (per IP and per username)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST":
            try:
                match = resolve(request.path)
            except Resolver404:
                match = None
            if match is not None and match.url_name == "login":
                username = request.POST.get("username", "").lower()
                keys = [("ip", _client_ip(request))]
                if username:
                    keys.append(("user", username))
                if any(_blocked(k) for k in keys):
                    attempts = settings.AUTH_LOGIN_MAX_ATTEMPTS
                    window = settings.AUTH_LOGIN_WINDOW_SECONDS
                    body = render_to_string(
                        "errors/429.html",
                        {"attempts": attempts, "window_seconds": window},
                        request=request,
                    )
                    return HttpResponse(body, status=429)
                for k in keys:
                    _record(k)
        return self.get_response(request)
