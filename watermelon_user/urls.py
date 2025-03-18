from django.urls import path
from .views import UserProfileSyncView

urlpatterns = [
    path('sync/', UserProfileSyncView.as_view(), name='sync'),
]