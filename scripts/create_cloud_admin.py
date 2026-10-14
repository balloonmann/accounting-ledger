"""Create an admin user directly on the cloud database."""
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main():
    print("=== Create Cloud Admin User ===")
    db_url = input("Paste your Render External Database URL: ").strip()
    if not db_url:
        print("Error: Database URL cannot be blank.")
        sys.exit(1)

    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"
    os.environ["DATABASE_URL"] = db_url
    os.environ["DJANGO_SECRET_KEY"] = "cloud-admin-provisioning-secret-key-at-least-50-chars-long-12345"
    os.environ["ALLOWED_HOSTS"] = "localhost"
    os.environ["CSRF_TRUSTED_ORIGINS"] = "https://localhost"

    import django
    django.setup()
    from apps.identity.models import User

    username = input("Enter admin username: ").strip()
    if not username:
        print("Error: Username cannot be blank.")
        sys.exit(1)

    password = getpass.getpass("Enter password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Error: Passwords do not match.")
        sys.exit(1)

    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.role = User.Role.ADMIN
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.save()

    action = "Created" if created else "Updated password for"
    print(f"\n[SUCCESS] Successfully {action} cloud admin '{username}' on Render!")

if __name__ == "__main__":
    main()
