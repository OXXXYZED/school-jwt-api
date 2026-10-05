from django.urls import path
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView, TokenVerifyView

from users.views import LoginView, MeView, RegisterView, StudentListView

app_name = "users"

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("auth/logout/", TokenBlacklistView.as_view(), name="logout"),
    path("users/me/", MeView.as_view(), name="me"),
    path("users/students/", StudentListView.as_view(), name="student-list"),
]
