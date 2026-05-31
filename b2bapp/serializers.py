"""
B2B Tracking Application - Serializers
========================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

Every serializer enforces the data contracts described in the TRS.

Key rules applied across all serializers:
  1. Passwords are write_only — never returned in any response.
  2. Auto-computed fields (total_price, total_amount) are read_only.
  3. UUID primary keys are read_only (server-assigned).
  4. Multi-tenant FKs (company) are excluded from input — set by the view.
  5. Return item quantities are validated against original order quantities.
  6. Order items carry stock-availability checks before saving.
"""

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import (
    Admin, AuditLog, Client, Company, Driver, InventoryLog,
    Manager, Notification, Order, OrderItem, Payment,
    Product, ReturnedItem, ReturnedOrder, Route,
    Shipment, User, Warehouse,
)


# ===========================================================================
# MODULE 1 — Identity & Auth
# ===========================================================================

class LoginSerializer(serializers.Serializer):
    """Validates the body of POST /api/auth/login."""
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class CompanySerializer(serializers.ModelSerializer):
    """
    Used for:  POST /api/companies  (onboarding)
               GET/PUT /api/companies/{id}
    company_id is assigned by the server — excluded from input.
    """

    class Meta:
        model  = Company
        fields = [
            "company_id", "company_name", "address",
            "email", "phone", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["company_id", "created_at", "updated_at"]


class UserSerializer(serializers.ModelSerializer):
    """
    Read / update an existing user.
    password_hash is always excluded from output.
    company is a nested read-only representation.
    """
    company_name = serializers.CharField(source="company.company_name", read_only=True)

    class Meta:
        model  = User
        fields = [
            "user_id", "company", "company_name",
            "name", "email", "phone", "role",
            "is_active", "last_login", "created_at",
        ]
        read_only_fields = ["user_id", "company", "company_name", "last_login", "created_at"]


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Used for POST /api/users.
    Accepts a plain-text password, hashes it via User.set_password(),
    and never returns it in the response.
    """
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        help_text="Min 8 characters.",
    )

    class Meta:
        model  = User
        fields = [
            "user_id", "name", "email", "phone",
            "password", "role", "is_active",
        ]
        read_only_fields = ["user_id"]

    def validate_role(self, value):
        """
        A Manager cannot create an Admin — only an Admin can do that.
        Enforced here in addition to the view-level RBAC check.
        """
        request = self.context.get("request")
        if request and request.user.is_manager and value == User.Role.ADMIN:
            raise ValidationError("Managers cannot create Admin accounts.")
        return value

    def create(self, validated_data):
        raw_password = validated_data.pop("password")
        # company is injected by the view via perform_create()
        user = User(**validated_data)
        user.set_password(raw_password)
        user.save()
        return user


class AdminSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.company_name", read_only=True)
    user_name    = serializers.CharField(source="user.name", read_only=True)
    user_email   = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model  = Admin
        fields = [
            "admin_id", "company", "company_name",
            "user", "user_name", "user_email", "created_at",
        ]
        read_only_fields = [
            "admin_id", "company", "company_name",
            "user", "user_name", "user_email", "created_at",
        ]


class ManagerSerializer(serializers.ModelSerializer):
    company_name          = serializers.CharField(source="company.company_name", read_only=True)
    user_name             = serializers.CharField(source="user.name", read_only=True)
    user_email            = serializers.CharField(source="user.email", read_only=True)
    created_by_admin_name = serializers.CharField(source="created_by_admin.user.name", read_only=True)
    supervisor_name       = serializers.CharField(source="supervisor.user.name", read_only=True)

    class Meta:
        model  = Manager
        fields = [
            "manager_id", "company", "company_name",
            "user", "user_name", "user_email",
            "created_by_admin", "created_by_admin_name",
            "supervisor", "supervisor_name", "created_at",
        ]
        read_only_fields = [
            "manager_id", "company", "company_name",
            "user", "user_name", "user_email",
            "created_by_admin", "created_by_admin_name",
            "supervisor_name", "created_at",
        ]


# ===========================================================================
# MODULE 2 — Catalog & Entities Management (MDM)
# ===========================================================================

class WarehouseSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.company_name", read_only=True)

    class Meta:
        model  = Warehouse
        fields = [
            "warehouse_id", "company", "company_name",
            "warehouse_name", "address", "capacity", "is_active",
        ]
        read_only_fields = ["warehouse_id", "company", "company_name"]


class ProductSerializer(serializers.ModelSerializer):
    """
    Exposes needs_reorder as a computed boolean.
    stock_available is read_only here — all mutations go through InventoryLog.
    """
    company_name   = serializers.CharField(source="company.company_name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.warehouse_name", read_only=True)
    needs_reorder  = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Product
        fields = [
            "product_id", "company", "company_name",
            "warehouse", "warehouse_name",
            "product_name", "product_version", "sku_code",
            "unit_price", "total_manufactured",
            "stock_available", "reorder_level",
            "needs_reorder", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "product_id", "company", "company_name",
            "warehouse_name", "stock_available",
            "needs_reorder", "created_at", "updated_at",
        ]

    def validate_warehouse(self, warehouse):
        request = self.context.get("request")
        if request and warehouse and warehouse.company_id != request.user.company_id:
            raise ValidationError("Warehouse does not belong to your company.")
        return warehouse


class ClientSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.company_name", read_only=True)

    class Meta:
        model  = Client
        fields = [
            "client_id", "company", "company_name",
            "client_name", "client_company",
            "address", "email", "phone",
            "client_since", "is_active",
        ]
        read_only_fields = ["client_id", "company", "company_name"]


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Route
        fields = [
            "route_id", "company",
            "start_location", "end_location",
            "distance", "estimated_time", "is_active",
        ]
        read_only_fields = ["route_id", "company"]

    def validate(self, attrs):
        if attrs.get("distance", 0) <= 0:
            raise ValidationError({"distance": "Distance must be greater than 0."})
        if attrs.get("estimated_time", 0) <= 0:
            raise ValidationError({"estimated_time": "Estimated time must be greater than 0."})
        return attrs


# ===========================================================================
# MODULE 3 — Order Management
# ===========================================================================

class OrderItemSerializer(serializers.ModelSerializer):
    """
    Read representation of a single order line.
    total_price is computed by OrderItem.save() — never accepted from input.
    unit_price is auto-populated from the product's current price on create.
    """
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku_code     = serializers.CharField(source="product.sku_code", read_only=True)

    class Meta:
        model  = OrderItem
        fields = [
            "order_item_id", "order", "product", "product_name",
            "sku_code", "quantity", "unit_price", "total_price",
        ]
        read_only_fields = ["order_item_id", "order", "product_name",
                            "sku_code", "unit_price", "total_price"]


class OrderItemCreateSerializer(serializers.Serializer):
    """
    Used only inside OrderCreateSerializer for the nested items list.
    Validates stock availability per item before the order is committed.
    """
    product  = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)

    def validate_product(self, product):
        request = self.context.get("request")
        if request and product.company_id != request.user.company_id:
            raise ValidationError("Product does not belong to your company.")
        return product

    def validate(self, attrs):
        product  = attrs["product"]
        quantity = attrs["quantity"]

        # Check stock — uses select_for_update() in the outer atomic() block
        if product.stock_available < quantity:
            raise ValidationError(
                f"Insufficient stock for '{product.product_name}'. "
                f"Available: {product.stock_available}, Requested: {quantity}."
            )
        return attrs


class OrderCreateSerializer(serializers.Serializer):
    """
    POST /api/orders
    Accepts: { client (UUID), items: [ { product, quantity } ] }
    Rejects total_amount from input — computed server-side only.
    Wrapped in transaction.atomic() in the view.
    """
    client = serializers.PrimaryKeyRelatedField(
        queryset=Client.objects.filter(is_active=True)
    )
    items = OrderItemCreateSerializer(many=True, min_length=1)

    def validate_client(self, client):
        """Client must belong to the requesting user's company."""
        request = self.context.get("request")
        if request and client.company_id != request.user.company_id:
            raise ValidationError("Client does not belong to your company.")
        return client

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        company    = validated_data.pop("company")  # injected by view

        order = Order.objects.create(company=company, **validated_data)

        for item_data in items_data:
            product  = item_data["product"]
            quantity = item_data["quantity"]

            # Lock the product row to prevent concurrent overselling
            product = Product.objects.select_for_update().get(pk=product.pk)

            if product.stock_available < quantity:
                raise ValidationError(
                    f"Race condition: '{product.product_name}' stock changed. "
                    f"Available: {product.stock_available}, Requested: {quantity}."
                )

            OrderItem.objects.create(
                order      = order,
                product    = product,
                quantity   = quantity,
                unit_price = product.unit_price,  # snapshot current price
            )

            # Deduct stock and write the inventory log in one atomic block
            product.stock_available -= quantity
            product.save(update_fields=["stock_available", "updated_at"])

            InventoryLog.objects.create(
                product      = product,
                warehouse    = product.warehouse,
                change_type  = InventoryLog.ChangeType.OUT,
                quantity     = -quantity,
                reference_id = order.order_id,
            )

        return order


class OrderSerializer(serializers.ModelSerializer):
    """Full read representation of an Order, including nested items."""
    items        = OrderItemSerializer(many=True, read_only=True)
    client_name  = serializers.CharField(source="client.client_name", read_only=True)
    company_name = serializers.CharField(source="company.company_name", read_only=True)

    class Meta:
        model  = Order
        fields = [
            "order_id", "company", "company_name",
            "client", "client_name",
            "ordered_at", "status", "total_amount",
            "payment_status", "is_active",
            "created_at", "updated_at", "items",
        ]
        read_only_fields = [
            "order_id", "company", "company_name",
            "client_name", "total_amount",
            "created_at", "updated_at", "items",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    order_status = serializers.CharField(source="order.status", read_only=True)

    class Meta:
        model  = Payment
        fields = [
            "payment_id", "order", "order_status",
            "amount", "payment_method", "payment_status",
            "paid_at", "transaction_ref",
        ]
        read_only_fields = ["payment_id", "order_status"]


# ===========================================================================
# MODULE 4 — Logistics, Driver App & Live Tracking
# ===========================================================================

class DriverSerializer(serializers.ModelSerializer):
    company_name             = serializers.CharField(source="company.company_name", read_only=True)
    created_by_manager_name = serializers.CharField(source="created_by_manager.user.name", read_only=True)

    class Meta:
        model  = Driver
        fields = [
            "driver_id", "company", "company_name",
            "created_by_manager", "created_by_manager_name",
            "name", "phone", "photo", "license_no",
            "is_available", "is_active",
            "total_orders_delivered", "joined_at",
            "current_location",
        ]
        read_only_fields = [
            "driver_id", "company", "company_name",
            "created_by_manager", "created_by_manager_name",
            "total_orders_delivered", "current_location",
        ]


class ShipmentSerializer(serializers.ModelSerializer):
    """
    Full read + create representation of a Shipment.
    live_location and proof_of_delivery are read_only here;
    they are updated via dedicated @action endpoints.
    """
    order_status        = serializers.CharField(source="order.status", read_only=True)
    driver_name         = serializers.CharField(source="driver.name", read_only=True)
    route_summary       = serializers.SerializerMethodField()
    warehouse_name      = serializers.CharField(source="from_warehouse.warehouse_name", read_only=True)
    client_name         = serializers.CharField(source="to_client.client_name", read_only=True)

    class Meta:
        model  = Shipment
        fields = [
            "shipment_id", "order", "order_status",
            "from_warehouse", "warehouse_name",
            "to_client", "client_name",
            "driver", "driver_name",
            "route", "route_summary",
            "dispatch_time", "estimated_delivery_time", "actual_delivery_time",
            "live_location", "status",
            "proof_of_delivery", "delivery_attempts",
        ]
        read_only_fields = [
            "shipment_id", "order_status", "warehouse_name",
            "client_name", "driver_name", "route_summary",
            "live_location", "proof_of_delivery",
            "actual_delivery_time",
        ]

    def get_route_summary(self, obj) -> str | None:
        if obj.route:
            return f"{obj.route.start_location} → {obj.route.end_location}"
        return None

    def validate_order(self, order):
        """An order can only have one shipment."""
        if Shipment.objects.filter(order=order).exists():
            raise ValidationError("A shipment already exists for this order.")
        if order.status not in (Order.Status.CONFIRMED, Order.Status.PACKED):
            raise ValidationError(
                f"Order must be Confirmed or Packed before shipment. "
                f"Current status: {order.status}."
            )
        request = self.context.get("request")
        if request and order.company_id != request.user.company_id:
            raise ValidationError("Order does not belong to your company.")
        return order

    def validate(self, attrs):
        request = self.context.get("request")
        if request:
            company = request.user.company
            if attrs.get("from_warehouse") and attrs["from_warehouse"].company_id != company.company_id:
                raise ValidationError({"from_warehouse": "Warehouse does not belong to your company."})
            if attrs.get("to_client") and attrs["to_client"].company_id != company.company_id:
                raise ValidationError({"to_client": "Client does not belong to your company."})
            if attrs.get("driver") and attrs["driver"].company_id != company.company_id:
                raise ValidationError({"driver": "Driver does not belong to your company."})
            if attrs.get("route") and attrs["route"].company_id != company.company_id:
                raise ValidationError({"route": "Route does not belong to your company."})
        return super().validate(attrs)


# ===========================================================================
# MODULE 5 — Returns & Reverse Logistics
# ===========================================================================

class ReturnedItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    sku_code     = serializers.CharField(source="product.sku_code", read_only=True)

    class Meta:
        model  = ReturnedItem
        fields = [
            "return_item_id", "return_order",
            "product", "product_name", "sku_code",
            "quantity", "condition",
        ]
        read_only_fields = ["return_item_id", "return_order", "product_name", "sku_code"]


class ReturnedItemCreateSerializer(serializers.Serializer):
    """Nested serializer for items within ReturnedOrderSerializer."""
    product   = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity  = serializers.IntegerField(min_value=1)
    condition = serializers.ChoiceField(choices=ReturnedItem.Condition.choices)


class ReturnedOrderSerializer(serializers.ModelSerializer):
    """
    POST /api/returns
    Validates:
      1. The order belongs to the requesting client.
      2. The order is in Delivered status.
      3. Each return item quantity ≤ the original ordered quantity.
    On create, stock is added back and an InventoryLog RETURN entry is written.
    """
    items        = ReturnedItemSerializer(many=True, read_only=True)
    return_items = ReturnedItemCreateSerializer(many=True, write_only=True, min_length=1)
    client_name  = serializers.CharField(source="client.client_name", read_only=True)
    order_ref    = serializers.CharField(source="old_order.order_id", read_only=True)

    class Meta:
        model  = ReturnedOrder
        fields = [
            "return_id", "old_order", "order_ref",
            "client", "client_name", "company",
            "driver", "return_reason", "return_status",
            "created_at", "items", "return_items",
        ]
        read_only_fields = [
            "return_id", "order_ref", "client_name", "client",
            "company", "return_status", "created_at", "items",
        ]

    def validate(self, attrs):
        request   = self.context.get("request")
        old_order = attrs.get("old_order")

        # 1. Order must be Delivered (or already partially Returned) before a return can be requested
        if old_order.status not in (Order.Status.DELIVERED, Order.Status.RETURNED):
            raise ValidationError(
                {"old_order": f"Returns are only allowed for Delivered orders. "
                              f"Current status: {old_order.status}."}
            )

        # 2. Client-role users can only return their own orders
        if request and request.user.is_client:
            try:
                client = Client.objects.get(email=request.user.email,
                                            company=request.user.company)
                if old_order.client_id != client.client_id:
                    raise ValidationError(
                        {"old_order": "You can only request returns for your own orders."}
                    )
            except Client.DoesNotExist:
                raise ValidationError({"old_order": "Client profile not found."})

        # 3. Validate each return item quantity against original order
        return_items = attrs.get("return_items", [])
        for item in return_items:
            product  = item["product"]
            quantity = item["quantity"]
            try:
                original = OrderItem.objects.get(order=old_order, product=product)
            except OrderItem.DoesNotExist:
                raise ValidationError(
                    {"return_items":
                     f"Product '{product.product_name}' was not in the original order."}
                )
            if quantity > original.quantity:
                raise ValidationError(
                    {"return_items":
                     f"Return quantity ({quantity}) for '{product.product_name}' "
                     f"exceeds original order quantity ({original.quantity})."}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        return_items_data = validated_data.pop("return_items")
        company           = validated_data.pop("company")

        # Determine the client from the order
        old_order = validated_data["old_order"]
        client    = old_order.client

        return_obj = ReturnedOrder.objects.create(
            company=company,
            client=client,
            **validated_data,
        )

        for item_data in return_items_data:
            product   = item_data["product"]
            quantity  = item_data["quantity"]
            condition = item_data["condition"]

            ReturnedItem.objects.create(
                return_order=return_obj,
                product=product,
                quantity=quantity,
                condition=condition,
            )

        return return_obj


# ===========================================================================
# MODULE 6 — Inventory Management & Stock Sync
# ===========================================================================

class InventoryLogSerializer(serializers.ModelSerializer):
    product_name   = serializers.CharField(source="product.product_name", read_only=True)
    sku_code       = serializers.CharField(source="product.sku_code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.warehouse_name", read_only=True)

    class Meta:
        model  = InventoryLog
        fields = [
            "log_id", "product", "product_name", "sku_code",
            "warehouse", "warehouse_name",
            "change_type", "quantity", "reference_id", "logged_at",
        ]
        read_only_fields = fields  # entire table is append-only; no writes via API


# ===========================================================================
# MODULE 7 — System Notifications & Audit Logging
# ===========================================================================

class NotificationSerializer(serializers.ModelSerializer):
    sent_to_name = serializers.CharField(source="sent_to.name", read_only=True)
    order_ref    = serializers.CharField(source="related_order.order_id", read_only=True,
                                         default=None)

    class Meta:
        model  = Notification
        fields = [
            "notification_id", "related_order", "order_ref",
            "sent_to", "sent_to_name", "type",
            "message", "is_read", "sent_at",
        ]
        read_only_fields = [
            "notification_id", "order_ref", "sent_to_name",
            "sent_at",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    """
    Strictly read-only.  old_value / new_value are stored as JSON strings
    and returned as parsed objects for easy frontend consumption.
    """
    actor_name = serializers.CharField(source="user.name", read_only=True, default="System")
    old_value  = serializers.SerializerMethodField()
    new_value  = serializers.SerializerMethodField()

    class Meta:
        model  = AuditLog
        fields = [
            "audit_id", "user", "actor_name",
            "action", "module", "reference_id",
            "old_value", "new_value", "created_at",
        ]
        read_only_fields = fields  # append-only; no API writes

    def get_old_value(self, obj) -> dict:
        import json
        try:
            return json.loads(obj.old_value) if obj.old_value else {}
        except (ValueError, TypeError):
            return {}

    def get_new_value(self, obj) -> dict:
        import json
        try:
            return json.loads(obj.new_value) if obj.new_value else {}
        except (ValueError, TypeError):
            return {}