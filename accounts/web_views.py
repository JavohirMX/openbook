from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView

from accounts.forms import SetupSuperuserForm

User = get_user_model()


def users_exist() -> bool:
    return User.objects.exists()


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not users_exist():
            return redirect("setup")
        return super().dispatch(request, *args, **kwargs)


class SetupView(FormView):
    form_class = SetupSuperuserForm
    template_name = "accounts/setup.html"
    success_url = reverse_lazy("web:dashboard")

    def dispatch(self, request, *args, **kwargs):
        if users_exist():
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            if User.objects.exists():
                form.add_error(None, "An account has already been created.")
                return self.form_invalid(form)
            user = User.objects.create_superuser(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
            )
        login(self.request, user)
        return super().form_valid(form)


class WebLogoutView(View):
    def post(self, request):
        logout(request)
        return redirect("login")

    def get(self, request):
        return redirect("login")
