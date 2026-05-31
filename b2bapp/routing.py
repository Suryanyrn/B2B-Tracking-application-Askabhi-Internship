"""
B2B Tracking Application - ASGI Routing
=========================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

This file replaces the standard asgi.py and wires Django Channels so that:
  • HTTP requests     → handled by Django's standard WSGI/ASGI application
  • WebSocket frames  → routed to the appropriate Channels consumer

WebSocket endpoints:
  WS /ws/shipments/{shipment_id}/location/   → ShipmentLocationConsumer

Channel Layer:
  Uses Redis as the backing store so broadcasts work across multiple
  Django Channels worker processes / pods.

  Required pip packages:
      channels
      channels-redis
      daphne  (or uvicorn[standard] as the ASGI server)

Django settings additions (settings.py):
  ─────────────────────────────────────────────────────────────────────────
  INSTALLED_APPS = [
      ...
      "channels",
      "daphne",       # must be BEFORE django.contrib.staticfiles
  ]

  # Tell Django to use Channels' ASGI application
  ASGI_APPLICATION = "your_project.routing.application"

  # Redis channel layer (replace host/port with your Redis instance)
  CHANNEL_LAYERS = {
      "default": {
          "BACKEND": "channels_redis.core.RedisChannelLayer",
          "CONFIG": {
              "hosts": [("127.0.0.1", 6379)],
              # Tune these for production scale:
              "capacity":        1500,   # max messages per channel before backpressure
              "expiry":          60,     # seconds before an unread message expires
              "group_expiry":    86400,  # seconds before an idle group is GC'd
          },
      },
  }
  ─────────────────────────────────────────────────────────────────────────

Usage with Daphne (production):
    daphne -b 0.0.0.0 -p 8000 your_project.routing:application

Usage with Uvicorn (alternative):
    uvicorn your_project.routing:application --host 0.0.0.0 --port 8000 --workers 4
"""

import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import re_path

# Set the Django settings module before any Django imports
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "b2b.settings")

# Initialise Django — must happen before importing consumers or models
django_asgi_app = get_asgi_application()

# Import consumer AFTER Django is initialised to avoid AppRegistryNotReady
from .consumers import ShipmentLocationConsumer  # noqa: E402


# ---------------------------------------------------------------------------
# WebSocket URL patterns
# ---------------------------------------------------------------------------
# Pattern: /ws/shipments/<shipment_id>/location/
#   shipment_id — UUID4 (8-4-4-4-12 hex groups, case-insensitive)
# ---------------------------------------------------------------------------

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

websocket_urlpatterns = [
    re_path(
        rf"^ws/shipments/(?P<shipment_id>{UUID_PATTERN})/location/$",
        ShipmentLocationConsumer.as_asgi(),
        name="ws-shipment-location",
    ),
]


# ---------------------------------------------------------------------------
# Authentication middleware stack
#
# AllowedHostsOriginValidator  — blocks WebSocket connections from any origin
#   not listed in Django's ALLOWED_HOSTS, protecting against CSRF-style attacks
#   on the WebSocket handshake.
#
# JWTWebsocketMiddleware is NOT used here because we validate the JWT inside
# ShipmentLocationConsumer.connect() via the ?token= query parameter.
# This is the standard pattern when you cannot set Authorization headers from
# a browser WebSocket client.
# ---------------------------------------------------------------------------

websocket_application = AllowedHostsOriginValidator(
    URLRouter(websocket_urlpatterns)
)


# ---------------------------------------------------------------------------
# Top-level ASGI application
# ProtocolTypeRouter dispatches on the connection type:
#   http       → standard Django request/response cycle
#   websocket  → Channels consumer pipeline
# ---------------------------------------------------------------------------

application = ProtocolTypeRouter(
    {
        # All HTTP traffic (REST API, admin, static files) is handled normally
        "http": django_asgi_app,

        # WebSocket traffic is routed through AllowedHostsOriginValidator
        # → URLRouter → ShipmentLocationConsumer
        "websocket": websocket_application,
    }
)


# ---------------------------------------------------------------------------
# Developer quick-reference
# ---------------------------------------------------------------------------
#
# Connecting as a Driver (push location):
#   wscat -c "ws://localhost:8000/ws/shipments/<uuid>/location/?token=<access_jwt>"
#   > {"type": "location", "latitude": 12.9716, "longitude": 77.5946}
#
# Connecting as a Client / Manager (subscribe only):
#   wscat -c "ws://localhost:8000/ws/shipments/<uuid>/location/?token=<access_jwt>"
#   < {"type": "location_update", "shipment_id": "...", "latitude": 12.9716,
#      "longitude": 77.5946, "timestamp": "2026-04-23T10:30:00Z",
#      "driver_name": "Ravi Kumar"}
#
# WS close codes used by ShipmentLocationConsumer:
#   4001  — Authentication failure (missing / invalid / expired JWT)
#   4003  — Authorization failure  (driver not assigned to this shipment)
#   4004  — Resource not found     (shipment does not exist for this company)
#
# Redis channel group naming convention:
#   "shipment_{shipment_id}_location"
#   e.g. "shipment_3f2a1b4c-...-d09e_location"
#
# Scaling notes:
#   - Each Daphne / Uvicorn worker holds its own in-memory rate-limit bucket.
#   - For multi-process deployments replace _ping_counts in consumers.py
#     with a Redis INCR + EXPIRE counter keyed on the user's channel_name.
#   - The channel layer's Redis pub/sub fan-out handles cross-worker broadcasts
#     transparently — no extra code needed in the consumer.
# ---------------------------------------------------------------------------