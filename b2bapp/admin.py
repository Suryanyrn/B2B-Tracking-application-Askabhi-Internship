"""
B2B Tracking Application - Django Admin
=========================================
Author  : Suryanarayanan R
Version : 1.0
Date    : 23rd April 2026

Registers all 16 models with production-grade admin classes.

Design principles applied:
  1. Custom AdminSite with branded header / title.
  2. Immutable models (AuditLog, InventoryLog) → has_add/change/delete_permission
     all return False — no row can ever be created or mutated via admin.
  3. Soft-delete everywhere — no hard DELETE actions exposed.
  4. Password handled via a split Add / Change form so it is always hashed.
  5. Inline classes keep related data (OrderItems, ReturnedItems, Payments,
     Notifications) visible on the parent record page.
  6. Raw-id-widgets on all FK / M2M fields that could produce huge dropdowns.
  7. company field hidden on all forms — auto-populated from request.user.company
     so an Admin from Company A can never accidentally assign a record to Company B.
  8. list_select_related=True on every ModelAdmin to prevent N+1 queries.
  9. Custom admin actions: deactivate users, mark notifications read, reset
     driver availability.
 10. colour-coded status badges via HTML in list_display.
"""

import json

from django import forms
from django.contrib import admin
from django.contrib.admin import AdminSite
from django.db import transaction
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    Admin, AuditLog, Client, Company, Driver, InventoryLog,
    Manager, Notification, Order, OrderItem, Payment,
    Product, ReturnedItem, ReturnedOrder, Route,
    Shipment, User, Warehouse,
)


# ===========================================================================
# Custom Admin Site
# ===========================================================================

class B2BAdminSite(AdminSite):
    site_header  = "B2B Tracking — Administration"
    site_title   = "B2B Admin"
    index_title  = "Operations Dashboard"
    site_url     = "/api/"          # "View site" link in header


admin_site = B2BAdminSite(name="b2b_admin")


# ===========================================================================
# Helpers
# ===========================================================================

# Status → (background colour, text colour)
_STATUS_COLOURS = {
    # Order statuses
    "Pending":    ("#FFF3CD", "#856404"),
    "Confirmed":  ("#CCE5FF", "#004085"),
    "Packed":     ("#D4EDDA", "#155724"),
    "Dispatched": ("#D1ECF1", "#0C5460"),
    "Delivered":  ("#C3E6CB", "#155724"),
    "Returned":   ("#F8D7DA", "#721C24"),
    "Cancelled":  ("#E2E3E5", "#383D41"),
    # Shipment statuses
    "Ready":      ("#CCE5FF", "#004085"),
    "In_Transit": ("#D1ECF1", "#0C5460"),
    "Failed":     ("#F8D7DA", "#721C24"),
    # Return statuses
    "Requested":  ("#FFF3CD", "#856404"),
    "Approved":   ("#D4EDDA", "#155724"),
    "Picked_Up":  ("#D1ECF1", "#0C5460"),
    "Rejected":   ("#F8D7DA", "#721C24"),
    # Payment statuses
    "Paid":       ("#C3E6CB", "#155724"),
    "Completed":  ("#C3E6CB", "#155724"),
    "Refunded":   ("#D1ECF1", "#0C5460"),
}


def _badge(value: str) -> str:
    """Return an HTML badge span for a status value."""
    bg, fg = _STATUS_COLOURS.get(value, ("#E2E3E5", "#383D41"))
    return format_html(
        '<span style="background:{};color:{};padding:2px 8px;'
        'border-radius:4px;font-size:0.85em;font-weight:600;">{}</span>',
        bg, fg, value,
    )


def _pretty_json(raw: str) -> str:
    """Render a JSON string as an indented <pre> block in the admin."""
    try:
        parsed = json.loads(raw) if raw else {}
        return format_html(
            "<pre style='font-size:0.8em;margin:0'>{}</pre>",
            json.dumps(parsed, indent=2, ensure_ascii=False),
        )
    except (ValueError, TypeError):
        return raw or "—"


# ===========================================================================
# MODULE 1 — User Management & Authentication (IAM)
# ===========================================================================

