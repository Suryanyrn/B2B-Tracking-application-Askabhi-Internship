"""
B2B Tracking Application - WebSocket Consumers
================================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

Implements the real-time GPS tracking endpoint described in Module 4:
  WS /ws/shipments/{shipment_id}/location/

Architecture:
  - Django Channels AsyncWebsocketConsumer.
  - Each active shipment gets its own Channel Group:
      "shipment_{shipment_id}_location"
  - Driver connects → sends GPS pings → all subscribers receive live updates.
  - Clients / Managers subscribe (read-only) to watch the live location.
  - JWT token is validated on connect via query-string param:
      ws://<host>/ws/shipments/{id}/location/?token=<access_jwt>

Security controls (per TRS Module 4):
  - JWT authentication on connect — unauthenticated connections are rejected.
  - Rate limiting: drivers may not send more than MAX_PINGS_PER_MINUTE pings.
    Excess pings are silently dropped (no disconnect) to prevent DDoS.
  - Drivers may only push location for shipments assigned to them.
  - Clients / Managers are receive-only (cannot push location).
  - Only users from the same company as the shipment are admitted.

Required pip packages:
    channels
    channels-redis
    djangorestframework-simplejwt
    django-ratelimit  (or use the in-memory token-bucket below)
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone as dt_tz

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import Driver, Shipment, User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate-limiter (in-memory token bucket per channel / user)
# For production, replace with a Redis-backed counter so it survives
# multi-process / multi-pod deployments.
# ---------------------------------------------------------------------------

MAX_PINGS_PER_MINUTE = 30           # ~1 ping every 2 seconds is plenty for GPS
_ping_counts: dict[str, list] = defaultdict(list)  # channel_name → [timestamp, ...]


def _is_rate_limited(channel_name: str) -> bool:
    """
    Return True when the sender has exceeded MAX_PINGS_PER_MINUTE.
    Uses a sliding 60-second window.
    """
    now = datetime.now(tz=dt_tz.utc).timestamp()
    window_start = now - 60.0

    timestamps = _ping_counts[channel_name]
    # Evict timestamps outside the window
    timestamps[:] = [t for t in timestamps if t > window_start]

    if len(timestamps) >= MAX_PINGS_PER_MINUTE:
        return True

    timestamps.append(now)
    return False


# ---------------------------------------------------------------------------
# Database helpers (must be called with database_sync_to_async)
# ---------------------------------------------------------------------------

@database_sync_to_async
def _get_user_from_token(token_str: str) -> User | None:
    """
    Validate a JWT access token and return the corresponding User.
    Returns None on any failure (expired, tampered, unknown user).
    """
    try:
        validated = UntypedToken(token_str)
        user_id   = validated.get("user_id")
        return User.objects.select_related("company").get(
            user_id=user_id, is_active=True
        )
    except (InvalidToken, TokenError, User.DoesNotExist, Exception):
        return None


@database_sync_to_async
def _get_shipment(shipment_id: str, company_id) -> Shipment | None:
    """Fetch shipment, checking it belongs to the right company."""
    try:
        return (
            Shipment.objects
            .select_related("driver", "order__company", "to_client")
            .get(shipment_id=shipment_id, order__company_id=company_id)
        )
    except (Shipment.DoesNotExist, Exception):
        return None


@database_sync_to_async
def _get_driver_for_user(user: User) -> Driver | None:
    """Return the Driver profile linked to a Driver-role user (matched by phone)."""
    try:
        return Driver.objects.get(company=user.company, phone=user.phone, is_active=True)
    except Driver.DoesNotExist:
        return None


@database_sync_to_async
def _persist_location(shipment_id: str, driver_id, location_str: str) -> None:
    """
    Atomically write the live_location to Shipment and current_location to Driver.
    Called on every valid GPS ping from the driver.
    """
    Shipment.objects.filter(shipment_id=shipment_id).update(live_location=location_str)
    if driver_id:
        Driver.objects.filter(driver_id=driver_id).update(current_location=location_str)


# ---------------------------------------------------------------------------
# WebSocket Consumer
# ---------------------------------------------------------------------------

class ShipmentLocationConsumer(AsyncWebsocketConsumer):
    """
    WS /ws/shipments/{shipment_id}/location/?token=<jwt>

    Message formats
    ───────────────
    Driver → Server (push GPS ping):
        { "type": "location", "latitude": 12.9716, "longitude": 77.5946 }

    Server → All subscribers (broadcast):
        {
          "type":         "location_update",
          "shipment_id":  "<uuid>",
          "latitude":     12.9716,
          "longitude":    77.5946,
          "timestamp":    "2026-04-23T10:30:00Z",
          "driver_name":  "Ravi Kumar"
        }

    Server → Client on error:
        { "type": "error", "message": "<reason>" }
    """

    # ------------------------------------------------------------------ #
    # Connection lifecycle                                                  #
    # ------------------------------------------------------------------ #

    async def connect(self):
        self.shipment_id = self.scope["url_route"]["kwargs"]["shipment_id"]
        self.group_name  = f"shipment_{self.shipment_id}_location"
        self.user        = None
        self.driver      = None
        self.is_driver_role = False

        # 1. Extract JWT from query string  (?token=<jwt>)
        query_string = self.scope.get("query_string", b"").decode()
        token_str    = self._parse_token(query_string)

        if not token_str:
            logger.warning("WS connect rejected — no token provided for shipment %s",
                           self.shipment_id)
            await self.close(code=4001)
            return

        # 2. Validate token and load user
        self.user = await _get_user_from_token(token_str)
        if not self.user:
            logger.warning("WS connect rejected — invalid/expired token for shipment %s",
                           self.shipment_id)
            await self.close(code=4001)
            return

        # 3. Confirm shipment exists and belongs to the user's company
        self.shipment = await _get_shipment(self.shipment_id, self.user.company_id)
        if not self.shipment:
            logger.warning(
                "WS connect rejected — shipment %s not found or not in company %s",
                self.shipment_id, self.user.company_id,
            )
            await self.close(code=4004)
            return

        # 4. If the user is a Driver, load their Driver profile and verify assignment
        if self.user.is_driver:
            self.driver = await _get_driver_for_user(self.user)
            if not self.driver:
                logger.warning("WS connect rejected — no driver profile for user %s",
                               self.user.user_id)
                await self.close(code=4003)
                return
            if self.shipment.driver_id != self.driver.driver_id:
                logger.warning(
                    "WS connect rejected — driver %s not assigned to shipment %s",
                    self.driver.driver_id, self.shipment_id,
                )
                await self.close(code=4003)
                return
            self.is_driver_role = True

        # 5. Join the channel group and accept the connection
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(
            "WS connected — user=%s role=%s shipment=%s",
            self.user.user_id, self.user.role, self.shipment_id,
        )

        # Send the last known location to newly connected clients
        if self.shipment.live_location:
            lat, lng = self._parse_location_str(self.shipment.live_location)
            if lat is not None:
                await self.send(text_data=json.dumps({
                    "type":        "location_update",
                    "shipment_id": str(self.shipment_id),
                    "latitude":    lat,
                    "longitude":   lng,
                    "timestamp":   datetime.now(tz=dt_tz.utc).isoformat(),
                    "driver_name": (
                        self.shipment.driver.name if self.shipment.driver else None
                    ),
                    "note":        "last_known_location",
                }))

    async def disconnect(self, close_code):
        # Leave the channel group on disconnect
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        # Clean up rate-limit bucket
        _ping_counts.pop(self.channel_name, None)

        logger.info(
            "WS disconnected — user=%s shipment=%s code=%s",
            getattr(self.user, "user_id", "?"), self.shipment_id, close_code,
        )

    # ------------------------------------------------------------------ #
    # Incoming messages (only drivers may push)                             #
    # ------------------------------------------------------------------ #

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket frames."""

        # Non-driver roles are receive-only — silently ignore any sends
        if not self.is_driver_role:
            await self._send_error("You are not authorised to push location updates.")
            return

        # Rate limit check
        if _is_rate_limited(self.channel_name):
            # Drop silently — don't disconnect the driver, just skip this ping
            logger.debug(
                "Rate limit hit — dropping ping from driver %s on shipment %s",
                getattr(self.driver, "driver_id", "?"), self.shipment_id,
            )
            return

        # Parse the incoming JSON frame
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            await self._send_error("Invalid JSON payload.")
            return

        msg_type = data.get("type")
        if msg_type != "location":
            await self._send_error(f"Unknown message type '{msg_type}'. Expected 'location'.")
            return

        # Validate coordinates
        lat = data.get("latitude")
        lng = data.get("longitude")
        if not self._valid_coordinates(lat, lng):
            await self._send_error(
                "Invalid coordinates. latitude must be −90..90, longitude −180..180."
            )
            return

        location_str = f"{lat},{lng}"
        timestamp    = datetime.now(tz=dt_tz.utc).isoformat()

        # Persist to DB asynchronously
        await _persist_location(
            self.shipment_id,
            getattr(self.driver, "driver_id", None),
            location_str,
        )

        # Broadcast to every subscriber in the group
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type":        "broadcast_location",   # maps to broadcast_location() below
                "shipment_id": str(self.shipment_id),
                "latitude":    lat,
                "longitude":   lng,
                "timestamp":   timestamp,
                "driver_name": self.driver.name if self.driver else None,
            },
        )

    # ------------------------------------------------------------------ #
    # Channel layer event handlers                                          #
    # ------------------------------------------------------------------ #

    async def broadcast_location(self, event):
        """
        Called by the channel layer when group_send() fires a 'broadcast_location' event.
        Forwards the payload to the connected WebSocket client.
        """
        await self.send(text_data=json.dumps({
            "type":        "location_update",
            "shipment_id": event["shipment_id"],
            "latitude":    event["latitude"],
            "longitude":   event["longitude"],
            "timestamp":   event["timestamp"],
            "driver_name": event.get("driver_name"),
        }))

    # ------------------------------------------------------------------ #
    # Private helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_token(query_string: str) -> str | None:
        """Extract ?token=<value> from the raw query string."""
        for part in query_string.split("&"):
            if part.startswith("token="):
                return part.split("=", 1)[1] or None
        return None

    @staticmethod
    def _parse_location_str(location_str: str) -> tuple[float | None, float | None]:
        """Parse 'lat,lng' string.  Returns (None, None) on failure."""
        try:
            parts = location_str.split(",")
            return float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            return None, None

    @staticmethod
    def _valid_coordinates(lat, lng) -> bool:
        """Basic range check for GPS coordinates."""
        try:
            return (-90 <= float(lat) <= 90) and (-180 <= float(lng) <= 180)
        except (TypeError, ValueError):
            return False

    async def _send_error(self, message: str) -> None:
        """Send a structured error frame to this specific client."""
        await self.send(text_data=json.dumps({
            "type":    "error",
            "message": message,
        }))