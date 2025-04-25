import threading
from django.apps import AppConfig

class CameraappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cameraapp'

    def ready(self):
        # Optional: only if signals.py exists
        try:
            import cameraapp.signals
        except ImportError:
            pass

        # Start background photo scheduler
        from .scheduler import start_photo_scheduler
        threading.Thread(target=start_photo_scheduler, daemon=True).start()
