"""
B2B Tracking Application - API Views
======================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

All views are DRF-based.  Authentication uses JWT (djangorestframework-simplejwt).
RBAC is enforced through custom permission classes at the view level — never
trust the frontend for role decisions.

Module → View mapping:
  Module 1  → LoginView, CompanyViewSet, UserViewSet
  Module 2  → WarehouseViewSet, ProductViewSet, ClientViewSet, RouteViewSet
  Module 3  → OrderViewSet  (create / list / status-update / items)
  Module 4  → DriverViewSet, ShipmentViewSet  (pod / status / location)
  Module 5  → ReturnViewSet  (initiate / approve / list)
  Module 6  → InventoryLogView
  Module 7  → NotificationViewSet, AuditLogView

Required pip packages:
    djangorestframework
    djangorestframework-simplejwt
    django-filter
"""

import json
from django.db import transaction
from django.utils import timezone

from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.tokens import RefreshToken

from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    Admin, AuditLog, Client, Company, Driver, InventoryLog,
    Manager, Notification, Order, OrderItem, Payment,
    Product, ReturnedItem, ReturnedOrder, Route,
    Shipment, User, Warehouse,
)
from .serializers import (
    AdminSerializer, AuditLogSerializer, ClientSerializer, CompanySerializer,
    DriverSerializer, InventoryLogSerializer, LoginSerializer,
    ManagerSerializer, NotificationSerializer, OrderCreateSerializer, OrderItemSerializer,
    OrderSerializer, PaymentSerializer, ProductSerializer,
    ReturnedOrderSerializer, ReturnedItemSerializer, RouteSerializer,
    ShipmentSerializer, UserCreateSerializer, UserSerializer,
    WarehouseSerializer,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _issue_tokens(user: User) -> dict:
    """Return a fresh JWT access + refresh pair for *user*."""
    refresh = RefreshToken()
    refresh["user_id"]  = str(user.user_id)
    refresh["role"]     = user.role
    refresh["company"]  = str(user.company_id)
    return {
        "refresh": str(refresh),
        "access":  str(refresh.access_token),
    }


from django.core.serializers.json import DjangoJSONEncoder

def _write_audit(user, action: str, module: str, reference_id, old=None, new=None):
    """
    Append one immutable row to AuditLog.
    Call inside the same atomic() block as the mutation being logged.
    """
    AuditLog.objects.create(
        user=user,
        action=action,
        module=module,
        reference_id=reference_id,
        old_value=json.dumps(old or {}, cls=DjangoJSONEncoder),
        new_value=json.dumps(new or {}, cls=DjangoJSONEncoder),
    )


# ===========================================================================
# Custom Permission Classes  (RBAC — enforced at middleware level)
# ===========================================================================

class IsAdmin(BasePermission):
    """Only users with role=Admin may proceed."""
    message = "Admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and hasattr(request.user, "is_admin")
            and request.user.is_admin
        )


class IsAdminOrManager(BasePermission):
    """Admin or Manager roles allowed."""
    message = "Admin or Manager access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and hasattr(request.user, "role")
            and request.user.role in (User.Role.ADMIN, User.Role.MANAGER)
        )


class IsDriver(BasePermission):
    """Driver-only actions (GPS ping, POD upload, status update)."""
    message = "Driver access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and hasattr(request.user, "is_driver")
            and request.user.is_driver
        )


class IsAdminManagerOrDriver(BasePermission):
    """Admin, Manager, or Driver — used for shipment reads."""
    message = "Insufficient role."

    def has_permission(self, request, view):
        return bool(
            request.user
            and hasattr(request.user, "role")
            and request.user.role in (User.Role.ADMIN, User.Role.MANAGER, User.Role.DRIVER)
        )


class IsClientUser(BasePermission):
    """Client role only."""
    message = "Client access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and hasattr(request.user, "is_client")
            and request.user.is_client
        )


class IsAdminManagerOrClient(BasePermission):
    """Used for order reads — Admins, Managers, and Clients all need access."""
    message = "Insufficient role."

    def has_permission(self, request, view):
        return bool(
            request.user
            and hasattr(request.user, "role")
            and request.user.role in (User.Role.ADMIN, User.Role.MANAGER, User.Role.CLIENT)
        )


# ===========================================================================
# Mixin — enforce company-scoped querysets (multi-tenant isolation)
# ===========================================================================

