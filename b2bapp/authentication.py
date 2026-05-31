from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from .models import User

class CustomJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user_id = validated_token.get('user_id')
        if not user_id:
            raise AuthenticationFailed('Token contained no recognizable user identification', code='user_not_found')

        try:
            user = User.objects.get(user_id=user_id, is_active=True)
        except User.DoesNotExist:
            raise AuthenticationFailed('User not found', code='user_not_found')

        return user
