from django.urls import path
from .django_view import receive_logs

urlpatterns = [
    path("log", receive_logs, name="log-receive"),
]