class CompanyScopedMixin:
    """
    Automatically scopes every queryset to request.user.company.
    Prevents Company A from reading or mutating Company B's data.
    Override get_queryset() in the subclass if you need extra filters.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request.user, "company_id"):
            qs = qs.filter(company=self.request.user.company)
        return qs

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)


# ===========================================================================
# MODULE 1 — User Management & Authentication (IAM)
# ===========================================================================

class LoginView(APIView):
    """
    POST /api/auth/login
    Accepts { email, password }.
    Returns { access, refresh } JWT pair on success.

    Security:
      - Uses User.verify_password() which wraps Django's check_password().
      - Updates last_login on success.
      - Returns generic 401 on any failure to avoid user enumeration.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email    = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        try:
            user = User.objects.select_related("company").get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.verify_password(password):
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Stamp last login
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        tokens = _issue_tokens(user)
        return Response(
            {
                "user": {
                    "user_id": str(user.user_id),
                    "name":    user.name,
                    "email":   user.email,
                    "role":    user.role,
                    "company": str(user.company_id),
                },
                **tokens,
            },
            status=status.HTTP_200_OK,
        )


class CompanyViewSet(viewsets.ModelViewSet):
    """
    POST   /api/companies          → Create company  (public — used during onboarding)
    GET    /api/companies/{id}     → View own company details  (Admin only after login)
    PUT    /api/companies/{id}     → Update own company  (Admin only)

    Multi-tenant note: A company can only see / edit itself.
    """
    queryset         = Company.objects.all()
    serializer_class = CompanySerializer

    def get_permissions(self):
        if self.action in ("create", "create_admin"):
            return [AllowAny()]          # Public — onboarding
        return [IsAuthenticated(), IsAdmin()]

    def get_queryset(self):
        if self.action in ("create_admin", "create"):
            return Company.objects.all()
        # Admins can only see their own company
        if hasattr(self.request, "user") and hasattr(self.request.user, "company_id"):
            return Company.objects.filter(pk=self.request.user.company_id)
        return Company.objects.none()

    def perform_create(self, serializer):
        company = serializer.save()
        _write_audit(None, "CREATE", "company", company.company_id, new=serializer.data)

    def perform_update(self, serializer):
        old = CompanySerializer(self.get_object()).data
        company = serializer.save()
        _write_audit(self.request.user, "UPDATE", "company", company.company_id,
                     old=old, new=serializer.data)

    @action(detail=True, methods=["post"], url_path="create_admin", permission_classes=[AllowAny])
    @transaction.atomic
    def create_admin(self, request, pk=None):
        company = self.get_object()

        if Admin.objects.filter(company=company).exists():
            raise ValidationError({"detail": "An Admin has already been created for this company."})

        name = request.data.get("name")
        email = request.data.get("email")
        password = request.data.get("password")
        phone = request.data.get("phone", "")

        if not all([name, email, password]):
            raise ValidationError({"detail": "Fields 'name', 'email', and 'password' are required."})

        # Create Platform User
        user = User.objects.create(
            company=company,
            name=name,
            email=email,
            phone=phone,
            role=User.Role.ADMIN
        )
        user.set_password(password)
        user.save()

        # Create Admin Profile
        admin_profile = Admin.objects.create(
            company=company,
            user=user
        )

        _write_audit(user, "CREATE", "admin", admin_profile.admin_id, new={"user": str(user.user_id)})

        return Response({
            "detail": "Admin created successfully.",
            "admin": AdminSerializer(admin_profile).data
        }, status=status.HTTP_201_CREATED)


class UserViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    POST   /api/users              → Create user       (Admin / Manager)
    GET    /api/users/{id}         → Get user detail   (Admin / Manager)
    PUT    /api/users/{id}         → Update user       (Admin / Manager)
    DELETE /api/users/{id}         → Deactivate user   (Admin only)

    Security:
      - Drivers cannot access /api/users at all (checked by IsAdminOrManager).
      - A Manager cannot promote another user to Admin or delete an Admin.
      - Passwords are never returned in responses (write_only in serializer).
    """
    queryset = User.objects.all()

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated(), IsAdminOrManager()]

    def perform_create(self, serializer):
        # Enforce company scoping
        user = serializer.save(company=self.request.user.company)
        _write_audit(self.request.user, "CREATE", "user", user.user_id,
                     new={"email": user.email, "role": user.role})

    def perform_destroy(self, instance):
        # Soft delete — never hard-delete a user for audit trail
        if instance.is_admin and not self.request.user.is_admin:
            raise PermissionDenied("Only an Admin can deactivate another Admin.")
        old_active = instance.is_active
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        _write_audit(self.request.user, "DELETE", "user", instance.user_id,
                     old={"is_active": old_active}, new={"is_active": False})

    def perform_update(self, serializer):
        old = UserSerializer(self.get_object()).data
        user = serializer.save()
        _write_audit(self.request.user, "UPDATE", "user", user.user_id,
                     old=old, new=UserSerializer(user).data)


class ManagerViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    CRUD /api/managers — Only Admins or Managers can list / retrieve.
    Only Admins can CREATE managers.
    """
    queryset = Manager.objects.select_related("user", "company", "created_by_admin", "supervisor")
    serializer_class = ManagerSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsAdmin()]  # Admin adds new managers
        return [IsAuthenticated(), IsAdminOrManager()]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        POST /api/managers/
        Body: { name, email, password, phone, supervisor (optional UUID) }
        Only Admin of the company can add new managers.
        """
        name = request.data.get("name")
        email = request.data.get("email")
        password = request.data.get("password")
        phone = request.data.get("phone", "")
        supervisor_id = request.data.get("supervisor")

        if not all([name, email, password]):
            raise ValidationError({"detail": "Fields 'name', 'email', and 'password' are required."})

        company = request.user.company

        # Ensure supervisor is in same company if provided
        supervisor = None
        if supervisor_id:
            try:
                supervisor = Manager.objects.get(pk=supervisor_id, company=company)
            except Manager.DoesNotExist:
                raise ValidationError({"supervisor": "Supervisor manager not found in your company."})

        # Ensure requesting user has an Admin profile
        try:
            admin_profile = request.user.admin_profile
        except Admin.DoesNotExist:
            raise ValidationError({"detail": "Only users with an Admin profile can create managers."})

        # Create Platform User
        user = User.objects.create(
            company=company,
            name=name,
            email=email,
            phone=phone,
            role=User.Role.MANAGER
        )
        user.set_password(password)
        user.save()

        # Create Manager profile
        manager_profile = Manager.objects.create(
            company=company,
            user=user,
            created_by_admin=admin_profile,
            supervisor=supervisor
        )

        _write_audit(request.user, "CREATE", "manager", manager_profile.manager_id,
                     new={"user": str(user.user_id), "supervisor": str(supervisor_id) if supervisor_id else None})

        return Response(ManagerSerializer(manager_profile).data, status=status.HTTP_201_CREATED)


# ===========================================================================
# MODULE 2 — Catalog & Entities Management (MDM)
# ===========================================================================

class WarehouseViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    CRUD /api/warehouses
    Only Admin / Manager may create or modify warehouses.
    All roles within the same company may read.
    """
    queryset           = Warehouse.objects.all()
    serializer_class   = WarehouseSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ["warehouse_name", "address"]

    def perform_create(self, serializer):
        wh = serializer.save(company=self.request.user.company)
        _write_audit(self.request.user, "CREATE", "warehouse", wh.warehouse_id, new=serializer.data)

    def perform_update(self, serializer):
        old = WarehouseSerializer(self.get_object()).data
        wh  = serializer.save()
        _write_audit(self.request.user, "UPDATE", "warehouse", wh.warehouse_id,
                     old=old, new=WarehouseSerializer(wh).data)

    def perform_destroy(self, instance):
        old = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        _write_audit(self.request.user, "DELETE", "warehouse", instance.warehouse_id,
                     old=old, new={"is_active": False})


class ProductViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    CRUD /api/products
    Only Admin / Manager may write.
    GET /api/products/{id}/stock  → quick stock snapshot (all auth roles).

    Concurrency note: stock_available changes must NEVER happen here directly.
    All stock mutations flow through Module 6 (InventoryLog) using
    select_for_update() inside atomic().
    """
    queryset           = Product.objects.select_related("warehouse")
    serializer_class   = ProductSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields   = ["warehouse", "is_active"]
    search_fields      = ["product_name", "sku_code"]

    @action(detail=True, methods=["get"], url_path="stock",
            permission_classes=[IsAuthenticated])
    def stock(self, request, pk=None):
        """GET /api/products/{id}/stock — live stock snapshot."""
        product = self.get_object()
        return Response({
            "product_id":      str(product.product_id),
            "product_name":    product.product_name,
            "stock_available": product.stock_available,
            "reorder_level":   product.reorder_level,
            "needs_reorder":   product.needs_reorder,
        })

    def perform_create(self, serializer):
        product = serializer.save(company=self.request.user.company)
        _write_audit(self.request.user, "CREATE", "product", product.product_id,
                     new=serializer.data)

    def perform_update(self, serializer):
        old     = ProductSerializer(self.get_object()).data
        product = serializer.save()
        _write_audit(self.request.user, "UPDATE", "product", product.product_id,
                     old=old, new=ProductSerializer(product).data)

    def perform_destroy(self, instance):
        old = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        _write_audit(self.request.user, "DELETE", "product", instance.product_id,
                     old=old, new={"is_active": False})


class ClientViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """CRUD /api/clients — Admin / Manager only."""
    queryset           = Client.objects.all()
    serializer_class   = ClientSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ["client_name", "email", "phone"]

    def perform_create(self, serializer):
        client = serializer.save(company=self.request.user.company)
        _write_audit(self.request.user, "CREATE", "client", client.client_id, new=serializer.data)

    def perform_update(self, serializer):
        old    = ClientSerializer(self.get_object()).data
        client = serializer.save()
        _write_audit(self.request.user, "UPDATE", "client", client.client_id,
                     old=old, new=ClientSerializer(client).data)

    def perform_destroy(self, instance):
        old = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        _write_audit(self.request.user, "DELETE", "client", instance.client_id,
                     old=old, new={"is_active": False})


class RouteViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """CRUD /api/routes — Admin / Manager only."""
    queryset           = Route.objects.all()
    serializer_class   = RouteSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ["start_location", "end_location"]

    def perform_create(self, serializer):
        route = serializer.save(company=self.request.user.company)
        _write_audit(self.request.user, "CREATE", "route", route.route_id, new=serializer.data)

    def perform_update(self, serializer):
        old   = RouteSerializer(self.get_object()).data
        route = serializer.save()
        _write_audit(self.request.user, "UPDATE", "route", route.route_id,
                     old=old, new=RouteSerializer(route).data)

    def perform_destroy(self, instance):
        old = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        _write_audit(self.request.user, "DELETE", "route", instance.route_id,
                     old=old, new={"is_active": False})


# ===========================================================================
# MODULE 3 — Order Management
# ===========================================================================

class OrderViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    POST   /api/orders                          → Create order with items
    GET    /api/orders                          → List orders (with filters)
    GET    /api/orders/{id}                     → Order detail
    PUT    /api/orders/{id}/status              → Update order status
    GET    /api/orders/{id}/items               → List items for an order

    Security:
      - total_amount is always computed on the backend via Order.recalculate_total().
      - Order creation wrapped in transaction.atomic() so a failed OrderItem
        insertion rolls back the entire order.
      - Clients may only view their own orders (filtered by client user).
    """
    queryset        = Order.objects.select_related("client").prefetch_related("items")
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status", "payment_status", "client"]
    ordering_fields  = ["ordered_at", "total_amount"]

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    def get_permissions(self):
        if self.action in ("update_status",):
            return [IsAuthenticated(), IsAdminOrManager()]
        if self.action in ("destroy",):
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated(), IsAdminManagerOrClient()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Clients only see their own company's orders that belong to them
        if user.is_client:
            # Assumes a Client record shares email with User record
            try:
                client = Client.objects.get(email=user.email, company=user.company)
                qs = qs.filter(client=client)
            except Client.DoesNotExist:
                return qs.none()
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        POST /api/orders
        Expects: { client, items: [{ product, quantity }] }
        total_amount is calculated server-side — frontend value is ignored.
        Wrapped in atomic() so a bad item rolls back the whole order.
        """
        serializer = OrderCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        order = serializer.save(company=request.user.company)
        order.recalculate_total()

        _write_audit(request.user, "CREATE", "order", order.order_id,
                     new={"client": str(order.client_id), "total_amount": str(order.total_amount)})

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"], url_path="status",
            permission_classes=[IsAuthenticated, IsAdminOrManager])
    @transaction.atomic
    def update_status(self, request, pk=None):
        """
        PUT /api/orders/{id}/status
        Body: { status: "Confirmed" }

        Enforces the order state machine:
          Pending → Confirmed → Packed → Dispatched → Delivered
          Any state → Cancelled  (Admin / Manager only)
          Delivered → Returned   (via Module 5 return flow)
        """
        order = self.get_object()

        # Valid forward transitions
        TRANSITIONS = {
            Order.Status.PENDING:    [Order.Status.CONFIRMED,  Order.Status.CANCELLED],
            Order.Status.CONFIRMED:  [Order.Status.PACKED,     Order.Status.CANCELLED],
            Order.Status.PACKED:     [Order.Status.DISPATCHED],
            Order.Status.DISPATCHED: [Order.Status.DELIVERED],
            Order.Status.DELIVERED:  [Order.Status.RETURNED],
            Order.Status.RETURNED:   [],
            Order.Status.CANCELLED:  [],
        }

        new_status = request.data.get("status")
        if not new_status:
            raise ValidationError({"status": "This field is required."})

        allowed = TRANSITIONS.get(order.status, [])
        if new_status not in allowed:
            raise ValidationError(
                {"status": f"Cannot transition from '{order.status}' to '{new_status}'. "
                           f"Allowed: {allowed}"}
            )

        old_status = order.status
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])

        if new_status == Order.Status.CANCELLED and old_status != Order.Status.CANCELLED:
            for item in order.items.all():
                product = Product.objects.select_for_update().get(pk=item.product_id)
                product.stock_available += item.quantity
                product.save(update_fields=["stock_available", "updated_at"])
                InventoryLog.objects.create(
                    product=product,
                    warehouse=product.warehouse,
                    change_type=InventoryLog.ChangeType.RETURN,
                    quantity=item.quantity,
                    reference_id=order.order_id,
                )

        _write_audit(request.user, "UPDATE", "order", order.order_id,
                     old={"status": old_status}, new={"status": new_status})

        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["get"], url_path="items",
            permission_classes=[IsAuthenticated, IsAdminManagerOrClient])
    def items(self, request, pk=None):
        """GET /api/orders/{id}/items — list all line items for one order."""
        order = self.get_object()
        serializer = OrderItemSerializer(order.items.all(), many=True)
        return Response(serializer.data)


# ===========================================================================
# MODULE 4 — Logistics, Driver App & Live Tracking
# ===========================================================================

class DriverViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    CRUD /api/drivers — Admin / Manager write, all roles read.
    GET /api/drivers/{id}/location → current GPS ping.
    """
    queryset           = Driver.objects.all()
    serializer_class   = DriverSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields   = ["is_available", "is_active"]
    search_fields      = ["name", "phone", "license_no"]

    @action(detail=True, methods=["get"], url_path="location",
            permission_classes=[IsAuthenticated])
    def location(self, request, pk=None):
        """GET /api/drivers/{id}/location — last known GPS position."""
        driver = self.get_object()
        return Response({
            "driver_id":        str(driver.driver_id),
            "name":             driver.name,
            "current_location": driver.current_location,
        })

    def perform_create(self, serializer):
        kwargs = {"company": self.request.user.company}
        if hasattr(self.request.user, "manager_profile"):
            kwargs["created_by_manager"] = self.request.user.manager_profile
        driver = serializer.save(**kwargs)
        _write_audit(self.request.user, "CREATE", "driver", driver.driver_id,
                     new={"name": driver.name, "license_no": driver.license_no})

    def perform_update(self, serializer):
        old    = DriverSerializer(self.get_object()).data
        driver = serializer.save()
        _write_audit(self.request.user, "UPDATE", "driver", driver.driver_id,
                     old=old, new=DriverSerializer(driver).data)

    def perform_destroy(self, instance):
        old = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        _write_audit(self.request.user, "DELETE", "driver", instance.driver_id,
                     old=old, new={"is_active": False})


class ShipmentViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    CRUD   /api/shipments
    PUT    /api/shipments/{id}/status        → Driver updates delivery status
    POST   /api/shipments/{id}/pod           → Driver uploads Proof of Delivery URL
    PUT    /api/shipments/{id}/location      → Driver pings live GPS (REST fallback;
                                               real-time via WS /ws/shipments/{id}/location)

    Security:
      - POD URL must be a Pre-Signed S3/GCS URL generated by the backend.
      - File type validation happens on the backend before generating the Pre-Signed URL.
      - Drivers can only update shipments assigned to them.
    """
    queryset         = Shipment.objects.select_related("order", "driver", "route",
                                                        "from_warehouse", "to_client")
    serializer_class = ShipmentSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ["status", "driver"]

    def get_permissions(self):
        if self.action in ("update_status", "upload_pod", "update_location"):
            return [IsAuthenticated(), IsAdminManagerOrDriver()]
        return [IsAuthenticated(), IsAdminOrManager()]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        # Drivers only see shipments assigned to them
        if user.is_driver:
            try:
                driver = Driver.objects.get(company=user.company, phone=user.phone, is_active=True)
                return qs.filter(driver=driver)
            except Driver.DoesNotExist:
                return qs.none()
        return qs

    @action(detail=True, methods=["put"], url_path="status")
    @transaction.atomic
    def update_status(self, request, pk=None):
        """
        PUT /api/shipments/{id}/status
        Body: { status: "In_Transit" }
        Only the assigned driver or a Manager/Admin may update.
        """
        shipment = self.get_object()
        user     = request.user

        # Driver can only update their own shipment
        if user.is_driver:
            try:
                driver = Driver.objects.get(company=user.company, phone=user.phone)
                if shipment.driver != driver:
                    raise PermissionDenied("You are not assigned to this shipment.")
            except Driver.DoesNotExist:
                raise PermissionDenied("Driver profile not found.")

        TRANSITIONS = {
            Shipment.Status.READY:      [Shipment.Status.IN_TRANSIT],
            Shipment.Status.IN_TRANSIT: [Shipment.Status.DELIVERED, Shipment.Status.FAILED],
            Shipment.Status.DELIVERED:  [Shipment.Status.RETURNED],
            Shipment.Status.FAILED:     [Shipment.Status.IN_TRANSIT],
            Shipment.Status.RETURNED:   [],
        }

        new_status = request.data.get("status")
        if not new_status:
            raise ValidationError({"status": "This field is required."})

        allowed = TRANSITIONS.get(shipment.status, [])
        if new_status not in allowed:
            raise ValidationError(
                {"status": f"Cannot move from '{shipment.status}' to '{new_status}'. "
                           f"Allowed: {allowed}"}
            )

        old_status = shipment.status
        shipment.status = new_status

        if new_status == Shipment.Status.DELIVERED:
            shipment.actual_delivery_time = timezone.now()
            # Increment driver delivery counter
            if shipment.driver:
                Driver.objects.filter(pk=shipment.driver_id).update(
                    total_orders_delivered=shipment.driver.total_orders_delivered + 1,
                    is_available=True,
                )
            order = shipment.order
            if order.status != Order.Status.DELIVERED:
                order_old_status = order.status
                order.status = Order.Status.DELIVERED
                order.save(update_fields=["status", "updated_at"])
                _write_audit(request.user, "UPDATE", "order", order.order_id,
                             old={"status": order_old_status}, new={"status": Order.Status.DELIVERED})

        elif new_status == Shipment.Status.IN_TRANSIT:
            order = shipment.order
            if order.status != Order.Status.DISPATCHED:
                order_old_status = order.status
                order.status = Order.Status.DISPATCHED
                order.save(update_fields=["status", "updated_at"])
                _write_audit(request.user, "UPDATE", "order", order.order_id,
                             old={"status": order_old_status}, new={"status": Order.Status.DISPATCHED})

        elif new_status == Shipment.Status.FAILED:
            pass # Pending future logistics/stock recovery implementation

        shipment.save()
        _write_audit(request.user, "UPDATE", "shipment", shipment.shipment_id,
                     old={"status": old_status}, new={"status": new_status})

        return Response(ShipmentSerializer(shipment).data)

    @action(detail=True, methods=["post"], url_path="pod")
    def upload_pod(self, request, pk=None):
        """
        POST /api/shipments/{id}/pod
        Body: { pod_url: "<pre-signed-s3-url>" }

        The backend generates a Pre-Signed URL (via boto3 / GCS client) and
        the driver's app uploads directly to Cloud Storage.  This endpoint
        receives the final URL and stores it — keeping backend bandwidth zero.

        Validation handled upstream (file type check before Pre-Signed URL is issued).
        """
        shipment = self.get_object()
        pod_url  = request.data.get("pod_url")

        if not pod_url:
            raise ValidationError({"pod_url": "Pre-signed URL is required."})

        old = {"proof_of_delivery": shipment.proof_of_delivery}
        shipment.proof_of_delivery = pod_url
        shipment.save(update_fields=["proof_of_delivery"])

        _write_audit(request.user, "UPDATE", "shipment", shipment.shipment_id,
                     old=old, new={"proof_of_delivery": pod_url})

        return Response(
            {"detail": "Proof of delivery saved.", "pod_url": pod_url},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "put"], url_path="location",
            permission_classes=[IsAuthenticated])
    def location(self, request, pk=None):
        """
        GET  /api/shipments/{id}/location  → Retrieve live location and route path history.
        PUT  /api/shipments/{id}/location  → REST fallback to update GPS location (assigned Driver only).
        """
        shipment = self.get_object()

        if request.method == "GET":
            # Retrieve location history
            history = []
            if shipment.driver:
                from .models import DriverLocationHistory
                # Fetch route logging points
                history_qs = DriverLocationHistory.objects.filter(driver=shipment.driver)
                if shipment.dispatch_time:
                    history_qs = history_qs.filter(recorded_at__gte=shipment.dispatch_time)
                history = [
                    {
                        "location": item.location,
                        "device_id": item.device_id,
                        "recorded_at": item.recorded_at.isoformat()
                    }
                    for item in history_qs.order_by("recorded_at")[:100]
                ]
            return Response({
                "shipment_id": str(shipment.shipment_id),
                "status": shipment.status,
                "live_location": shipment.live_location,
                "route": {
                    "route_id": str(shipment.route_id) if shipment.route else None,
                    "start_location": shipment.route.start_location if shipment.route else None,
                    "end_location": shipment.route.end_location if shipment.route else None,
                    "distance": shipment.route.distance if shipment.route else None,
                } if shipment.route else None,
                "history": history
            })

        elif request.method == "PUT":
            # Driver can only update their own shipment if they are a driver
            user = request.user
            if user.is_driver:
                try:
                    driver = Driver.objects.get(company=user.company, phone=user.phone)
                    if shipment.driver != driver:
                        raise PermissionDenied("You are not assigned to this shipment.")
                except Driver.DoesNotExist:
                    raise PermissionDenied("Driver profile not found.")

            lat = request.data.get("latitude")
            lng = request.data.get("longitude")
            device_id = request.data.get("device_id")

            if lat is None or lng is None:
                raise ValidationError({"detail": "latitude and longitude are required."})

            location_str = f"{lat},{lng}"
            shipment.live_location = location_str
            shipment.save(update_fields=["live_location"])

            # Mirror on the driver record and record location log
            if shipment.driver_id:
                driver_qs = Driver.objects.filter(pk=shipment.driver_id)
                if device_id:
                    driver_qs.update(current_location=location_str, device_id=device_id)
                else:
                    driver_qs.update(current_location=location_str)

                from .models import DriverLocationHistory
                DriverLocationHistory.objects.create(
                    driver_id=shipment.driver_id,
                    device_id=device_id or "",
                    location=location_str
                )

            return Response({"live_location": location_str})

    def perform_create(self, serializer):
        shipment = serializer.save(company=self.request.user.company)
        _write_audit(self.request.user, "CREATE", "shipment", shipment.shipment_id,
                     new={"order": str(shipment.order_id), "driver": str(shipment.driver_id)})


# ===========================================================================
# MODULE 5 — Returns & Reverse Logistics
# ===========================================================================

class ReturnViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """
    POST   /api/returns                      → Initiate return (Client or Manager)
    GET    /api/returns                      → List returns    (Admin / Manager)
    GET    /api/returns/{id}                 → Return detail
    PUT    /api/returns/{id}/approve         → Manager/Admin approves return
    PUT    /api/returns/{id}/reject          → Manager/Admin rejects return

    Security:
      - A client can only return their own orders.
      - Return quantity per item must not exceed original order item quantity
        (validated in ReturnedOrderSerializer).
    """
    queryset         = ReturnedOrder.objects.select_related("old_order", "client", "driver")
    serializer_class = ReturnedOrderSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ["return_status"]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsAdminManagerOrClient()]
        return [IsAuthenticated(), IsAdminOrManager()]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_client:
            try:
                client = Client.objects.get(email=user.email, company=user.company)
                return qs.filter(client=client)
            except Client.DoesNotExist:
                return qs.none()
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        POST /api/returns
        Body: { old_order, return_reason, items: [{ product, quantity, condition }] }

        Validates:
          1. Order belongs to the requesting client.
          2. Order status is Delivered.
          3. Return quantity ≤ original ordered quantity per product.
        """
        serializer = ReturnedOrderSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        return_obj = serializer.save(company=request.user.company)

        _write_audit(request.user, "CREATE", "return", return_obj.return_id,
                     new={"old_order": str(return_obj.old_order_id)})

        return Response(
            ReturnedOrderSerializer(return_obj).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["put"], url_path="approve",
            permission_classes=[IsAuthenticated, IsAdminOrManager])
    @transaction.atomic
    def approve(self, request, pk=None):
        """PUT /api/returns/{id}/approve — Manager/Admin approves the return."""
        return_obj = self.get_object()

        if return_obj.return_status != ReturnedOrder.ReturnStatus.REQUESTED:
            raise ValidationError(
                {"detail": f"Can only approve a 'Requested' return. "
                           f"Current status: {return_obj.return_status}"}
            )

        old_status = return_obj.return_status
        return_obj.return_status = ReturnedOrder.ReturnStatus.APPROVED
        return_obj.save(update_fields=["return_status"])

        _write_audit(request.user, "UPDATE", "return", return_obj.return_id,
                     old={"return_status": old_status},
                     new={"return_status": ReturnedOrder.ReturnStatus.APPROVED})

        return Response(ReturnedOrderSerializer(return_obj).data)

    @action(detail=True, methods=["put"], url_path="reject",
            permission_classes=[IsAuthenticated, IsAdminOrManager])
    @transaction.atomic
    def reject(self, request, pk=None):
        """PUT /api/returns/{id}/reject — Manager/Admin rejects the return."""
        return_obj = self.get_object()

        if return_obj.return_status != ReturnedOrder.ReturnStatus.REQUESTED:
            raise ValidationError(
                {"detail": f"Can only reject a 'Requested' return. "
                           f"Current status: {return_obj.return_status}"}
            )

        old_status = return_obj.return_status
        return_obj.return_status = ReturnedOrder.ReturnStatus.REJECTED
        return_obj.save(update_fields=["return_status"])

        _write_audit(request.user, "UPDATE", "return", return_obj.return_id,
                     old={"return_status": old_status},
                     new={"return_status": ReturnedOrder.ReturnStatus.REJECTED})

        return Response(ReturnedOrderSerializer(return_obj).data)

    @action(detail=True, methods=["put"], url_path="receive",
            permission_classes=[IsAuthenticated, IsAdminOrManager])
    @transaction.atomic
    def receive(self, request, pk=None):
        """PUT /api/returns/{id}/receive — Manager/Admin marks return as Received."""
        return_obj = self.get_object()

        if return_obj.return_status not in (ReturnedOrder.ReturnStatus.APPROVED, ReturnedOrder.ReturnStatus.PICKED_UP):
            raise ValidationError(
                {"detail": f"Can only receive an Approved or Picked_Up return. "
                           f"Current status: {return_obj.return_status}"}
            )

        old_status = return_obj.return_status
        return_obj.return_status = ReturnedOrder.ReturnStatus.RETURNED
        return_obj.save(update_fields=["return_status"])

        # Restore stock logic
        for item in return_obj.items.all():
            product = item.product
            if item.condition == ReturnedItem.Condition.GOOD and product.warehouse:
                product_locked = Product.objects.select_for_update().get(pk=product.pk)
                product_locked.stock_available += item.quantity
                product_locked.save(update_fields=["stock_available", "updated_at"])

                InventoryLog.objects.create(
                    product=product_locked,
                    warehouse=product_locked.warehouse,
                    change_type=InventoryLog.ChangeType.RETURN,
                    quantity=item.quantity,
                    reference_id=return_obj.return_id,
                )
            elif item.condition == ReturnedItem.Condition.DAMAGED and product.warehouse:
                InventoryLog.objects.create(
                    product=product,
                    warehouse=product.warehouse,
                    change_type=InventoryLog.ChangeType.DAMAGE,
                    quantity=0,
                    reference_id=return_obj.return_id,
                )

        order = return_obj.old_order
        if order.status != Order.Status.RETURNED:
            order_old_status = order.status
            order.status = Order.Status.RETURNED
            order.save(update_fields=["status", "updated_at"])
            _write_audit(request.user, "UPDATE", "order", order.order_id,
                         old={"status": order_old_status}, new={"status": Order.Status.RETURNED})

        _write_audit(request.user, "UPDATE", "return", return_obj.return_id,
                     old={"return_status": old_status},
                     new={"return_status": ReturnedOrder.ReturnStatus.RETURNED})

        return Response(ReturnedOrderSerializer(return_obj).data)


