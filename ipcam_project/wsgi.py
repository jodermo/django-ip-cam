import os
from django.core.wsgi import get_wsgi_application
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Set the settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ipcam_project.settings')

# WSGI application for Gunicorn and production
application = get_wsgi_application()
