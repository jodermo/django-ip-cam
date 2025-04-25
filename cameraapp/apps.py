class CameraappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cameraapp'

    def ready(self):
        import cameraapp.signals  # optional für Startup-Logik
