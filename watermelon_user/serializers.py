# serializers.py
from rest_framework import serializers
from .models import User, StudentProfile

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'created_at', 'updated_at', 'deleted_at']
        # Exclude sensitive fields or make them read-only
        read_only_fields = ['password']

class StudentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProfile
        fields = ['id', 'user', 'bio', 'created_at', 'updated_at', 'deleted_at']