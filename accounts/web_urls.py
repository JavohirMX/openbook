from django.urls import path

from accounts.web_views import EmailLoginView, SetupView, WebLogoutView

urlpatterns = [
    path("setup/", SetupView.as_view(), name="setup"),
    path("login/", EmailLoginView.as_view(), name="login"),
    path("logout/", WebLogoutView.as_view(), name="logout"),
]
