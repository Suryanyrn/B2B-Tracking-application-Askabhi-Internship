import json
from rest_framework.test import APITestCase
from rest_framework import status
from .models import Company, User, Warehouse, Product, Client, Route, Driver, Order, Shipment

class B2BWorkflowTest(APITestCase):
    def setUp(self):
        # 1. Create a Company
        self.company = Company.objects.create(
            company_name="Acme Corp", email="contact@acme.com", phone="1234567890"
        )
        
        # 2. Create Admin User
        self.admin = User.objects.create(
            company=self.company,
            name="Alice Admin",
            email="admin@acme.com",
            phone="0987654321",
            role=User.Role.ADMIN,
        )
        self.admin.set_password("password123")
        self.admin.save()
        
        # 3. Create Client User
        self.client_user = User.objects.create(
            company=self.company,
            name="Bob Client",
            email="client@acme.com",
            phone="1111111111",
            role=User.Role.CLIENT,
        )
        self.client_user.set_password("password123")
        self.client_user.save()
        
        # 4. Create Driver User
        self.driver_user = User.objects.create(
            company=self.company,
            name="Dave Driver",
            email="driver@acme.com",
            phone="2222222222",
            role=User.Role.DRIVER,
        )
        self.driver_user.set_password("password123")
        self.driver_user.save()

    def test_full_workflow(self):
        # Authenticate as Admin
        response = self.client.post("/api/auth/login", {
            "email": "admin@acme.com", "password": "password123"
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        admin_token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + admin_token)
        
        # Create Warehouse
        response = self.client.post("/api/warehouses/", {
            "warehouse_name": "Main Hub",
            "address": "123 Hub Lane",
            "capacity": 10000,
            "is_active": True
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        warehouse_id = response.data["warehouse_id"]
        
        # Create Product
        response = self.client.post("/api/products/", {
            "warehouse": warehouse_id,
            "product_name": "Widget X",
            "product_version": "1.0",
            "sku_code": "WX-001",
            "unit_price": 50.00,
            "total_manufactured": 100,
            "reorder_level": 10,
            "is_active": True
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        product_id = response.data["product_id"]
        
        # Manually set stock since there's no API endpoint for stock ingestion yet
        Product.objects.filter(pk=product_id).update(stock_available=100)
        
        # Create Client Profile
        response = self.client.post("/api/clients/", {
            "client_name": "Bob Client Profile",
            "client_company": "Bob's Shop",
            "address": "456 Shop St",
            "email": "client@acme.com",
            "phone": "1111111111",
            "is_active": True
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        client_id = response.data["client_id"]
        
        # Create Driver Profile
        response = self.client.post("/api/drivers/", {
            "name": "Dave Driver",
            "phone": "2222222222",
            "license_no": "DL12345",
            "is_active": True
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        driver_id = response.data["driver_id"]
        
        # Authenticate as Client to Create Order
        response = self.client.post("/api/auth/login", {
            "email": "client@acme.com", "password": "password123"
        })
        client_token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + client_token)
        
        print("ALL CLIENTS:", list(Client.objects.values('client_id', 'is_active')))
        print("ALL PRODUCTS:", list(Product.objects.values('product_id', 'is_active')))
        
        response = self.client.post("/api/orders/", {
            "client": client_id,
            "items": [{"product": product_id, "quantity": 10}]
        }, format='json')
        if response.status_code != 201:
            print("ORDER CREATION FAILED", response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order_id = response.data["order_id"]
        
        # Check stock deducted
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + admin_token)
        response = self.client.get(f"/api/products/{product_id}/")
        self.assertEqual(response.data["stock_available"], 90)
        
        # Admin Updates Order Status
        response = self.client.put(f"/api/orders/{order_id}/status/", {"status": "Confirmed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.put(f"/api/orders/{order_id}/status/", {"status": "Packed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Admin Creates Shipment
        response = self.client.post("/api/shipments/", {
            "order": order_id,
            "from_warehouse": warehouse_id,
            "to_client": client_id,
            "driver": driver_id
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        shipment_id = response.data["shipment_id"]
        
        # Authenticate as Driver
        response = self.client.post("/api/auth/login", {
            "email": "driver@acme.com", "password": "password123"
        })
        driver_token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + driver_token)
        
        # Driver updates shipment to In_Transit
        response = self.client.put(f"/api/shipments/{shipment_id}/status/", {"status": "In_Transit"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check parent order synced to Dispatched
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + admin_token)
        response = self.client.get(f"/api/orders/{order_id}/")
        self.assertEqual(response.data["status"], "Dispatched")
        
        # Driver updates shipment to Delivered
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + driver_token)
        response = self.client.put(f"/api/shipments/{shipment_id}/status/", {"status": "Delivered"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check parent order synced to Delivered
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + admin_token)
        response = self.client.get(f"/api/orders/{order_id}/")
        self.assertEqual(response.data["status"], "Delivered")
        
        # Client requests a return
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + client_token)
        response = self.client.post("/api/returns/", {
            "old_order": order_id,
            "return_reason": "Not needed",
            "return_items": [{"product": product_id, "quantity": 5, "condition": "Good"}]
        }, format='json')
        if response.status_code != 201:
            print("RETURN CREATION FAILED", response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return_id = response.data["return_id"]
        
        # Check stock not yet added back!
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + admin_token)
        response = self.client.get(f"/api/products/{product_id}/")
        self.assertEqual(response.data["stock_available"], 90)
        
        # Admin approves the return
        response = self.client.put(f"/api/returns/{return_id}/approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Admin receives the return
        response = self.client.put(f"/api/returns/{return_id}/receive/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check order synced to Returned
        response = self.client.get(f"/api/orders/{order_id}/")
        self.assertEqual(response.data["status"], "Returned")
        
        # Check stock added back! (90 + 5 = 95)
        response = self.client.get(f"/api/products/{product_id}/")
        self.assertEqual(response.data["stock_available"], 95)
        
        print("ALL TESTS PASSED: WORKFLOW IS SMOOTH AND GOOD")

    def test_admin_and_manager_workflow(self):
        # 1. Register a new company (Public endpoint)
        company_data = {
            "company_name": "Globex Corp",
            "email": "contact@globex.com",
            "phone": "9876543210",
            "address": "123 Globex Way"
        }
        response = self.client.post("/api/companies/", company_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        company_id = response.data["company_id"]

        # 2. Link Admin to the company on successful creation via the create_admin endpoint
        admin_data = {
            "name": "Alice Admin",
            "email": "alice@globex.com",
            "password": "password123",
            "phone": "123456789"
        }
        response = self.client.post(f"/api/companies/{company_id}/create_admin/", admin_data)
        if response.status_code != 201:
            print("CREATE ADMIN FAILED WITH STATUS:", response.status_code)
            print("CONTENT:", response.content)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("admin", response.data)
        admin_id = response.data["admin"]["admin_id"]

        # 3. Authenticate as the newly created Admin
        response = self.client.post("/api/auth/login", {
            "email": "alice@globex.com",
            "password": "password123"
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        admin_token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + admin_token)

        # 4. Admin adds a new Manager for their company
        manager_data = {
            "name": "Mark Manager",
            "email": "mark@globex.com",
            "password": "password123",
            "phone": "55555555"
        }
        response = self.client.post("/api/managers/", manager_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        manager_id = response.data["manager_id"]
        self.assertEqual(str(response.data["created_by_admin"]), str(admin_id))

        # 5. Admin adds a sub-Manager supervised by Mark
        sub_manager_data = {
            "name": "Molly Manager",
            "email": "molly@globex.com",
            "password": "password123",
            "phone": "44444444",
            "supervisor": manager_id
        }
        response = self.client.post("/api/managers/", sub_manager_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sub_manager_id = response.data["manager_id"]
        self.assertEqual(str(response.data["supervisor"]), str(manager_id))

        # 6. Authenticate as Molly Manager
        response = self.client.post("/api/auth/login", {
            "email": "molly@globex.com",
            "password": "password123"
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        molly_token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + molly_token)

        # 7. Molly Manager adds a Driver for their company
        driver_data = {
            "name": "Dan Driver",
            "phone": "3333333333",
            "license_no": "LIC99999"
        }
        response = self.client.post("/api/drivers/", driver_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data["created_by_manager"]), str(sub_manager_id))
        self.assertEqual(response.data["created_by_manager_name"], "Molly Manager")

        print("ADMIN, MANAGER, AND DRIVER ASSIGNMENT TESTS PASSED SUCCESSFULLY!")

from django.core import mail
from .models import OTPVerification

class OTPWorkflowTest(APITestCase):
    def test_otp_generation_and_verification(self):
        # 1. Generate OTP
        response = self.client.post("/api/auth/otp/generate/", {"email": "test@example.com"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "OTP sent successfully.")
        
        # Verify email was sent (Django uses locmem backend in tests automatically)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Your B2B System OTP Code")
        self.assertIn("Your one-time password (OTP) is:", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["test@example.com"])
        
        # 2. Extract OTP from DB (to simulate user reading email)
        otp_record = OTPVerification.objects.get(email="test@example.com")
        otp_code = otp_record.otp_code
        
        # 3. Verify OTP successfully
        response = self.client.post("/api/auth/otp/verify/", {
            "email": "test@example.com",
            "otp_code": otp_code
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "OTP verified successfully.")
        
        # 4. Verify OTP fails on reuse
        response = self.client.post("/api/auth/otp/verify/", {
            "email": "test@example.com",
            "otp_code": otp_code
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "OTP has expired or already used.")
        
        print("OTP GENERATION & VERIFICATION TESTS PASSED SUCCESSFULLY!")
