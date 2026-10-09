import os
from django.core.exceptions import ImproperlyConfigured
from .base import *  # noqa: F403

ALLOWED_HOSTS = [x.strip() for x in required("ALLOWED_HOSTS").split(",") if x.strip()]
if any("*" in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Production ALLOWED_HOSTS must contain exact hostnames.")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Production signing key must be at least 50 characters.")
CSRF_TRUSTED_ORIGINS = [
    x.strip() for x in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()
]
if any(not origin.startswith("https://") or "*" in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("Production CSRF origins must be exact HTTPS origins.")
DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
if os.environ.get("TRUST_PROXY_HTTPS") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
