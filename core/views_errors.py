"""Nexora — branded error handlers (400/403/404/429/500 + CSRF)."""
import logging

from django.shortcuts import render

logger = logging.getLogger(__name__)


def page_not_found(request, exception):
    return render(request, "errors/404.html", status=404)


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def bad_request(request, exception=None):
    return render(request, "errors/400.html", status=400)


def server_error(request):
    return render(request, "errors/500.html", status=500)


def csrf_failure(request, reason=""):
    logger.warning("Rejected request with invalid CSRF token: %s", reason)
    return render(request, "errors/403.html", {"reason": reason}, status=403)
