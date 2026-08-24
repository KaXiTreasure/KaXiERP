from rest_framework import serializers


class LoginSerializer(serializers.Serializer[dict[str, str]]):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    captcha = serializers.CharField(
        max_length=8, trim_whitespace=True, write_only=True, required=False, allow_blank=True
    )


class PasswordChangeSerializer(serializers.Serializer[dict[str, str]]):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(
        max_length=128, min_length=8, trim_whitespace=False, write_only=True
    )
