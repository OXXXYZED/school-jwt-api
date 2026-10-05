from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User


def issue_token_pair(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    # Informational claims for clients (e.g. role-based UI routing); they are copied to
    # the access token. The JWT payload is only Base64url-encoded, so nothing secret here.
    # Authorization is always checked against the user loaded from the DB, so a stale
    # claim (role changed after login) can never grant access.
    refresh["username"] = user.username
    refresh["role"] = user.role
    return {"access": str(refresh.access_token), "refresh": str(refresh)}