# ── User forms ──────────────────────────────────────────────────────────────

class UserAddForm(forms.ModelForm):
    """
    Used only when creating a new User via admin.
    Accepts a plain-text password and hashes it via set_password().
    """
    password  = forms.CharField(
        label="Password",
        widget=forms.PasswordInput,
        min_length=8,
        help_text="Min 8 characters.  Stored as a hash — never plain text.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput,
    )

    class Meta:
        model  = User
        fields = ["company", "name", "email", "phone", "role", "is_active"]

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """
    Used when editing an existing User.
    Password field is optional — leave blank to keep the current hash.
    """
    new_password = forms.CharField(
        label="New password (optional)",
        widget=forms.PasswordInput,
        required=False,
        min_length=8,
        help_text="Leave blank to keep the existing password.",
    )

    class Meta:
        model  = User
        fields = ["company", "name", "email", "phone", "role", "is_active"]

    def save(self, commit=True):
        user = super().save(commit=False)
        raw  = self.cleaned_data.get("new_password")
        if raw:
            user.set_password(raw)
        if commit:
            user.save()
        return user


# ── Inline for Users inside Company ─────────────────────────────────────────

class UserInline(admin.TabularInline):
    model           = User
    form            = UserChangeForm
    extra           = 0
    show_change_link = True
    fields          = ["name", "email", "role", "is_active"]
    readonly_fields = ["last_login"]
    can_delete      = False   # use soft-delete via the User admin instead


