from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from apps.operations.views import health

urlpatterns = [
    path("", include("apps.accounting.urls")),
    path("", include("apps.identity.urls")),
    path("", include("apps.reporting.urls")),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
]
