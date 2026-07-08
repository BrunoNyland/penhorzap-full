"""
WSGI config for penhorzap project.

Loads the shared `.env` (one level above `www/`) before Django boots, so
gunicorn (started with WorkingDirectory=/var/www/pwa.brunonyland.com/www)
picks up DJANGO_SETTINGS_MODULE, DB_*, EVOLUTION_* etc.
"""

import os

import dotenv
from django.core.wsgi import get_wsgi_application

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PROJECT_DIR)
dotenv.load_dotenv(os.path.join(BASE_DIR, ".env"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "penhorzap.settings")

application = get_wsgi_application()
