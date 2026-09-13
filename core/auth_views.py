"""Nexora — registration views (login/logout live in core.urls)."""
from django.contrib import messages
from django.contrib.auth import login
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.views.generic.edit import FormView


class RegisterForm(UserCreationForm):
    """Username + email + strong password. Email is unique and required."""

    email = forms.EmailField(required=True, label="Email address")

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "username": "Pick a username (letters, digits, @ . + - _)",
            "email": "you@example.com",
            "password1": "8+ characters, not all numbers, not too common",
            "password2": "Repeat the password",
        }
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"
            field.widget.attrs["placeholder"] = placeholders.get(name, "")


class RegisterView(FormView):
    """Create the account and log the user straight in."""

    form_class = RegisterForm
    template_name = "registration/register.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, "Welcome! Your account was created.")
        return super().form_valid(form)
