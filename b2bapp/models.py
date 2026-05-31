"""
B2B Tracking Application - Django Models
=========================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

Module Coverage:
  Module 1 - User Management & Authentication (IAM)   - Company, User
  Module 2 - Catalog & Entities Management (MDM)      - Warehouse, Product, Client, Route
  Module 3 - Order Management                         - Order, OrderItem
  Module 4 - Logistics, Driver App & Live Tracking    - Driver, Shipment
  Module 5 - Returns & Reverse Logistics              - ReturnedOrder, ReturnedItem
  Module 6 - Inventory Management & Stock Sync        - InventoryLog
  Module 7 - System Notifications & Audit Logging     - Notification, AuditLog
"""

import uuid
from django.db import models
from django.contrib.auth.hashers import make_password, check_password as _check_password
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid_pk():
    """Default factory: UUID4 primary key."""
    return uuid.uuid4


# ===========================================================================
# MODULE 1 — User Management & Authentication (IAM)
# ===========================================================================

class Company(models.Model):
    """
    Represents a tenant organisation on the platform.
    Every other record is scoped to a Company via company_id for strict
    multi-tenant isolation (filter(company=request.user.company)).
    """

    company_id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(max_length=255)
    address      = models.TextField()
    email        = models.EmailField(unique=True)
    phone        = models.CharField(max_length=20)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table   = "company"
        ordering   = ["company_name"]
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.company_name


class User(models.Model):
    """
    Platform user.  Passwords are hashed via Django's make_password /
    check_password — NEVER stored in plain text.

    Role controls what APIs the JWT bearer may call (enforced at middleware /
    permission level, not here).
    """

    class Role(models.TextChoices):
        ADMIN   = "Admin",   "Admin"
        MANAGER = "Manager", "Manager"
        DRIVER  = "Driver",  "Driver"
        CLIENT  = "Client",  "Client"

    user_id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company       = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="users")
    name          = models.CharField(max_length=255)
    email         = models.EmailField(unique=True)
    phone         = models.CharField(max_length=20, blank=True)
    # Store ONLY the hash — use set_password() / verify_password() helpers below
    password_hash = models.CharField(max_length=255)
    role          = models.CharField(max_length=10, choices=Role.choices)
    is_active     = models.BooleanField(default=True)
    last_login    = models.DateTimeField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.role})"

    @property
    def is_authenticated(self):
        return True

    # ------------------------------------------------------------------ #
    # Password helpers — wraps Django's built-in hashing utilities         #
    # ------------------------------------------------------------------ #

    def set_password(self, raw_password: str) -> None:
        """Hash *raw_password* and store it.  Call save() afterwards."""
        self.password_hash = make_password(raw_password)

    def verify_password(self, raw_password: str) -> bool:
        """Return True if *raw_password* matches the stored hash."""
        return _check_password(raw_password, self.password_hash)

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def is_driver(self):
        return self.role == self.Role.DRIVER

    @property
    def is_client(self):
        return self.role == self.Role.CLIENT


class Admin(models.Model):
    """
    Admin profile. Linked to a Company and a platform User (Role.ADMIN).
    An Admin is automatically created/assigned to a Company.
    """
    admin_id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company    = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="admin_profile")
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="admin_profile")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin"
        ordering = ["user__name"]

    def __str__(self):
        return f"Admin: {self.user.name} ({self.company.company_name})"


class Manager(models.Model):
    """
    Manager profile. Linked to a Company and a platform User (Role.MANAGER).
    Created by an Admin. Can be supervised by another Manager.
    """
    manager_id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company          = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="managers")
    user             = models.OneToOneField(User, on_delete=models.CASCADE, related_name="manager_profile")
    created_by_admin = models.ForeignKey(Admin, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_managers")
    supervisor       = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name="subordinates")
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "manager"
        ordering = ["user__name"]

    def __str__(self):
        return f"Manager: {self.user.name} ({self.company.company_name})"


# ===========================================================================
# MODULE 2 — Catalog & Entities Management (MDM)
# ===========================================================================

