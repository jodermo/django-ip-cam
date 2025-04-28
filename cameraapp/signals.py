# cameraapp/signals.py
from django.core.signals import request_finished
from django.dispatch import receiver
from .camera_manager import CameraManager

@receiver(request_finished)
def on_request_finished(sender, **kwargs):
    """Ensure camera resources are properly released when Django shuts down"""
    CameraManager().release()