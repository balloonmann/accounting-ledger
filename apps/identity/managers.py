from django.contrib.auth.models import UserManager as DjangoUserManager


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "ADMIN")
        if extra_fields["role"] != "ADMIN":
            raise ValueError("A household superuser must have the Admin role.")
        return super().create_superuser(username, email, password, **extra_fields)
