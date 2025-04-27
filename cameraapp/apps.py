import threading
import os
from django.apps import AppConfig

class CameraappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cameraapp'

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            # Nur Webserver, nicht bei 'migrate' etc.
            return
        if os.environ.get("RUN_TIMELAPSE") == "1":
            from .scheduler import start_photo_scheduler
            threading.Thread(target=start_photo_scheduler, daemon=True).start()


