from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, generics
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from users.basic_auth import BASIC_AUTH_CHALLENGE, InvalidBasicCredentials, parse_basic_authorization
from users.models import User
from users.permissions import IsTeacher
from users.serializers import LoginResponseSerializer, RegisterSerializer, UserSerializer
from users.tokens import issue_token_pair


class LoginView(APIView):
    """Exchange `Authorization: Basic base64(username:password)` for a JWT pair."""

    # Credentials are checked in post() instead of by a DRF authentication class:
    # DRF authenticates *before* throttling, so failed attempts would never be rate limited.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def get_authenticate_header(self, request):
        # Without authentication classes DRF would turn 401 into 403; keep 401 + challenge.
        return BASIC_AUTH_CHALLENGE

    @extend_schema(
        request=None,
        auth=[{"basicAuth": []}],
        responses={
            200: LoginResponseSerializer,
            400: OpenApiResponse(description="Malformed Basic credentials"),
            401: OpenApiResponse(description="Missing or invalid credentials"),
            429: OpenApiResponse(description="Too many login attempts"),
        },
    )
    def post(self, request):
        try:
            credentials = parse_basic_authorization(request.headers.get("Authorization", ""))
        except InvalidBasicCredentials as exc:
            raise ParseError(str(exc)) from exc
        if credentials is None:
            raise NotAuthenticated("Send credentials as 'Authorization: Basic base64(username:password)'.")

        username, password = credentials
        # Returns None for unknown users, wrong passwords and inactive accounts alike.
        user = authenticate(request, username=username, password=password)
        if user is None:
            raise AuthenticationFailed("Invalid username or password.")

        update_last_login(None, user)
        return Response(LoginResponseSerializer({**issue_token_pair(user), "user": user}).data)


class RegisterView(generics.CreateAPIView):
    """Self-registration of a student account."""

    serializer_class = RegisterSerializer
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


class MeView(generics.RetrieveUpdateAPIView):
    """Profile of the authenticated user."""

    serializer_class = UserSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


class StudentListView(generics.ListAPIView):
    """Active students (teachers only)."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsTeacher]
    queryset = User.objects.filter(role=User.Role.STUDENT, is_active=True).order_by("last_name", "first_name", "id")
    filter_backends = [filters.SearchFilter]
    search_fields = ["username", "first_name", "last_name"]