# ===========================================================================
# MODULE 6 — Inventory Management & Stock Sync
# ===========================================================================

class InventoryLogView(CompanyScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/inventory/logs          → List all stock movements (paginated)
    GET  /api/inventory/logs/{id}     → Single log entry

    This endpoint is READ-ONLY.  InventoryLog is append-only;
    all writes are internal (triggered by Modules 3, 4, 5).
    Only Admin / Manager may view.
    """
    queryset           = InventoryLog.objects.select_related("product", "warehouse")
    serializer_class   = InventoryLogSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManager]
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields   = ["change_type", "product", "warehouse"]
    ordering_fields    = ["logged_at"]

    def get_queryset(self):
        """Scope to company via product's company FK."""
        return InventoryLog.objects.filter(
            product__company=self.request.user.company
        ).select_related("product", "warehouse")


# ===========================================================================
# MODULE 7 — System Notifications & Audit Logging
# ===========================================================================

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/notifications          → List notifications for the current user
    PUT  /api/notifications/{id}/read → Mark notification as read
    """
    serializer_class   = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend]
    filterset_fields   = ["is_read", "type"]

    def get_queryset(self):
        # Users only see their own notifications
        return Notification.objects.filter(sent_to=self.request.user)

    @action(detail=True, methods=["put"], url_path="read")
    def mark_read(self, request, pk=None):
        """PUT /api/notifications/{id}/read — flip is_read to True."""
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response(NotificationSerializer(notification).data)


class AuditLogView(viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/audit-logs             → All audit log entries  (Admin only)
    GET  /api/audit-logs/{id}        → Single entry

    Strictly read-only — no create, update, or delete.
    Append happens internally via _write_audit() helper.
    """
    serializer_class   = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ["action", "module"]
    search_fields      = ["module", "action"]
    ordering_fields    = ["created_at"]

    def get_queryset(self):
        # Admins only see audit logs for their own company's users
        return AuditLog.objects.filter(
            user__company=self.request.user.company
        ).select_related("user")


# ==============================================================================
# Module 8 — OTP Generation
# ==============================================================================
import random
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.conf import settings
from .models import OTPVerification

class GenerateOTPView(APIView):
    """
    POST /api/auth/otp/generate/
    Generates a 6-digit OTP, saves it, and sends via SMTP.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Generate 6-digit OTP
        otp_code = f"{random.randint(100000, 999999)}"
        
        # Save to DB
        otp_record = OTPVerification.objects.create(
            email=email,
            otp_code=otp_code
        )
        
        # Send via SMTP
        subject = "Your B2B System OTP Code"
        message = f"Your one-time password (OTP) is: {otp_code}\n\nThis code will expire in 10 minutes."
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as e:
            return Response({"error": f"Failed to send email: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "OTP sent successfully."}, status=status.HTTP_201_CREATED)


class VerifyOTPView(APIView):
    """
    POST /api/auth/otp/verify/
    Verifies the 6-digit OTP for the given email.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        otp_code = request.data.get("otp_code")

        if not email or not otp_code:
            return Response({"error": "Email and OTP code are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Get latest OTP for email
        otp_record = OTPVerification.objects.filter(email=email).order_by("-created_at").first()

        if not otp_record:
            return Response({"error": "No OTP found for this email."}, status=status.HTTP_404_NOT_FOUND)
        
        if not otp_record.is_valid():
            return Response({"error": "OTP has expired or already used."}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_record.otp_code != str(otp_code):
            return Response({"error": "Invalid OTP code."}, status=status.HTTP_400_BAD_REQUEST)

        # Mark as used
        otp_record.is_used = True
        otp_record.save()

        return Response({"message": "OTP verified successfully."}, status=status.HTTP_200_OK)