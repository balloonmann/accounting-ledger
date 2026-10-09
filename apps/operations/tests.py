"""
Operational and deployment acceptance tests (Milestone 5).
Covers:
  - Health check endpoint behavior and failure status.
  - H01: Production configuration safeguards (rejection of wildcards, short keys, non-HTTPS origins).
"""
import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_check_returns_ok_when_database_is_healthy(self):
        """GET /health/ returns 200 with status ok."""
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_check_rejects_post(self):
        """POST /health/ is rejected with 405 Method Not Allowed."""
        response = self.client.post(reverse("health"))
        self.assertEqual(response.status_code, 405)

    @patch("django.db.connection.cursor")
    def test_health_check_returns_503_when_database_fails(self, mock_cursor):
        """GET /health/ returns 503 without leaking credentials or database names."""
        mock_cursor.side_effect = DatabaseError("Database unreachable")
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})


class H01ProductionConfigurationSafeguardsTests(TestCase):
    """
    H01: Production settings must strictly reject unsafe configurations:
      - Short SECRET_KEY (< 50 chars)
      - Wildcard in ALLOWED_HOSTS
      - Non-HTTPS or wildcard in CSRF_TRUSTED_ORIGINS
    """

    def _reload_production(self):
        import importlib
        import config.settings.base
        import config.settings.production
        importlib.reload(config.settings.base)
        return importlib.reload(config.settings.production)

    def test_production_rejects_short_secret_key(self):
        env = {
            "DJANGO_SECRET_KEY": "too-short",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1/db",
            "ALLOWED_HOSTS": "ledger.household.example",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                self._reload_production()
            self.assertIn("at least 50 characters", str(ctx.exception))

    def test_production_rejects_wildcard_allowed_hosts(self):
        env = {
            "DJANGO_SECRET_KEY": "valid-production-key-that-is-at-least-50-characters-long-12345",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1/db",
            "ALLOWED_HOSTS": "*",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                self._reload_production()
            self.assertIn("must contain exact hostnames", str(ctx.exception))

    def test_production_rejects_insecure_csrf_origins(self):
        env = {
            "DJANGO_SECRET_KEY": "valid-production-key-that-is-at-least-50-characters-long-12345",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1/db",
            "ALLOWED_HOSTS": "ledger.household.example",
            "CSRF_TRUSTED_ORIGINS": "http://insecure-http.example",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                self._reload_production()
            self.assertIn("must be exact HTTPS origins", str(ctx.exception))

    def test_valid_production_configuration_loads_cleanly(self):
        env = {
            "DJANGO_SECRET_KEY": "valid-production-key-that-is-at-least-50-characters-long-12345",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1/db",
            "ALLOWED_HOSTS": "ledger.household.example",
            "CSRF_TRUSTED_ORIGINS": "https://ledger.household.example",
        }
        with patch.dict(os.environ, env):
            prod = self._reload_production()

            self.assertFalse(prod.DEBUG)
            self.assertTrue(prod.SECURE_SSL_REDIRECT)
            self.assertTrue(prod.SESSION_COOKIE_SECURE)
            self.assertTrue(prod.CSRF_COOKIE_SECURE)
            self.assertEqual(prod.ALLOWED_HOSTS, ["ledger.household.example"])
            self.assertEqual(prod.CSRF_TRUSTED_ORIGINS, ["https://ledger.household.example"])

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        import importlib
        import config.settings.base
        importlib.reload(config.settings.base)
