from .models import CameraSettings

def get_camera_settings():
    return CameraSettings.objects.first()