# 7. Administrator Multi-Factor Authentication (MFA / TOTP)

Date: 2026-10-14
Status: Accepted

## Context
Administrators have privileged access to configure chart of accounts, edit posting lock dates, create users, and manage account privacy grants. A compromised admin credential presents a significant integrity and privacy risk.

## Decision
For production / real-data deployments:
1. Administrator accounts (`role == 'ADMIN'`) will require Time-based One-Time Password (TOTP) authentication using `django-otp`.
2. Standard members (`role == 'MEMBER'`) remain on single-factor password authentication in scope for the single household release, with optional TOTP enrollment.
3. Enrollment and verification flow will use RFC 6238-compliant authenticator apps (e.g. Google Authenticator, Bitwarden, 1Password).

## Implementation Roadmap
- Add `django-otp` and `qrcode` to dependencies during pre-production rollout.
- Include `django_otp` and `django_otp.plugins.otp_totp` in `INSTALLED_APPS`.
- Add `django_otp.middleware.OTPMiddleware` after `AuthenticationMiddleware`.
- Add an admin-enforced view requiring TOTP verification for sensitive operations (`/settings/lock-date/`, `/users/`).
