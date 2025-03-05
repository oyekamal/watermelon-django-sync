from rest_framework import serializers
from .models import Project, Task

class TaskSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        allow_null=True,
        required=False
    )

    class Meta:
        model = Task
        fields = ['id', 'title', 'project', 'created_at', 'updated_at']

class ProjectSerializer(serializers.ModelSerializer):
    lead_task = serializers.PrimaryKeyRelatedField(
        queryset=Task.objects.all(),
        allow_null=True,
        required=False
    )

    class Meta:
        model = Project
        fields = ['id', 'name', 'lead_task', 'created_at', 'updated_at']