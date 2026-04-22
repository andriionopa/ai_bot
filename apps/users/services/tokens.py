from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User


def build_token_pair(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}

