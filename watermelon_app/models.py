# myapp/models.py
import uuid
from django.db import models

class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)  # Client can provide IDs
    name = models.CharField(max_length=100)
    lead_task = models.ForeignKey(
        'Task', on_delete=models.SET_NULL, null=True, blank=True, related_name='leading_projects'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)  # Soft deletes

    class Meta:
        ordering = ['created_at']

class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    title = models.CharField(max_length=200)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True, related_name='tasks'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']