import uuid
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction
from b2bapp.models import (
    Admin, Company, User as B2BUser, Warehouse, Product, Client, Route, Driver,
    Manager, Order, OrderItem, Shipment, ReturnedOrder, ReturnedItem,
    InventoryLog, Payment, Notification, AuditLog
)

class Command(BaseCommand):
    help = "Seeds the database with rich, production-grade multi-tenant dummy data for visualization."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Starting database seeding..."))

        # 1. Create Django Superuser for visual administration
        DjangoUser = get_user_model()
        superuser_username = "admin"
        superuser_email = "admin@example.com"
        superuser_password = "password123"

        if not DjangoUser.objects.filter(username=superuser_username).exists():
            self.stdout.write(self.style.MIGRATE_LABEL(f"Creating Django Superuser ({superuser_username} / {superuser_password})..."))
            DjangoUser.objects.create_superuser(
                username=superuser_username,
                email=superuser_email,
                password=superuser_password
            )
        else:
            self.stdout.write(self.style.SUCCESS("Django Superuser already exists."))

        # 2. Clear old data to prevent duplication
        self.stdout.write("Cleaning up existing operational data...")
        Notification.objects.all().delete()
        AuditLog.objects.all().delete()
        InventoryLog.objects.all().delete()
        Payment.objects.all().delete()
        ReturnedItem.objects.all().delete()
        ReturnedOrder.objects.all().delete()
        Shipment.objects.all().delete()
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Driver.objects.all().delete()
        Route.objects.all().delete()
        Client.objects.all().delete()
        Product.objects.all().delete()
        Warehouse.objects.all().delete()
        B2BUser.objects.all().delete()
        Company.objects.all().delete()

        # 3. Create Companies (Multi-Tenant)
        self.stdout.write("Creating Companies...")
        acme = Company.objects.create(
            company_name="Acme Corp",
            email="operations@acme.com",
            phone="+1 (555) 123-4567",
            address="100 Acme Way, Silicon Valley, CA"
        )
        globex = Company.objects.create(
            company_name="Globex Inc",
            email="logistics@globex.com",
            phone="+1 (555) 987-6543",
            address="456 Innovation Blvd, Boston, MA"
        )

        for comp, suffix in [(acme, "acme"), (globex, "globex")]:
            self.stdout.write(f"Seeding details for {comp.company_name}...")

            # 4. Create Tenant B2B Users
            admin_user = B2BUser.objects.create(
                company=comp,
                name=f"Admin for {comp.company_name}",
                email=f"admin@{suffix}.com",
                phone="1234567890",
                role=B2BUser.Role.ADMIN
            )
            admin_user.set_password("password123")
            admin_user.save()

            admin_profile = Admin.objects.create(
                company=comp,
                user=admin_user
            )

            manager_user = B2BUser.objects.create(
                company=comp,
                name=f"Manager for {comp.company_name}",
                email=f"manager@{suffix}.com",
                phone="9876543219",
                role=B2BUser.Role.MANAGER
            )
            manager_user.set_password("password123")
            manager_user.save()

            manager_profile = Manager.objects.create(
                company=comp,
                user=manager_user,
                created_by_admin=admin_profile
            )

            client_user = B2BUser.objects.create(
                company=comp,
                name=f"Client for {comp.company_name}",
                email=f"client@{suffix}.com",
                phone="2345678901",
                role=B2BUser.Role.CLIENT
            )
            client_user.set_password("password123")
            client_user.save()

            driver_user = B2BUser.objects.create(
                company=comp,
                name=f"Driver for {comp.company_name}",
                email=f"driver@{suffix}.com",
                phone="3456789012",
                role=B2BUser.Role.DRIVER
            )
            driver_user.set_password("password123")
            driver_user.save()

            # 5. Create Warehouses
            wh_hub = Warehouse.objects.create(
                company=comp,
                warehouse_name=f"{comp.company_name} Primary Hub",
                address=f"789 Warehouse Lane, {comp.company_name} City",
                capacity=15000,
                is_active=True
            )
            wh_secondary = Warehouse.objects.create(
                company=comp,
                warehouse_name=f"{comp.company_name} Secondary Hub",
                address=f"101 Annex Road, {comp.company_name} Outpost",
                capacity=5000,
                is_active=True
            )

            # 6. Create Products (ensure starting stock)
            prod1 = Product.objects.create(
                company=comp,
                warehouse=wh_hub,
                product_name="Ultra Widget Gold",
                product_version="3.2",
                sku_code=f"WG-GOLD-{suffix.upper()}",
                unit_price=120.00,
                total_manufactured=1000,
                stock_available=450,
                reorder_level=50,
                is_active=True
            )
            prod2 = Product.objects.create(
                company=comp,
                warehouse=wh_hub,
                product_name="Nano Widget Silver",
                product_version="1.0",
                sku_code=f"WS-SILV-{suffix.upper()}",
                unit_price=45.00,
                total_manufactured=2500,
                stock_available=1500,
                reorder_level=200,
                is_active=True
            )
            prod3 = Product.objects.create(
                company=comp,
                warehouse=wh_secondary,
                product_name="Standard Widget Bronze",
                product_version="5.4",
                sku_code=f"WB-BRON-{suffix.upper()}",
                unit_price=15.00,
                total_manufactured=5000,
                stock_available=30, # Low stock trigger demonstration!
                reorder_level=100,
                is_active=True
            )

            # Write Initial Inventory IN Logs
            for prod in [prod1, prod2, prod3]:
                InventoryLog.objects.create(
                    product=prod,
                    warehouse=prod.warehouse,
                    change_type="IN",
                    quantity=prod.stock_available,
                    reference_id=uuid.uuid4()
                )

            # 7. Create Clients
            client1 = Client.objects.create(
                company=comp,
                client_name=f"Enterprise Retailers ({suffix.upper()})",
                client_company="Enterprise LLC",
                address="12 Retail Mall, Commerce City",
                email=f"procurement@enterprise-{suffix}.com",
                phone="+1-800-RETAIL",
                is_active=True
            )
            client2 = Client.objects.create(
                company=comp,
                client_name=f"Global Distributors ({suffix.upper()})",
                client_company="Global Dist",
                address="56 Logistics Way, Transport Hub",
                email=f"orders@globaldist-{suffix}.com",
                phone="+1-888-GLOBAL",
                is_active=True
            )

            # 8. Create Drivers
            driver1 = Driver.objects.create(
                company=comp,
                created_by_manager=manager_profile,
                name=f"Dave Driver ({suffix.upper()})",
                phone="+1-555-DRV-1",
                license_no=f"LIC-DRV1-{suffix.upper()}",
                is_available=True,
                is_active=True,
                total_orders_delivered=42
            )
            driver2 = Driver.objects.create(
                company=comp,
                created_by_manager=manager_profile,
                name=f"Dan Driver ({suffix.upper()})",
                phone="+1-555-DRV-2",
                license_no=f"LIC-DRV2-{suffix.upper()}",
                is_available=True,
                is_active=True,
                total_orders_delivered=18
            )

            # 9. Create Routes
            route1 = Route.objects.create(
                company=comp,
                start_location=wh_hub.warehouse_name,
                end_location=client1.client_name,
                distance=24.50,
                estimated_time=45,
                is_active=True
            )
            route2 = Route.objects.create(
                company=comp,
                start_location=wh_secondary.warehouse_name,
                end_location=client2.client_name,
                distance=105.00,
                estimated_time=120,
                is_active=True
            )

            # 10. Orders & Shipments & Returns Simulations

            # Order A: Pending Flow
            order_pending = Order.objects.create(
                company=comp,
                client=client1,
                status=Order.Status.PENDING,
                payment_status=Order.PaymentStatus.PENDING
            )
            OrderItem.objects.create(
                order=order_pending,
                product=prod1,
                quantity=10,
                unit_price=prod1.unit_price
            )
            OrderItem.objects.create(
                order=order_pending,
                product=prod2,
                quantity=20,
                unit_price=prod2.unit_price
            )
            # Re-derive order pending total amount
            order_pending.total_amount = (10 * prod1.unit_price) + (20 * prod2.unit_price)
            order_pending.save()

            # Order B: Delivered with Shipment & Payment & Logs
            order_delivered = Order.objects.create(
                company=comp,
                client=client2,
                status=Order.Status.DELIVERED,
                payment_status=Order.PaymentStatus.PAID
            )
            OrderItem.objects.create(
                order=order_delivered,
                product=prod2,
                quantity=50,
                unit_price=prod2.unit_price
            )
            order_delivered.total_amount = 50 * prod2.unit_price
            order_delivered.save()

            # Create Payment record
            Payment.objects.create(
                order=order_delivered,
                amount=order_delivered.total_amount,
                payment_method="Bank_Transfer",
                payment_status="Paid",
                transaction_ref=f"TXN-{suffix.upper()}-99281"
            )

            # Create Shipment
            shipment = Shipment.objects.create(
                company=comp,
                order=order_delivered,
                from_warehouse=wh_hub,
                to_client=client2,
                driver=driver1,
                route=route1,
                status=Shipment.Status.DELIVERED,
                dispatch_time=timezone.now() - timezone.timedelta(days=1),
                estimated_delivery_time=timezone.now() - timezone.timedelta(hours=23),
                actual_delivery_time=timezone.now() - timezone.timedelta(hours=23, minutes=15),
                live_location="40.7128,-74.0060",
                proof_of_delivery="https://b2b-cloud-storage.s3.amazonaws.com/pod/receipt_signature.png"
            )

            # Inventory OUT log
            InventoryLog.objects.create(
                product=prod2,
                warehouse=wh_hub,
                change_type="OUT",
                quantity=50,
                reference_id=order_delivered.order_id
            )

            # Order C: Returned Flow (Simulating a received, verified reverse logistics item)
            order_returned = Order.objects.create(
                company=comp,
                client=client1,
                status=Order.Status.RETURNED,
                payment_status=Order.PaymentStatus.PAID
            )
            OrderItem.objects.create(
                order=order_returned,
                product=prod1,
                quantity=5,
                unit_price=prod1.unit_price
            )
            order_returned.total_amount = 5 * prod1.unit_price
            order_returned.save()

            # Return order
            return_order = ReturnedOrder.objects.create(
                company=comp,
                old_order=order_returned,
                client=client1,
                driver=driver2,
                return_reason="Damaged protective packaging on arrival",
                return_status=ReturnedOrder.ReturnStatus.RETURNED
            )
            ReturnedItem.objects.create(
                return_order=return_order,
                product=prod1,
                quantity=2,
                condition="Good"
            )
            ReturnedItem.objects.create(
                return_order=return_order,
                product=prod1,
                quantity=3,
                condition="Damaged"
            )

            # Inventory RETURN logs
            InventoryLog.objects.create(
                product=prod1,
                warehouse=wh_hub,
                change_type="RETURN",
                quantity=2,
                reference_id=return_order.return_id
            )
            InventoryLog.objects.create(
                product=prod1,
                warehouse=wh_hub,
                change_type="DAMAGE",
                quantity=3,
                reference_id=return_order.return_id
            )

            # Create Audit logs for simulation
            AuditLog.objects.create(
                user=admin_user,
                action="CREATE",
                module="order",
                reference_id=order_pending.order_id,
                new_value=f'{{"client": "{client1.client_name}", "status": "Pending", "items": 2}}'
            )
            AuditLog.objects.create(
                user=admin_user,
                action="UPDATE",
                module="product",
                reference_id=prod3.product_id,
                old_value=f'{{"stock_available": 130}}',
                new_value=f'{{"stock_available": 30}}'
            )

            # System Notifications
            Notification.objects.create(
                sent_to=admin_user,
                related_order=order_pending,
                type="ALERT",
                message=f"New B2B Order {order_pending.order_id} pending approval for client {client1.client_name}."
            )
            Notification.objects.create(
                sent_to=admin_user,
                type="SYSTEM",
                message=f"Stock warning: '{prod3.product_name}' has dropped below reorder level (30 / 100)."
            )

        self.stdout.write(self.style.SUCCESS("Database seeded successfully with beautiful visual logs and tenant isolation!"))
