import logging
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from apps.operations.models import ActivityRecord

logger = logging.getLogger("apps.identity")


def get_client_ip(request):
    if not request:
        return "unknown"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    ip = get_client_ip(request)
    logger.info("Successful login for user '%s' from IP %s", user.username, ip)
    try:
        ActivityRecord.objects.create(
            actor=user,
            action="LOGIN_SUCCESS",
            object_type="User",
            object_id=str(user.pk),
            metadata={"username": user.username, "ip": ip},
        )
    except Exception as exc:
        logger.error("Failed to record login success audit activity: %s", exc)


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "<unknown>") if credentials else "<unknown>"
    ip = get_client_ip(request)
    logger.warning("Failed login attempt for user '%s' from IP %s", username, ip)
    try:
        ActivityRecord.objects.create(
            actor=None,
            action="LOGIN_FAILED",
            object_type="User",
            object_id="",
            metadata={"username": str(username), "ip": ip},
        )
    except Exception as exc:
        logger.error("Failed to record login failure audit activity: %s", exc)
