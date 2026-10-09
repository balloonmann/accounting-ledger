from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Enter secure password", "class": "form-control"}),
        help_text="Must satisfy standard security rules.",
    )

    class Meta:
        model = User
        fields = ["username", "role", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "e.g. alice", "class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-control"}),
        }

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data["password"]
        user.set_password(password)
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Leave blank to keep unchanged", "class": "form-control"}),
        help_text="Optional: enter a new password to reset.",
    )

    class Meta:
        model = User
        fields = ["username", "role", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-control"}),
        }

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user