class Warehouse(models.Model):
    """Physical storage location.  Capacity is in units (business-defined)."""

    warehouse_id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company        = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="warehouses")
    warehouse_name = models.CharField(max_length=255)
    address        = models.TextField()
    capacity       = models.PositiveIntegerField(help_text="Max stock units this warehouse can hold")
    is_active      = models.BooleanField(default=True)

    class Meta:
        db_table = "warehouse"
        ordering = ["warehouse_name"]

    def __str__(self):
        return f"{self.warehouse_name} ({self.company})"


class Product(models.Model):
    """
    A sellable / shippable item.

    stock_available is the live count.  All mutations MUST go through
    Module 6 (InventoryLog) and use select_for_update() to prevent
    race conditions.
    """

    product_id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company         = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="products")
    warehouse       = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    product_name    = models.CharField(max_length=255)
    product_version = models.CharField(max_length=50, blank=True)
    sku_code        = models.CharField(max_length=100, unique=True)
    unit_price      = models.DecimalField(max_digits=12, decimal_places=2)
    total_manufactured = models.PositiveIntegerField(default=0)
    stock_available = models.PositiveIntegerField(default=0)
    # When stock_available drops to or below this, fire a reorder alert
    reorder_level   = models.PositiveIntegerField(default=0)
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "product"
        ordering = ["product_name"]

    def __str__(self):
        return f"{self.product_name} [{self.sku_code}]"

    @property
    def needs_reorder(self) -> bool:
        return self.stock_available <= self.reorder_level


class Client(models.Model):
    """
    External business customer that places orders.
    A Client belongs to the same Company as the Manager who manages them
    (multi-tenant: Company A cannot see Company B's clients).
    """

    client_id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company        = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="clients")
    client_name    = models.CharField(max_length=255)
    client_company = models.CharField(max_length=255, blank=True, help_text="Client's own company name")
    address        = models.TextField()
    email          = models.EmailField()
    phone          = models.CharField(max_length=20)
    client_since   = models.DateField(auto_now_add=True)
    is_active      = models.BooleanField(default=True)

    class Meta:
        db_table = "client"
        ordering = ["client_name"]

    def __str__(self):
        return self.client_name


class Route(models.Model):
    """
    Pre-defined delivery path between two locations.
    Used by Shipment to compute ETA.
    """

    route_id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company         = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="routes")
    start_location  = models.CharField(max_length=255)
    end_location    = models.CharField(max_length=255)
    distance        = models.DecimalField(max_digits=10, decimal_places=2, help_text="Distance in km")
    estimated_time  = models.PositiveIntegerField(help_text="Estimated travel time in minutes")
    is_active       = models.BooleanField(default=True)

    class Meta:
        db_table = "route"
        ordering = ["start_location", "end_location"]

    def __str__(self):
        return f"{self.start_location} - {self.end_location} ({self.distance} km)"


# ===========================================================================
# MODULE 3 — Order Management
# ===========================================================================

class Order(models.Model):
    """
    Core revenue transaction.

    total_amount MUST be computed on the backend (sum of OrderItem.total_price).
    NEVER accept a total_amount from the frontend.

    Status transitions are enforced by Module 3 / 5 business logic.
    Use django.db.transaction.atomic() when creating an Order + its OrderItems.
    """

    class Status(models.TextChoices):
        PENDING    = "Pending",    "Pending"
        CONFIRMED  = "Confirmed",  "Confirmed"
        PACKED     = "Packed",     "Packed"
        DISPATCHED = "Dispatched", "Dispatched"
        DELIVERED  = "Delivered",  "Delivered"
        RETURNED   = "Returned",   "Returned"
        CANCELLED  = "Cancelled",  "Cancelled"

    class PaymentStatus(models.TextChoices):
        PENDING = "Pending", "Pending"
        PAID    = "Paid",    "Paid"
        FAILED  = "Failed",  "Failed"

    order_id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company        = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="orders")
    client         = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="orders")
    ordered_at     = models.DateTimeField(default=timezone.now)
    status         = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    total_amount   = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "order"
        ordering = ["-ordered_at"]

    def __str__(self):
        return f"Order {self.order_id} | {self.client} | {self.status}"

    def recalculate_total(self) -> None:
        """
        Recompute total_amount from child OrderItems.
        Call inside atomic() after saving all items.
        """
        from django.db.models import Sum
        result = self.items.aggregate(total=Sum("total_price"))
        self.total_amount = result["total"] or 0
        self.save(update_fields=["total_amount", "updated_at"])


