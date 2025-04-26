import threading
from django.apps import AppConfig

class CameraappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cameraapp'

    def ready(self):
        try:
            import cameraapp.signals
        except ImportError:
            pass

        def start_safe():
            from .scheduler import wait_for_table, start_photo_scheduler
            wait_for_table("cameraapp_camerasettings")
            start_photo_scheduler()

        threading.Thread(target=start_safe, daemon=True).start()
