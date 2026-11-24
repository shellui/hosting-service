"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from config.telemetry import setup_service_telemetry

# Before the app serves traffic. Gunicorn preload and post-fork calls are safe:
# the SDK restarts export threads, and a second call does not build a new provider.
setup_service_telemetry()

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
