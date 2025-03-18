# myapp/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction
import datetime
from rest_framework import status
from .models import User, StudentProfile
from .serializers import UserSerializer, StudentProfileSerializer

class UserProfileSyncView(APIView):
    """
    API view to handle synchronization of User and StudentProfile models using WatermelonDB.
    The sync logic mirrors that of the Project/Task models.
    """

    def get(self, request):
        # Convert the provided last sync timestamp (milliseconds) to a UTC datetime
        last_pulled_at_str = request.query_params.get('last_pulled_at')
        if last_pulled_at_str:
            last_pulled_at = datetime.datetime.fromtimestamp(
                int(last_pulled_at_str) / 1000, tz=datetime.timezone.utc
            )
        else:
            last_pulled_at = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

        # --- Users ---
        users_created = User.objects.filter(
            created_at__gt=last_pulled_at, deleted_at__isnull=True
        )
        users_updated = User.objects.filter(
            updated_at__gt=last_pulled_at, created_at__lte=last_pulled_at, deleted_at__isnull=True
        )
        users_deleted = User.objects.filter(
            deleted_at__gt=last_pulled_at
        ).values_list('id', flat=True)

        # --- Student Profiles ---
        profiles_created = StudentProfile.objects.filter(
            created_at__gt=last_pulled_at, deleted_at__isnull=True
        )
        profiles_updated = StudentProfile.objects.filter(
            updated_at__gt=last_pulled_at, created_at__lte=last_pulled_at, deleted_at__isnull=True
        )
        profiles_deleted = StudentProfile.objects.filter(
            deleted_at__gt=last_pulled_at
        ).values_list('id', flat=True)

        changes = {
            'users': {
                'created': UserSerializer(users_created, many=True).data,
                'updated': UserSerializer(users_updated, many=True).data,
                'deleted': list(users_deleted),
            },
            'student_profiles': {
                'created': StudentProfileSerializer(profiles_created, many=True).data,
                'updated': StudentProfileSerializer(profiles_updated, many=True).data,
                'deleted': list(profiles_deleted),
            }
        }

        current_timestamp = int(timezone.now().timestamp() * 1000)
        return Response({'changes': changes, 'timestamp': current_timestamp})

    def post(self, request):
        errors = []
        with transaction.atomic():
            # Expected request structure:
            # {
            #   "changes": {
            #     "users": {"created": [...], "updated": [...], "deleted": [...]},
            #     "student_profiles": {"created": [...], "updated": [...], "deleted": [...]}
            #   }
            # }
            changes = request.data.get('changes', {})
            user_changes = changes.get('users', {})
            profile_changes = changes.get('student_profiles', {})

            errors.extend(self._apply_changes(user_changes, profile_changes))

        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': 'success'}, status=status.HTTP_200_OK)

    def _apply_changes(self, user_changes, profile_changes):
        errors = []
        user_items = user_changes.get('created', [])
        profile_items = profile_changes.get('created', [])

        # Phase 1: Create User records
        for item in user_items:
            serializer = UserSerializer(data=item)
            if serializer.is_valid():
                serializer.save()
            else:
                errors.append(f"User creation failed for ID {item.get('id', 'unknown')}: {serializer.errors}")

        # Phase 2: Create StudentProfile records without the user FK initially
        for item in profile_items:
            # Remove the 'user' field to avoid FK dependency issues during creation
            item_data = {k: v for k, v in item.items() if k != 'user'}
            serializer = StudentProfileSerializer(data=item_data)
            if serializer.is_valid():
                serializer.save()
            else:
                errors.append(f"StudentProfile creation failed for ID {item.get('id', 'unknown')}: {serializer.errors}")

        # Phase 3: Update StudentProfile records to set the user foreign key
        for item in profile_items:
            if 'user' in item:
                try:
                    profile = StudentProfile.objects.get(id=item['id'])
                    user = User.objects.get(id=item['user'])
                    profile.user = user
                    profile.save()
                except (StudentProfile.DoesNotExist, User.DoesNotExist) as e:
                    errors.append(f"Failed to set user for student profile {item['id']}: {str(e)}")
                except Exception as e:
                    errors.append(f"Unexpected error for student profile {item['id']}: {str(e)}")

        # Process updates for Users and StudentProfiles
        errors.extend(self._apply_updates(user_changes.get('updated', []), UserSerializer, User))
        errors.extend(self._apply_updates(profile_changes.get('updated', []), StudentProfileSerializer, StudentProfile))
        # Process soft deletions by setting deleted_at
        errors.extend(self._apply_deletions(user_changes.get('deleted', []), User))
        errors.extend(self._apply_deletions(profile_changes.get('deleted', []), StudentProfile))

        return errors

    def _apply_updates(self, items, serializer_class, model_class):
        errors = []
        for item in items:
            try:
                obj = model_class.objects.get(id=item['id'])
                serializer = serializer_class(obj, data=item, partial=True)
                if serializer.is_valid():
                    serializer.save()
                else:
                    errors.append(f"Update failed for {model_class.__name__} {item['id']}: {serializer.errors}")
            except Exception as e:
                errors.append(f"Unexpected error updating {model_class.__name__} {item.get('id')}: {str(e)}")
        return errors

    def _apply_deletions(self, ids, model_class):
        errors = []
        for record_id in ids:
            try:
                obj = model_class.objects.get(id=record_id)
                obj.deleted_at = timezone.now()
                obj.save()
            except Exception as e:
                errors.append(f"Unexpected error deleting {model_class.__name__} {record_id}: {str(e)}")
        return errors