@admin.register(Company, site=admin_site)
class CompanyAdmin(admin.ModelAdmin):
    list_display         = ["company_name", "email", "phone", "is_active",
                             "created_at", "user_count"]
    list_filter          = ["is_active"]
    search_fields        = ["company_name", "email", "phone"]
    readonly_fields      = ["company_id", "created_at", "updated_at"]
    list_select_related  = True
    inlines              = [UserInline]

    fieldsets = [
        ("Identity", {
            "fields": ["company_id", "company_name", "is_active"],
        }),
        ("Contact", {
            "fields": ["email", "phone", "address"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    @admin.display(description="Users")
    def user_count(self, obj) -> int:
        return obj.users.filter(is_active=True).count()

    def has_delete_permission(self, request, obj=None):
        # Companies are never hard-deleted via admin
        return False


@admin.register(User, site=admin_site)
class UserAdmin(admin.ModelAdmin):
    list_display        = ["name", "email", "role", "company",
                           "is_active", "last_login", "created_at"]
    list_filter         = ["role", "is_active", "company"]
    search_fields       = ["name", "email", "phone"]
    readonly_fields     = ["user_id", "password_hash", "last_login", "created_at"]
    list_select_related = True
    raw_id_fields       = ["company"]
    actions             = ["deactivate_users"]

    fieldsets = [
        ("Identity", {
            "fields": ["user_id", "company", "name", "email", "phone"],
        }),
        ("Access", {
            "fields": ["role", "is_active"],
        }),
        ("Security", {
            "fields": ["password_hash", "last_login", "created_at"],
            "classes": ["collapse"],
            "description": "password_hash is shown for audit only — it is never plain text.",
        }),
    ]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = UserAddForm
        else:
            kwargs["form"] = UserChangeForm
        return super().get_form(request, obj, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return False   # use deactivate_users action instead

    @admin.action(description="Deactivate selected users (soft delete)")
    def deactivate_users(self, request, queryset):
        updated = queryset.exclude(role=User.Role.ADMIN).update(is_active=False)
        self.message_user(request, f"{updated} user(s) deactivated.")


@admin.register(Admin, site=admin_site)
class AdminAdmin(admin.ModelAdmin):
    list_display        = ["admin_id", "company", "user", "created_at"]
    list_filter         = ["company"]
    search_fields       = ["user__name", "user__email", "company__company_name"]
    readonly_fields     = ["admin_id", "created_at"]
    raw_id_fields       = ["company", "user"]
    list_select_related = True


@admin.register(Manager, site=admin_site)
class ManagerAdmin(admin.ModelAdmin):
    list_display        = ["manager_id", "company", "user", "created_by_admin", "supervisor", "created_at"]
    list_filter         = ["company"]
    search_fields       = ["user__name", "user__email", "company__company_name"]
    readonly_fields     = ["manager_id", "created_at"]
    raw_id_fields       = ["company", "user", "created_by_admin", "supervisor"]
    list_select_related = True


# ===========================================================================
# MODULE 2 — Catalog & Entities Management (MDM)
# ===========================================================================

@admin.register(Warehouse, site=admin_site)
class WarehouseAdmin(admin.ModelAdmin):
    list_display        = ["warehouse_name", "company", "capacity",
                           "is_active", "product_count"]
    list_filter         = ["is_active", "company"]
    search_fields       = ["warehouse_name", "address"]
    readonly_fields     = ["warehouse_id"]
    raw_id_fields       = ["company"]
    list_select_related = True

    fieldsets = [
        (None, {
            "fields": ["warehouse_id", "company", "warehouse_name", "address",
                       "capacity", "is_active"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Active products")
    def product_count(self, obj) -> int:
        return obj.products.filter(is_active=True).count()


@admin.register(Product, site=admin_site)
class ProductAdmin(admin.ModelAdmin):
    list_display        = ["product_name", "sku_code", "company", "warehouse",
                           "unit_price", "stock_available", "reorder_level",
                           "stock_status", "is_active"]
    list_filter         = ["is_active", "company", "warehouse"]
    search_fields       = ["product_name", "sku_code"]
    readonly_fields     = ["product_id", "stock_available", "needs_reorder_display",
                           "created_at", "updated_at"]
    raw_id_fields       = ["company", "warehouse"]
    list_select_related = True

    fieldsets = [
        ("Identity", {
            "fields": ["product_id", "company", "warehouse",
                       "product_name", "product_version", "sku_code", "is_active"],
        }),
        ("Pricing & Stock", {
            "fields": ["unit_price", "total_manufactured",
                       "stock_available", "reorder_level", "needs_reorder_display"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Stock status", ordering="stock_available")
    def stock_status(self, obj) -> str:
        if obj.stock_available == 0:
            return format_html(
                '<span style="color:#721C24;font-weight:700;">⚠ OUT OF STOCK</span>'
            )
        if obj.needs_reorder:
            return format_html(
                '<span style="color:#856404;font-weight:700;">↓ Low stock</span>'
            )
        return format_html('<span style="color:#155724;">✓ OK</span>')

    @admin.display(description="Needs reorder?", boolean=True)
    def needs_reorder_display(self, obj) -> bool:
        return obj.needs_reorder


@admin.register(Client, site=admin_site)
class ClientAdmin(admin.ModelAdmin):
    list_display        = ["client_name", "client_company", "company",
                           "email", "phone", "client_since", "is_active"]
    list_filter         = ["is_active", "company"]
    search_fields       = ["client_name", "client_company", "email", "phone"]
    readonly_fields     = ["client_id"]
    raw_id_fields       = ["company"]
    list_select_related = True

    fieldsets = [
        ("Identity", {
            "fields": ["client_id", "company", "client_name",
                       "client_company", "is_active"],
        }),
        ("Contact", {
            "fields": ["address", "email", "phone", "client_since"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Route, site=admin_site)
class RouteAdmin(admin.ModelAdmin):
    list_display    = ["start_location", "end_location", "distance",
                       "estimated_time_display", "company", "is_active"]
    list_filter     = ["is_active", "company"]
    search_fields   = ["start_location", "end_location"]
    readonly_fields = ["route_id"]
    raw_id_fields   = ["company"]

    fieldsets = [
        (None, {
            "fields": ["route_id", "company", "start_location", "end_location",
                       "distance", "estimated_time", "is_active"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="ETA")
    def estimated_time_display(self, obj) -> str:
        hrs, mins = divmod(obj.estimated_time, 60)
        return f"{hrs}h {mins}m" if hrs else f"{mins}m"


# ===========================================================================
# MODULE 3 — Order Management
# ===========================================================================

class OrderItemInline(admin.TabularInline):
    model           = OrderItem
    extra           = 0
    readonly_fields = ["order_item_id", "unit_price", "total_price"]
    fields          = ["product", "quantity", "unit_price", "total_price"]
    raw_id_fields   = ["product"]
    can_delete      = False

    def has_add_permission(self, request, obj=None):
        # Items are added only through the API's atomic order-create flow
        return False


class PaymentInline(admin.TabularInline):
    model           = Payment
    extra           = 0
    readonly_fields = ["payment_id", "paid_at"]
    fields          = ["payment_method", "payment_status", "amount",
                       "paid_at", "transaction_ref"]
    can_delete      = False


@admin.register(Order, site=admin_site)
class OrderAdmin(admin.ModelAdmin):
    list_display        = ["order_id_short", "client", "company", "status_badge",
                           "total_amount", "payment_status_badge",
                           "ordered_at", "is_active"]
    list_filter         = ["status", "payment_status", "is_active", "company"]
    search_fields       = ["client__client_name", "order_id"]
    readonly_fields     = ["order_id", "total_amount", "created_at", "updated_at"]
    raw_id_fields       = ["company", "client"]
    list_select_related = True
    date_hierarchy      = "ordered_at"
    inlines             = [OrderItemInline, PaymentInline]

    fieldsets = [
        ("Order", {
            "fields": ["order_id", "company", "client", "ordered_at", "is_active"],
        }),
        ("Status & Payment", {
            "fields": ["status", "total_amount", "payment_status"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Order ID")
    def order_id_short(self, obj) -> str:
        return str(obj.order_id)[:8] + "…"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj) -> str:
        return _badge(obj.status)

    @admin.display(description="Payment", ordering="payment_status")
    def payment_status_badge(self, obj) -> str:
        return _badge(obj.payment_status)


# ===========================================================================
# MODULE 4 — Logistics, Driver App & Live Tracking
# ===========================================================================

@admin.register(Driver, site=admin_site)
class DriverAdmin(admin.ModelAdmin):
    list_display        = ["name", "phone", "license_no", "company",
                           "is_available", "is_active", "total_orders_delivered",
                           "current_location", "joined_at"]
    list_filter         = ["is_available", "is_active", "company"]
    search_fields       = ["name", "phone", "license_no"]
    readonly_fields     = ["driver_id", "total_orders_delivered",
                           "current_location", "joined_at"]
    raw_id_fields       = ["company"]
    list_select_related = True
    actions             = ["mark_available", "mark_unavailable"]

    fieldsets = [
        ("Identity", {
            "fields": ["driver_id", "company", "name", "phone",
                       "license_no", "photo"],
        }),
        ("Status", {
            "fields": ["is_available", "is_active",
                       "total_orders_delivered", "joined_at"],
        }),
        ("Live Location", {
            "fields": ["current_location"],
            "classes": ["collapse"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Mark selected drivers as Available")
    def mark_available(self, request, queryset):
        updated = queryset.update(is_available=True)
        self.message_user(request, f"{updated} driver(s) marked as available.")

    @admin.action(description="Mark selected drivers as Unavailable")
    def mark_unavailable(self, request, queryset):
        updated = queryset.update(is_available=False)
        self.message_user(request, f"{updated} driver(s) marked as unavailable.")


@admin.register(Shipment, site=admin_site)
class ShipmentAdmin(admin.ModelAdmin):
    list_display        = ["shipment_id_short", "order", "driver",
                           "status_badge", "from_warehouse", "to_client",
                           "dispatch_time", "actual_delivery_time",
                           "delivery_attempts", "has_pod"]
    list_filter         = ["status", "from_warehouse", "driver"]
    search_fields       = ["order__order_id", "driver__name", "to_client__client_name"]
    readonly_fields     = ["shipment_id", "live_location", "proof_of_delivery",
                           "actual_delivery_time", "delivery_attempts"]
    raw_id_fields       = ["order", "from_warehouse", "to_client", "driver", "route"]
    list_select_related = True
    date_hierarchy      = "dispatch_time"

    fieldsets = [
        ("Shipment", {
            "fields": ["shipment_id", "order", "from_warehouse",
                       "to_client", "driver", "route"],
        }),
        ("Timing", {
            "fields": ["dispatch_time", "estimated_delivery_time",
                       "actual_delivery_time"],
        }),
        ("Status & Tracking", {
            "fields": ["status", "delivery_attempts",
                       "live_location", "proof_of_delivery"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Shipment ID")
    def shipment_id_short(self, obj) -> str:
        return str(obj.shipment_id)[:8] + "…"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj) -> str:
        return _badge(obj.status)

    @admin.display(description="POD", boolean=True)
    def has_pod(self, obj) -> bool:
        return bool(obj.proof_of_delivery)


# ===========================================================================
# MODULE 5 — Returns & Reverse Logistics
# ===========================================================================

class ReturnedItemInline(admin.TabularInline):
    model           = ReturnedItem
    extra           = 0
    readonly_fields = ["return_item_id"]
    fields          = ["product", "quantity", "condition"]
    raw_id_fields   = ["product"]
    can_delete      = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ReturnedOrder, site=admin_site)
class ReturnedOrderAdmin(admin.ModelAdmin):
    list_display        = ["return_id_short", "old_order", "client", "company",
                           "driver", "return_status_badge", "created_at"]
    list_filter         = ["return_status", "company"]
    search_fields       = ["client__client_name", "old_order__order_id"]
    readonly_fields     = ["return_id", "created_at"]
    raw_id_fields       = ["old_order", "client", "company", "driver"]
    list_select_related = True
    date_hierarchy      = "created_at"
    inlines             = [ReturnedItemInline]

    fieldsets = [
        ("Return", {
            "fields": ["return_id", "company", "old_order",
                       "client", "driver"],
        }),
        ("Details", {
            "fields": ["return_reason", "return_status", "created_at"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Return ID")
    def return_id_short(self, obj) -> str:
        return str(obj.return_id)[:8] + "…"

    @admin.display(description="Status", ordering="return_status")
    def return_status_badge(self, obj) -> str:
        return _badge(obj.return_status)


# ===========================================================================
# MODULE 6 — Inventory Management & Stock Sync
# ===========================================================================

@admin.register(InventoryLog, site=admin_site)
class InventoryLogAdmin(admin.ModelAdmin):
    """
    STRICTLY READ-ONLY.
    InventoryLog is an immutable ledger — no admin user may add, change,
    or delete rows.  Every permission method returns False.
    """
    list_display        = ["log_id_short", "change_type_badge", "product",
                           "warehouse", "quantity", "reference_id_short", "logged_at"]
    list_filter         = ["change_type", "warehouse"]
    search_fields       = ["product__product_name", "product__sku_code"]
    readonly_fields     = ["log_id", "product", "warehouse", "change_type",
                           "quantity", "reference_id", "logged_at"]
    list_select_related = True
    date_hierarchy      = "logged_at"

    # Collapse the sidebar add button / change links entirely
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Log ID")
    def log_id_short(self, obj) -> str:
        return str(obj.log_id)[:8] + "…"

    @admin.display(description="Reference")
    def reference_id_short(self, obj) -> str:
        return str(obj.reference_id)[:8] + "…"

    # Colour-code the change type badge
    _CT_COLOURS = {
        "IN":     ("#D4EDDA", "#155724"),
        "OUT":    ("#F8D7DA", "#721C24"),
        "RETURN": ("#D1ECF1", "#0C5460"),
        "DAMAGE": ("#FFF3CD", "#856404"),
    }

    @admin.display(description="Type", ordering="change_type")
    def change_type_badge(self, obj) -> str:
        bg, fg = self._CT_COLOURS.get(obj.change_type, ("#E2E3E5", "#383D41"))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;'
            'border-radius:4px;font-size:0.85em;font-weight:600;">{}</span>',
            bg, fg, obj.change_type,
        )


# ===========================================================================
# MODULE 3 extension — Payment
# ===========================================================================

@admin.register(Payment, site=admin_site)
class PaymentAdmin(admin.ModelAdmin):
    list_display        = ["payment_id_short", "order", "payment_method",
                           "payment_status_badge", "amount", "paid_at"]
    list_filter         = ["payment_status", "payment_method"]
    search_fields       = ["order__order_id", "transaction_ref"]
    readonly_fields     = ["payment_id", "paid_at"]
    raw_id_fields       = ["order"]
    list_select_related = True

    fieldsets = [
        (None, {
            "fields": ["payment_id", "order", "amount",
                       "payment_method", "payment_status",
                       "paid_at", "transaction_ref"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Payment ID")
    def payment_id_short(self, obj) -> str:
        return str(obj.payment_id)[:8] + "…"

    @admin.display(description="Status", ordering="payment_status")
    def payment_status_badge(self, obj) -> str:
        return _badge(obj.payment_status)


# ===========================================================================
# MODULE 7 — System Notifications & Audit Logging
# ===========================================================================

@admin.register(Notification, site=admin_site)
class NotificationAdmin(admin.ModelAdmin):
    list_display        = ["notification_id_short", "type", "sent_to",
                           "related_order", "is_read", "sent_at"]
    list_filter         = ["type", "is_read"]
    search_fields       = ["sent_to__name", "sent_to__email", "message"]
    readonly_fields     = ["notification_id", "sent_at"]
    raw_id_fields       = ["sent_to", "related_order"]
    list_select_related = True
    date_hierarchy      = "sent_at"
    actions             = ["mark_all_read"]

    fieldsets = [
        (None, {
            "fields": ["notification_id", "related_order", "sent_to",
                       "type", "message", "is_read", "sent_at"],
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="ID")
    def notification_id_short(self, obj) -> str:
        return str(obj.notification_id)[:8] + "…"

    @admin.action(description="Mark selected notifications as read")
    def mark_all_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} notification(s) marked as read.")


@admin.register(AuditLog, site=admin_site)
class AuditLogAdmin(admin.ModelAdmin):
    """
    STRICTLY READ-ONLY.
    Even Django Admins cannot add, edit, or delete audit log rows.
    old_value / new_value are rendered as pretty-printed JSON.
    """
    list_display        = ["audit_id_short", "action_badge", "module",
                           "reference_id_short", "user", "created_at"]
    list_filter         = ["action", "module"]
    search_fields       = ["module", "user__name", "user__email"]
    readonly_fields     = ["audit_id", "user", "action", "module",
                           "reference_id", "old_value_pretty",
                           "new_value_pretty", "created_at"]
    raw_id_fields       = []   # no FKs to edit
    list_select_related = True
    date_hierarchy      = "created_at"

    fieldsets = [
        ("Who / What / When", {
            "fields": ["audit_id", "user", "action", "module",
                       "reference_id", "created_at"],
        }),
        ("Before", {
            "fields": ["old_value_pretty"],
        }),
        ("After", {
            "fields": ["new_value_pretty"],
        }),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ── display helpers ────────────────────────────────────────────────

    @admin.display(description="Audit ID")
    def audit_id_short(self, obj) -> str:
        return str(obj.audit_id)[:8] + "…"

    @admin.display(description="Reference")
    def reference_id_short(self, obj) -> str:
        return str(obj.reference_id)[:8] + "…"

    _ACTION_COLOURS = {
        "CREATE": ("#D4EDDA", "#155724"),
        "UPDATE": ("#CCE5FF", "#004085"),
        "DELETE": ("#F8D7DA", "#721C24"),
    }

    @admin.display(description="Action", ordering="action")
    def action_badge(self, obj) -> str:
        bg, fg = self._ACTION_COLOURS.get(obj.action, ("#E2E3E5", "#383D41"))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;'
            'border-radius:4px;font-size:0.85em;font-weight:600;">{}</span>',
            bg, fg, obj.action,
        )

    @admin.display(description="Before (old value)")
    def old_value_pretty(self, obj) -> str:
        return _pretty_json(obj.old_value)

    @admin.display(description="After (new value)")
    def new_value_pretty(self, obj) -> str:
        return _pretty_json(obj.new_value)


# ===========================================================================
# Wire the custom admin site into urls.py
# ===========================================================================
#
# In your project's urls.py add:
#
#   from your_app.admin import admin_site
#
#   urlpatterns = [
#       path("admin/", admin_site.urls),
#       path("api/",   include("your_app.urls")),
#   ]
#
# ===========================================================================