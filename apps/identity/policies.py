def is_admin(user):
    return bool(user and user.is_authenticated and user.is_active and user.role == "ADMIN")
