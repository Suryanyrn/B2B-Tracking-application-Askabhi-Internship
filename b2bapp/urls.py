"""
B2B Tracking Application - URL Configuration
=============================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

All API routes are prefixed with /api/.
WebSocket routes (live tracking) live in routing.py and are registered
separately via Django Channels.

Route map (matches TRS spec exactly):
─────────────────────────────────────────────────────────────────────────────
MODULE 1 — Identity & Auth
  POST    /api/auth/login                         LoginView
  POST    /api/auth/token/refresh                 TokenRefreshView  (simplejwt)
  POST    /api/companies/                         CompanyViewSet.create
  GET     /api/companies/{id}/                    CompanyViewSet.retrieve
  PUT     /api/companies/{id}/                    CompanyViewSet.update
  POST    /api/users/                             UserViewSet.create
  GET     /api/users/                             UserViewSet.list
  GET     /api/users/{id}/                        UserViewSet.retrieve
  PUT     /api/users/{id}/                        UserViewSet.update
  DELETE  /api/users/{id}/                        UserViewSet.destroy

MODULE 2 — Master Data (MDM)
  CRUD    /api/warehouses/                        WarehouseViewSet
  CRUD    /api/products/                          ProductViewSet
  GET     /api/products/{id}/stock/               ProductViewSet.stock
  CRUD    /api/clients/                           ClientViewSet
  CRUD    /api/routes/                            RouteViewSet

MODULE 3 — Order Management
  POST    /api/orders/                            OrderViewSet.create
  GET     /api/orders/                            OrderViewSet.list
  GET     /api/orders/{id}/                       OrderViewSet.retrieve
  PUT     /api/orders/{id}/status/                OrderViewSet.update_status
  GET     /api/orders/{id}/items/                 OrderViewSet.items

MODULE 4 — Logistics & Live Tracking
  CRUD    /api/drivers/                           DriverViewSet
  GET     /api/drivers/{id}/location/             DriverViewSet.location
  CRUD    /api/shipments/                         ShipmentViewSet
  PUT     /api/shipments/{id}/status/             ShipmentViewSet.update_status
  POST    /api/shipments/{id}/pod/                ShipmentViewSet.upload_pod
  PUT     /api/shipments/{id}/location/           ShipmentViewSet.update_location
  WS      /ws/shipments/{id}/location/            (channels routing.py)

MODULE 5 — Returns
  POST    /api/returns/                           ReturnViewSet.create
  GET     /api/returns/                           ReturnViewSet.list
  GET     /api/returns/{id}/                      ReturnViewSet.retrieve
  PUT     /api/returns/{id}/approve/              ReturnViewSet.approve
  PUT     /api/returns/{id}/reject/               ReturnViewSet.reject

MODULE 6 — Inventory
  GET     /api/inventory/logs/                    InventoryLogView.list
  GET     /api/inventory/logs/{id}/               InventoryLogView.retrieve

MODULE 7 — Notifications & Audit
  GET     /api/notifications/                     NotificationViewSet.list
  GET     /api/notifications/{id}/                NotificationViewSet.retrieve
  PUT     /api/notifications/{id}/read/           NotificationViewSet.mark_read
  GET     /api/audit-logs/                        AuditLogView.list
  GET     /api/audit-logs/{id}/                   AuditLogView.retrieve
─────────────────────────────────────────────────────────────────────────────
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from . import views
from .views import (
    AuditLogView,
    ClientViewSet,
    CompanyViewSet,
    DriverViewSet,
    InventoryLogView,
    LoginView,
    GenerateOTPView,
    VerifyOTPView,
    ManagerViewSet,
    NotificationViewSet,
    OrderViewSet,
    ProductViewSet,
    ReturnViewSet,
    RouteViewSet,
    ShipmentViewSet,
    UserViewSet,
    WarehouseViewSet,
)

# ---------------------------------------------------------------------------
# Router — auto-generates list / detail / extra actions for ViewSets
# ---------------------------------------------------------------------------

router = DefaultRouter()

# Module 1
router.register(r"companies",    CompanyViewSet,      basename="company")
router.register(r"users",        UserViewSet,         basename="user")
router.register(r"managers",     ManagerViewSet,      basename="manager")

# Module 2
router.register(r"warehouses",   WarehouseViewSet,    basename="warehouse")
router.register(r"products",     ProductViewSet,      basename="product")
router.register(r"clients",      ClientViewSet,       basename="client")
router.register(r"routes",       RouteViewSet,        basename="route")

# Module 3
router.register(r"orders",       OrderViewSet,        basename="order")

# Module 4
router.register(r"drivers",      DriverViewSet,       basename="driver")
router.register(r"shipments",    ShipmentViewSet,     basename="shipment")

# Module 5
router.register(r"returns",      ReturnViewSet,       basename="return")

# Module 6
router.register(r"inventory/logs", InventoryLogView,  basename="inventory-log")

# Module 7
router.register(r"notifications", NotificationViewSet, basename="notification")
router.register(r"audit-logs",    AuditLogView,        basename="audit-log")


# ---------------------------------------------------------------------------
# URL Patterns
# ---------------------------------------------------------------------------

urlpatterns = [

    # ------------------------------------------------------------------
    # Module 1 — Authentication
    # POST  /api/auth/login           → issue JWT pair
    # POST  /api/auth/token/refresh   → exchange refresh for new access token
    # ------------------------------------------------------------------
    path(
        "api/auth/login",
        LoginView.as_view(),
        name="auth-login",
    ),
    path(
        "api/auth/token/refresh",
        TokenRefreshView.as_view(),
        name="auth-token-refresh",
    ),
    path(
        "api/auth/otp/generate/",
        GenerateOTPView.as_view(),
        name="auth-otp-generate",
    ),
    path(
        "api/auth/otp/verify/",
        VerifyOTPView.as_view(),
        name="auth-otp-verify",
    ),

    # ------------------------------------------------------------------
    # All router-generated routes (Modules 1–7)
    # ------------------------------------------------------------------
    path("api/", include(router.urls)),
    path("",views.index,name="index"),
]


# ---------------------------------------------------------------------------
# WebSocket routes  (add to your asgi.py / routing.py — shown here as reference)
# ---------------------------------------------------------------------------
#
#  from channels.routing import ProtocolTypeRouter, URLRouter
#  from channels.auth import AuthMiddlewareStack
#  from django.urls import re_path
#  from .consumers import ShipmentLocationConsumer
#
#  websocket_urlpatterns = [
#      re_path(
#          r"ws/shipments/(?P<shipment_id>[0-9a-f-]+)/location/$",
#          ShipmentLocationConsumer.as_asgi(),
#      ),
#  ]
#
#  application = ProtocolTypeRouter({
#      "http": get_asgi_application(),
#      "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
#  })
#
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Auto-generated action URLs produced by the router for quick reference:
#
#   GET/PUT  /api/orders/{id}/status/         → OrderViewSet.update_status
#   GET      /api/orders/{id}/items/          → OrderViewSet.items
#   GET      /api/products/{id}/stock/        → ProductViewSet.stock
#   GET      /api/drivers/{id}/location/      → DriverViewSet.location
#   PUT      /api/shipments/{id}/status/      → ShipmentViewSet.update_status
#   POST     /api/shipments/{id}/pod/         → ShipmentViewSet.upload_pod
#   PUT      /api/shipments/{id}/location/    → ShipmentViewSet.update_location
#   PUT      /api/returns/{id}/approve/       → ReturnViewSet.approve
#   PUT      /api/returns/{id}/reject/        → ReturnViewSet.reject
#   PUT      /api/notifications/{id}/read/    → NotificationViewSet.mark_read
# ---------------------------------------------------------------------------