class OrderItem(models.Model):
    """
    A single product line within an Order.
    total_price = quantity × unit_price (computed on save, not from frontend).
    """

    order_item_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order         = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product       = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity      = models.PositiveIntegerField()
    unit_price    = models.DecimalField(max_digits=12, decimal_places=2)
    total_price   = models.DecimalField(max_digits=14, decimal_places=2, editable=False, default=0)

    class Meta:
        db_table = "order_item"

    def save(self, *args, **kwargs):
        # Always derive total_price on the backend
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}× {self.product} (Order {self.order_id})"


# ===========================================================================
# MODULE 4 — Logistics, Driver App & Live Tracking
# ===========================================================================

class Driver(models.Model):
    """
    Company employee who physically delivers shipments.
    current_location is updated in real-time via WebSocket / MQTT.
    """

    driver_id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company                = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="drivers")
    created_by_manager     = models.ForeignKey(Manager, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_drivers")
    name                   = models.CharField(max_length=255)
    phone                  = models.CharField(max_length=20)
    # Stored in Cloud Storage (S3/GCS); only the URL is kept in DB
    photo                  = models.URLField(blank=True)
    license_no             = models.CharField(max_length=50, unique=True)
    is_available           = models.BooleanField(default=True)
    is_active              = models.BooleanField(default=True)
    total_orders_delivered = models.PositiveIntegerField(default=0)
    joined_at              = models.DateField(auto_now_add=True)
    # Updated via WS /ws/shipments/{id}/location — stored as "lat,lng" string
    current_location       = models.CharField(max_length=100, blank=True,
                                              help_text='Comma-separated "latitude,longitude"')

    class Meta:
        db_table = "driver"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.license_no})"


class Shipment(models.Model):
    """
    Physical dispatch of an Order from a Warehouse to a Client.

    Live location is updated through the WebSocket endpoint
    WS /ws/shipments/{id}/location and persisted to live_location.

    proof_of_delivery stores a Pre-Signed URL from Cloud Storage
    (never a raw file path — see Module 4 security notes).
    """

    class Status(models.TextChoices):
        READY      = "Ready",      "Ready"
        IN_TRANSIT = "In_Transit", "In Transit"
        DELIVERED  = "Delivered",  "Delivered"
        FAILED     = "Failed",     "Failed"
        RETURNED   = "Returned",   "Returned"

    shipment_id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company                = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="shipments")
    order                  = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="shipment")
    from_warehouse         = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="outbound_shipments")
    to_client              = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="shipments")
    driver                 = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name="shipments")
    route                  = models.ForeignKey(Route, on_delete=models.SET_NULL, null=True, blank=True, related_name="shipments")
    dispatch_time          = models.DateTimeField(null=True, blank=True)
    estimated_delivery_time = models.DateTimeField(null=True, blank=True)
    actual_delivery_time   = models.DateTimeField(null=True, blank=True)
    # Real-time field — updated by WebSocket consumer on every driver ping
    live_location          = models.CharField(max_length=100, blank=True,
                                              help_text='Current "latitude,longitude" of the shipment')
    status                 = models.CharField(max_length=15, choices=Status.choices, default=Status.READY)
    # Pre-Signed Cloud Storage URL for photos / signatures
    proof_of_delivery      = models.URLField(blank=True,
                                             help_text="Pre-signed S3/GCS URL for POD image or signature")
    delivery_attempts      = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "shipment"
        ordering = ["-dispatch_time"]

    def __str__(self):
        return f"Shipment {self.shipment_id} | Order {self.order_id} | {self.status}"


