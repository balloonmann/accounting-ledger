import logging
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.operations.models import ActivityRecord

from .forms import UserCreateForm, UserEditForm
from .policies import is_admin

logger = logging.getLogger(__name__)
User = get_user_model()


@login_required
def user_list(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can manage users.")

    users = User.objects.all().order_by("-is_active", "role", "username")
    return render(request, "identity/user_list.html", {"users": users})


@login_required
def user_create(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can create users.")

    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            ActivityRecord.objects.create(
                actor=request.user,
                action="CREATE_USER",
                object_type="User",
                object_id=str(user.pk),
                metadata={"username": user.username, "role": user.role},
            )
            messages.success(request, f"User '{user.username}' created successfully.")
            return redirect("user_list")
    else:
        form = UserCreateForm()

    return render(request, "identity/user_form.html", {
        "form": form,
        "title": "Add Household Member",
        "action": "Create User",
    })


@login_required
def user_edit(request, pk):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can edit users.")

    target_user = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserEditForm(request.POST, instance=target_user)
        if form.is_valid():
            # Safeguard: prevent disabling or demoting the last active admin
            if target_user.pk == request.user.pk:
                new_role = form.cleaned_data.get("role")
                new_active = form.cleaned_data.get("is_active")
                if not new_active or new_role != User.Role.ADMIN:
                    messages.error(request, "You cannot deactivate or demote your own administrator account.")
                    return render(request, "identity/user_form.html", {
                        "form": form,
                        "target_user": target_user,
                        "title": f"Edit User: {target_user.username}",
                        "action": "Save Changes",
                    })

            user = form.save()
            ActivityRecord.objects.create(
                actor=request.user,
                action="UPDATE_USER",
                object_type="User",
                object_id=str(user.pk),
                metadata={"username": user.username, "role": user.role, "is_active": user.is_active},
            )
            messages.success(request, f"User '{user.username}' updated successfully.")
            return redirect("user_list")
    else:
        form = UserEditForm(instance=target_user)

    return render(request, "identity/user_form.html", {
        "form": form,
        "target_user": target_user,
        "title": f"Edit User: {target_user.username}",
        "action": "Save Changes",
    })


@login_required
@require_POST
def user_toggle_active(request, pk):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can toggle user active state.")

    target_user = get_object_or_404(User, pk=pk)
    if target_user.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("user_list")

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active"])

    status_str = "activated" if target_user.is_active else "deactivated"
    ActivityRecord.objects.create(
        actor=request.user,
        action="TOGGLE_USER_ACTIVE",
        object_type="User",
        object_id=str(target_user.pk),
        metadata={"is_active": target_user.is_active},
    )
    messages.success(request, f"User '{target_user.username}' has been {status_str}.")
    return redirect("user_list")
