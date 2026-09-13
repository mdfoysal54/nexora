"""Canonical security test-suite — identical for every flagship project.

Covers: security headers + CSP nonce, CSRF presence on forms, registration,
login flow and brute-force throttling on the login endpoint.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .middleware import reset_throttle


class SecurityHeaderTests(TestCase):
    def setUp(self):
        reset_throttle()

    def test_csp_and_hardening_headers_present(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self' 'nonce-", csp)      # nonce minted per request
        self.assertIn("style-src 'self' 'nonce-", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertEqual(response.headers.get("Referrer-Policy"), "same-origin")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")

    def test_csp_nonce_unique_per_request(self):
        r1 = self.client.get(reverse("login")).headers["Content-Security-Policy"]
        r2 = self.client.get(reverse("login")).headers["Content-Security-Policy"]
        self.assertNotEqual(r1, r2)

    def test_login_form_has_csrf_token(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_admin_keeps_usable_csp(self):
        response = self.client.get("/admin/login/")
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("'unsafe-inline'", csp)   # admin widgets require it


class RegistrationTests(TestCase):
    def setUp(self):
        reset_throttle()

    def test_register_then_login_redirects_home(self):
        response = self.client.post(reverse("register"), {
            "username": "alice",
            "email": "alice@example.com",
            "password1": "Str0ng!Passw0rd",
            "password2": "Str0ng!Passw0rd",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.count(), 1)
        self.assertIn("_auth_user_id", self.client.session)

    def test_duplicate_email_rejected(self):
        User.objects.create_user("bob", email="bob@example.com", password="x-Passw0rd!")
        response = self.client.post(reverse("register"), {
            "username": "bob2",
            "email": "bob@example.com",
            "password1": "Str0ng!Passw0rd",
            "password2": "Str0ng!Passw0rd",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_weak_password_rejected(self):
        response = self.client.post(reverse("register"), {
            "username": "carol",
            "email": "carol@example.com",
            "password1": "password",
            "password2": "password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)


class LoginThrottleTests(TestCase):
    def setUp(self):
        reset_throttle()
        self.password = "Str0ng!Passw0rd"
        User.objects.create_user("mallory", email="m@example.com", password=self.password)
        self.login_url = reverse("login")

    def _post_login(self, username, password):
        return self.client.post(self.login_url, {"username": username, "password": password})

    def test_allows_max_attempts_then_blocks(self):
        for _ in range(5):
            response = self._post_login("mallory", "wrong-pass")
            self.assertEqual(response.status_code, 200)     # form re-rendered
        response = self._post_login("mallory", "wrong-pass")
        self.assertEqual(response.status_code, 429)         # throttled
        self.assertContains(response, "Too many", status_code=429)

    def test_correct_password_also_blocked_while_throttled(self):
        for _ in range(6):
            self._post_login("mallory", "wrong-pass")
        response = self._post_login("mallory", self.password)
        self.assertEqual(response.status_code, 429)

    @override_settings(AUTH_LOGIN_MAX_ATTEMPTS=2)
    def test_brute_force_keyed_per_username_and_ip(self):
        # Keys are (ip, ...) AND (username, ...) — blocking on either one.
        # This means a username-rotation attack from one IP still runs out of
        # attempts (the shared IP budget), while a fresh IP gets its own run.
        User.objects.create_user("eve", email="eve@example.com", password=self.password)
        User.objects.create_user("frank", email="frank@example.com", password=self.password)

        # mallory exhausts both budgets from this IP (2 wrong attempts).
        self.assertEqual(self._post_login("mallory", "wrong").status_code, 200)
        self.assertEqual(self._post_login("mallory", "wrong").status_code, 200)
        # Username budget spent -> blocked.
        self.assertEqual(self._post_login("mallory", "wrong").status_code, 429)
        # eve on the SAME IP is blocked too (shared per-IP budget, by design:
        # stops an attacker rotating usernames from one machine).
        self.assertEqual(self._post_login("eve", "wrong").status_code, 429)

        # frank from a DIFFERENT IP has clean budgets -> gets his own 2 tries.
        fresh_ip_client = self.client_class(HTTP_X_FORWARDED_FOR="203.0.113.77")
        response = fresh_ip_client.post(
            self.login_url, {"username": "frank", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        response = fresh_ip_client.post(
            self.login_url, {"username": "frank", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        response = fresh_ip_client.post(
            self.login_url, {"username": "frank", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 429)

    def test_successful_login_resets_throttle(self):
        for _ in range(6):
            self._post_login("mallory", "wrong-pass")
        reset_throttle()
        response = self._post_login("mallory", self.password)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