# ===========================================================================
# MODULE 5 — Returns & Reverse Logistics
# ===========================================================================

class ReturnedOrder(models.Model):
    """
    Header for a return request.
    A return can only be initiated against a Delivered Order
    (enforced in business logic / serializer validation).
    """

    class ReturnStatus(models.TextChoices):
        REQUESTED  = "Requested",  "Requested"
        APPROVED   = "Approved",   "Approved"
        PICKED_UP  = "Picked_Up",  "Picked Up"
        RETURNED   = "Returned",   "Returned"
        REJECTED   = "Rejected",   "Rejected"

    return_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    old_order     = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="returns")
    client        = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="returns")
    company       = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="returns")
    driver        = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="return_pickups")
    return_reason = models.TextField()
    return_status = models.CharField(max_length=15, choices=ReturnStatus.choices,
                                     default=ReturnStatus.REQUESTED)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "returned_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Return {self.return_id} | Order {self.old_order_id} | {self.return_status}"


class ReturnedItem(models.Model):
    """
    A single product line within a Return.
    quantity MUST NOT exceed the original OrderItem.quantity — validated in serializer.
    """

    class Condition(models.TextChoices):
        GOOD    = "Good",    "Good"
        DAMAGED = "Damaged", "Damaged"
        EXPIRED = "Expired", "Expired"
        OTHER   = "Other",   "Other"

    return_item_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_order   = models.ForeignKey(ReturnedOrder, on_delete=models.CASCADE, related_name="items")
    product        = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="returned_items")
    quantity       = models.PositiveIntegerField()
    condition      = models.CharField(max_length=10, choices=Condition.choices, default=Condition.GOOD)

    class Meta:
        db_table = "returned_item"

    def __str__(self):
        return f"{self.quantity}× {self.product} ({self.condition})"


# ===========================================================================
# MODULE 6 — Inventory Management & Stock Sync
#   NOTE: Product.stock_available updates MUST use:
#         Product.objects.select_for_update().filter(pk=...) inside atomic()
#         to prevent race conditions on concurrent orders.
# ===========================================================================

class InventoryLog(models.Model):
    """
    Immutable, append-only ledger of every stock movement.
    Created automatically when:
      - An Order is dispatched   (OUT)
      - A Return is confirmed    (RETURN / IN)
      - Damage is recorded       (DAMAGE)
    No UPDATE or DELETE permissions should ever be granted on this table.
    """

    class ChangeType(models.TextChoices):
        IN     = "IN",     "Stock In"
        OUT    = "OUT",    "Stock Out"
        RETURN = "RETURN", "Return"
        DAMAGE = "DAMAGE", "Damage"

    log_id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product      = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="inventory_logs")
    warehouse    = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="inventory_logs")
    change_type  = models.CharField(max_length=10, choices=ChangeType.choices)
    quantity     = models.IntegerField(help_text="Positive = stock added, Negative = stock deducted")
    # ID of the triggering record (e.g. Shipment UUID or ReturnedOrder UUID)
    reference_id = models.UUIDField(help_text="UUID of the Shipment, ReturnedOrder, or other source record")
    logged_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_log"
        ordering = ["-logged_at"]
        # Prevent accidental migrations from adding mutable operations
        # (enforce append-only at DB permission level separately)

    def __str__(self):
        return f"[{self.change_type}] {self.quantity} × {self.product} @ {self.logged_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        # Block any updates — log entries are write-once
        if self.pk and InventoryLog.objects.filter(pk=self.pk).exists():
            raise PermissionError("InventoryLog records are immutable and cannot be updated.")
        super().save(*args, **kwargs)


# ===========================================================================
# MODULE 3 (extension) — Payment
# ===========================================================================

