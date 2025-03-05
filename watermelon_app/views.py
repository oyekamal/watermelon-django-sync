# myapp/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction
from .models import Project, Task
from .serializers import ProjectSerializer, TaskSerializer
import datetime
from rest_framework import status

class SyncView(APIView):
    """
    API view to handle synchronization of Project and Task models with a client application.
    Supports pulling changes from the server (GET) and pushing changes to the server (POST).
    Ensures atomicity for database operations and handles mutual dependencies between projects and tasks.
    """

    def get(self, request):
        """
        Handle GET requests to pull changes since the last synchronization timestamp.

        Args:
            request: The HTTP request object containing query parameters.

        Query Parameters:
            last_pulled_at (str): Timestamp in milliseconds since Unix epoch representing the last sync time.

        Returns:
            Response: A JSON response containing:
                - changes: Dictionary with created, updated, and deleted records for projects and tasks.
                - timestamp: Current server timestamp in milliseconds.

        Example Response:
            {
                "changes": {
                    "projects": {
                        "created": [...],
                        "updated": [...],
                        "deleted": [1, 2, 3]
                    },
                    "tasks": {
                        "created": [...],
                        "updated": [...],
                        "deleted": [4, 5, 6]
                    }
                },
                "timestamp": 1698771234567
            }
        """
        # Extract last_pulled_at from query parameters
        last_pulled_at_str = request.query_params.get('last_pulled_at')
        if last_pulled_at_str:
            # Convert milliseconds to seconds and create a UTC datetime object
            last_pulled_at = datetime.datetime.fromtimestamp(
                int(last_pulled_at_str) / 1000, tz=datetime.timezone.utc
            )
        else:
            # Default to earliest possible time if no timestamp provided
            last_pulled_at = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

        # Filter projects created after last_pulled_at and not deleted
        projects_created = Project.objects.filter(
            created_at__gt=last_pulled_at, deleted_at__isnull=True
        )
        # Filter projects updated after last_pulled_at, created on or before, and not deleted
        projects_updated = Project.objects.filter(
            updated_at__gt=last_pulled_at, created_at__lte=last_pulled_at, deleted_at__isnull=True
        )
        # Get IDs of projects soft-deleted after last_pulled_at
        projects_deleted = Project.objects.filter(
            deleted_at__gt=last_pulled_at
        ).values_list('id', flat=True)

        # Filter tasks created after last_pulled_at and not deleted
        tasks_created = Task.objects.filter(
            created_at__gt=last_pulled_at, deleted_at__isnull=True
        )
        # Filter tasks updated after last_pulled_at, created on or before, and not deleted
        tasks_updated = Task.objects.filter(
            updated_at__gt=last_pulled_at, created_at__lte=last_pulled_at, deleted_at__isnull=True
        )
        # Get IDs of tasks soft-deleted after last_pulled_at
        tasks_deleted = Task.objects.filter(
            deleted_at__gt=last_pulled_at
        ).values_list('id', flat=True)

        # Serialize the filtered data into a structured response
        changes = {
            'projects': {
                'created': ProjectSerializer(projects_created, many=True).data,
                'updated': ProjectSerializer(projects_updated, many=True).data,
                'deleted': list(projects_deleted)
            },
            'tasks': {
                'created': TaskSerializer(tasks_created, many=True).data,
                'updated': TaskSerializer(tasks_updated, many=True).data,
                'deleted': list(tasks_deleted)
            }
        }

        # Current server timestamp in milliseconds
        current_timestamp = int(timezone.now().timestamp() * 1000)
        return Response({'changes': changes, 'timestamp': current_timestamp})

    def post(self, request):
        """
        Handle POST requests to push changes from the client to the server.

        Args:
            request: The HTTP request object containing the changes in the request body.

        Request Body:
            changes (dict): Dictionary containing created, updated, and deleted records for projects and tasks.
                Example:
                    {
                        "projects": {
                            "created": [{"id": 1, "name": "Project A", "lead_task": 1}, ...],
                            "updated": [{"id": 2, "name": "Project B"}, ...],
                            "deleted": [3, 4]
                        },
                        "tasks": {
                            "created": [{"id": 1, "title": "Task A", "project": 1}, ...],
                            "updated": [{"id": 2, "title": "Task B"}, ...],
                            "deleted": [5, 6]
                        }
                    }

        Returns:
            Response: A JSON response indicating success or failure:
                - On success: {"status": "success"} with HTTP 200.
                - On failure: {"errors": [error_messages]} with HTTP 400.
        """
        errors = []
        # Use atomic transaction to ensure all changes are applied or none are
        with transaction.atomic():
            # Extract changes from request data, defaulting to empty dict if not provided
            changes = request.data.get('changes', {})
            projects_changes = changes.get('projects', {})
            tasks_changes = changes.get('tasks', {})
            # Apply changes and collect any errors
            errors.extend(self._apply_changes(projects_changes, tasks_changes))
        
        if errors:
            # Return errors with 400 status if any issues occurred
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        # Return success response if all changes applied successfully
        return Response({'status': 'success'}, status=status.HTTP_200_OK)

    def _apply_changes(self, projects_changes, tasks_changes):
        """
        Apply changes to projects and tasks, handling creation, updates, and deletions.
        Handles mutual dependencies by creating records first, then updating foreign keys.

        Args:
            projects_changes (dict): Dictionary of changes for projects (created, updated, deleted).
            tasks_changes (dict): Dictionary of changes for tasks (created, updated, deleted).

        Returns:
            list: List of error messages encountered during the process.
        """
        errors = []
        project_items = projects_changes.get('created', [])
        task_items = tasks_changes.get('created', [])

        # Step 1: Create projects without lead_task to avoid dependency issues
        for item in project_items:
            # Exclude lead_task field during initial creation
            item_data = {k: v for k, v in item.items() if k != 'lead_task'}
            serializer = ProjectSerializer(data=item_data)
            if serializer.is_valid():
                serializer.save()
            else:
                errors.append(f"Project creation failed for ID {item.get('id', 'unknown')}: {serializer.errors}")

        # Step 2: Create tasks without project to avoid dependency issues
        for item in task_items:
            # Exclude project field during initial creation
            item_data = {k: v for k, v in item.items() if k != 'project'}
            serializer = TaskSerializer(data=item_data)
            if serializer.is_valid():
                serializer.save()
            else:
                errors.append(f"Task creation failed for ID {item.get('id', 'unknown')}: {serializer.errors}")

        # Step 3: Update foreign keys for projects (lead_task) after all creations
        for item in project_items:
            if 'lead_task' in item:
                try:
                    project = Project.objects.get(id=item['id'])
                    task = Task.objects.get(id=item['lead_task'])
                    project.lead_task = task
                    project.save()
                except (Project.DoesNotExist, Task.DoesNotExist) as e:
                    errors.append(f"Failed to set lead_task for project {item['id']}: {str(e)}")
                except Exception as e:
                    errors.append(f"Unexpected error for project {item['id']}: {str(e)}")

        # Step 4: Update foreign keys for tasks (project) after all creations
        for item in task_items:
            if 'project' in item:
                try:
                    task = Task.objects.get(id=item['id'])
                    project = Project.objects.get(id=item['project'])
                    task.project = project
                    task.save()
                except (Task.DoesNotExist, Project.DoesNotExist) as e:
                    errors.append(f"Failed to set project for task {item['id']}: {str(e)}")
                except Exception as e:
                    errors.append(f"Unexpected error for task {item['id']}: {str(e)}")

        # Step 5: Process updates and deletions
        errors.extend(self._apply_updated(projects_changes.get('updated', []), ProjectSerializer, 'lead_task'))
        errors.extend(self._apply_updated(tasks_changes.get('updated', []), TaskSerializer, 'project'))
        errors.extend(self._apply_deleted(projects_changes.get('deleted', []), Project))
        errors.extend(self._apply_deleted(tasks_changes.get('deleted', []), Task))

        return errors

    def _apply_updated(self, items, serializer_class, fk_field):
        """
        Apply updates to existing records using partial updates.

        Args:
            items (list): List of records to update, each containing an 'id' and updated fields.
            serializer_class (class): Serializer class for the model (ProjectSerializer or TaskSerializer).
            fk_field (str): Foreign key field name ('lead_task' for Project, 'project' for Task).

        Returns:
            list: List of error messages encountered during updates.
        """
        errors = []
        for item in items:
            try:
                # Determine model based on foreign key field
                model = Project if fk_field == 'lead_task' else Task
                obj = model.objects.get(id=item['id'])
                # Use partial=True to allow updating only provided fields
                serializer = serializer_class(obj, data=item, partial=True)
                if serializer.is_valid():
                    serializer.save()
                else:
                    errors.append(f"Update failed for {model.__name__} {item['id']}: {serializer.errors}")
            except model.DoesNotExist:
                errors.append(f"{model.__name__} {item['id']} does not exist")
            except Exception as e:
                errors.append(f"Unexpected error updating {model.__name__} {item['id']}: {str(e)}")
        return errors

    def _apply_deleted(self, ids, model):
        """
        Apply soft deletions by setting the deleted_at timestamp.

        Args:
            ids (list): List of IDs of records to delete.
            model (class): Model class to delete from (Project or Task).

        Returns:
            list: List of error messages encountered during deletions.
        """
        errors = []
        for id in ids:
            try:
                obj = model.objects.get(id=id)
                # Soft delete by setting deleted_at timestamp
                obj.deleted_at = timezone.now()
                obj.save()
            except model.DoesNotExist:
                errors.append(f"{model.__name__} {id} does not exist")
            except Exception as e:
                errors.append(f"Unexpected error deleting {model.__name__} {id}: {str(e)}")
        return errors