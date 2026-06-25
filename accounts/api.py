from django.contrib.auth import authenticate, get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from openbook.api.throttling import AuthRateThrottle

User = get_user_model()


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthRateThrottle]

    def get_authenticate_header(self, request):
        return "Token"

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        if not email or not password:
            raise ValidationError({"email": ["This field is required."]})

        user = authenticate(request, email=email, password=password)
        if user is None:
            raise AuthenticationFailed("Invalid email or password.")

        token, _created = Token.objects.get_or_create(user=user)
        return Response({"token": token.key}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_200_OK)