class Payment(models.Model):
    """
    Payment record linked to an Order.
    Kept separate from Order so multiple payment attempts can be tracked.
    """

    class PaymentMethod(models.TextChoices):
        CASH   = "Cash",   "Cash"
        BANK   = "Bank",   "Bank Transfer"
        CARD   = "Card",   "Card"
        UPI    = "UPI",    "UPI"
        CREDIT = "Credit", "Credit / Net 30"

    class PaymentStatus(models.TextChoices):
        PENDING   = "Pending",   "Pending"
        COMPLETED = "Completed", "Completed"
        FAILED    = "Failed",    "Failed"
        REFUNDED  = "Refunded",  "Refunded"

    payment_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order          = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    amount         = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices,
                                      default=PaymentStatus.PENDING)
    paid_at        = models.DateTimeField(null=True, blank=True)
    transaction_ref = models.CharField(max_length=255, blank=True,
                                       help_text="Gateway / bank transaction reference")

    class Meta:
        db_table = "payment"
        ordering = ["-paid_at"]

    def __str__(self):
        return f"Payment {self.payment_id} | {self.payment_status} | {self.amount}"


# ===========================================================================
# MODULE 7 — System Notifications & Audit Logging
# ===========================================================================

class Notification(models.Model):
    """
    Pushed to users via FCM (mobile), SendGrid (email), or Twilio (SMS).
    Actual dispatch is handled asynchronously by Celery workers.
    """

    class NotificationType(models.TextChoices):
        ORDER    = "Order",    "Order"
        DISPATCH = "Dispatch", "Dispatch"
        DELAY    = "Delay",    "Delay"
        TRACKING = "Tracking", "Tracking"
        DELIVERY = "Delivered","Delivered"
        RETURN   = "Return",   "Return"

    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    related_order   = models.ForeignKey(Order, on_delete=models.CASCADE,
                                        null=True, blank=True, related_name="notifications")
    sent_to         = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type            = models.CharField(max_length=10, choices=NotificationType.choices)
    message         = models.TextField()
    is_read         = models.BooleanField(default=False)
    sent_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        ordering = ["-sent_at"]

    def __str__(self):
        return f"[{self.type}] - {self.sent_to} | Read: {self.is_read}"


class AuditLog(models.Model):
    """
    Strictly append-only compliance log.
    Records every CREATE / UPDATE / DELETE across all modules.

    Enforcement rules:
      - Use django-auditlog or django-simple-history for automatic capture.
      - No UPDATE or DELETE permission should exist at DB level.
      - Even Admins cannot modify this table.
      - old_value / new_value stored as JSON strings for queryability.
    """

    audit_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="audit_logs",
                                     help_text="The actor who triggered the change")
    action       = models.CharField(max_length=10,
                                    help_text="CREATE | UPDATE | DELETE")
    module       = models.CharField(max_length=50,
                                    help_text="e.g. 'order', 'shipment', 'user'")
    reference_id = models.UUIDField(help_text="PK of the modified record")
    # Store as JSON strings — keeps the log queryable without a separate JSONB column
    old_value    = models.TextField(blank=True,
                                    help_text="JSON snapshot of the record BEFORE the change")
    new_value    = models.TextField(blank=True,
                                    help_text="JSON snapshot of the record AFTER the change")
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.action}] {self.module} {self.reference_id} by {self.user} @ {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        # Block any update to an existing audit log row
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise PermissionError("AuditLog records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

# ===========================================================================
# 8. Authentication Extras (OTP)
# ===========================================================================

from django.utils.timezone import now
from datetime import timedelta

class OTPVerification(models.Model):
    # Standard market OTP model for secure short-lived validation
    otp_id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email      = models.EmailField(max_length=255)
    otp_code   = models.CharField(max_length=6)
    is_used    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "otp_verification"
        ordering = ["-created_at"]

    def __str__(self):
        return f"OTP for {self.email} ({'Used' if self.is_used else 'Active'})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            # 10 minutes market standard expiration
            self.expires_at = now() + timedelta(minutes=10)
        super().save(*args, **kwargs)
    
    def is_valid(self):
        return not self.is_used and self.expires_at >= now()