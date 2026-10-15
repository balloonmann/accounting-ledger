import os
from urllib.parse import urlparse
from django.core.exceptions import ImproperlyConfigured

url = os.environ.get("TEST_DATABASE_URL", "")
parts = urlparse(url)
if (
    parts.hostname != "127.0.0.1" or parts.port != 55432
    or parts.path != "/ledger_test_control"
):
    raise ImproperlyConfigured(
        "Tests require the isolated loopback PostgreSQL instance on port 55432 "
        "and database ledger_test_control. Run scripts/test.py."
    )
os.environ["DATABASE_URL"] = url
os.environ["DJANGO_SECRET_KEY"] = "test-only-signing-key-never-used-outside-isolated-tests-12345"
from .base import *  # noqa: E402,F403

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES["default"]["TEST"] = {"NAME": "test_household_ledger"}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
WHITENOISE_USE_FINDERS = True
AXES_ENABLED = False
TEST_RUNNER = "config.test_runner.LedgerTestRunner"
