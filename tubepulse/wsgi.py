"""WSGI config for TubePulse CRM."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tubepulse.settings")
application = get_wsgi_application()
