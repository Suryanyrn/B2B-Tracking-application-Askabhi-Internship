"""
ASGI config for b2b project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

# Set settings module before importing routing
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'b2b.settings')

from b2bapp.routing import application
