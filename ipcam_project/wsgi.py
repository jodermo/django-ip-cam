import os
from django.core.asgi import get_asgi_application
from dotenv import load_dotenv

# .env-Datei laden
load_dotenv()

# Django-Einstellungen setzen
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ipcam_project.settings')

# ASGI-Anwendung laden
application = get_asgi_application()
