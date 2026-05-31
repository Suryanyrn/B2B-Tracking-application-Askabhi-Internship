# B2B Platform: System Workflow & Technical Reference
*Document tailored for Stakeholders & Development Review*

## 1. System Workflow Overview
The B2B Tracking Application is a multi-tenant logistics and tracking platform designed to manage the full supply chain lifecycle from inventory and order creation to physical logistics, delivery, and reverse logistics (returns).

### **Core Workflow Flow**
1. **Identity & Multi-Tenancy (Module 1):** Companies (tenants) are onboarded. Employees (Admins, Managers, Drivers) and external parties (Clients) are assigned to the company. Every record is scoped to its specific Company. Role-based Access Control (RBAC) governs the actions each user can take. Secure authentication uses OTP and JWT.
2. **Master Data & Inventory Management (Module 2 & 6):** Admins and Managers define Warehouses, Routes, and Clients. Products are added to Warehouses, establishing initial inventory logs.
3. **Order Placement (Module 3):** A Client places an Order. This reserves items from the inventory. Order totals are computed strictly on the backend to prevent tampering.
4. **Logistics & Dispatch (Module 4):** A Manager/Admin groups Orders into Shipments, assigns a Driver, and a Route. The Driver's live GPS location updates via WebSockets and REST fallbacks while en route. Upon delivery, the Driver uploads a Proof of Delivery (POD).
5. **Reverse Logistics / Returns (Module 5):** Clients can initiate a Return for delivered items. Upon Manager/Admin approval and physical receipt, inventory is either restored or marked damaged, and an updated Return Inventory Log is made.
6. **Auditing & Notifications (Module 7):** Stakeholders receive system notifications (via email/SMS/app) for key actions (e.g., low stock, delivery status changes). A strictly append-only `AuditLog` captures every structural modification in the system for complete compliance.

---

## 2. Database Architecture (Models & Tables)
*The platform utilizes 19 isolated database tables structurally grouped into 7 distinct business modules.*

### Module 1: Identity & Authorization
- **`Company`**: Represents a tenant organization on the platform. Establishes strict multi-tenant isolation.
- **`User`**: Base profile for all individuals. Holds role specifications (Admin, Manager, Client, Driver) and secure password hashes.
- **`Admin`**: Administrator profile auto-created when a company is registered. Has supreme rights over the tenant's data.
- **`Manager`**: Staff profile responsible for daily supply chain tasks and Driver supervision. Created by an Admin.
- **`OTPVerification`**: Transient table managing 6-digit one-time passwords for secure onboarding/authentication flows.

### Module 2: Master Data Management (MDM)
- **`Warehouse`**: Physical storage locations defined by capacity metrics.
- **`Product`**: Sellable inventory items. Includes `stock_available` limits and `reorder_level` triggers.
- **`Client`**: External buyers mapped to a specific tenant company.
- **`Route`**: Pre-determined geographical paths utilized for dispatching shipments, with estimated transit times.

### Module 3: Order Management
- **`Order`**: A core revenue transaction mapped to a Client. Transitions through statuses like Pending, Dispatched, Delivered, and Returned.
- **`OrderItem`**: A singular line item linking a `Product` to an `Order`. Enforces that the `total_price` equals `unit_price × quantity` directly on the server.
- **`Payment`**: Independent transactional log bound to Orders to allow tracking of payment success and multiple retries.

### Module 4: Logistics & Live Tracking
- **`Driver`**: Logistics personnel responsible for completing `Shipments`. Monitors `total_orders_delivered` and `current_location`.
- **`Shipment`**: The physical dispatch record of an `Order`. Tracks ETA, live GPS location via WebSockets, Delivery Attempts, and secure Pre-Signed Cloud Storage URLs for Proof of Delivery.

### Module 5: Returns & Reverse Logistics
- **`ReturnedOrder`**: Initiated strictly against previously Delivered Orders. Maintains the overarching reason and approval status.
- **`ReturnedItem`**: Sub-components of the Return. Validates that return quantities do not exceed original order capacities. 

### Module 6: Inventory Ledger
- **`InventoryLog`**: The most critical financial ledger. It is immutable (append-only) tracking all stock movements (IN, OUT, RETURN, DAMAGE) preventing race conditions via database-level `select_for_update()`.

### Module 7: Notifications & Auditing
- **`Notification`**: Broadcasts alerts internally and externally regarding state changes (e.g., Low Stock).
- **`AuditLog`**: A comprehensive, tamper-proof history of every CREATE, UPDATE, or DELETE action. Preserves `old_value` and `new_value` in JSON.

---

## 3. API Reference & Interactions
*The platform exposes robust RESTful APIs following conventional CRUD logic via Django REST Framework ViewSets and customized endpoints.*

### Authentication & Identity APIs
- **POST `/api/auth/login`**: Accepts `{"email": "...", "password": "..."}`. Returns `{"access": "...", "refresh": "..."}` JWT tokens.
- **POST `/api/auth/otp/generate/`**: Accepts `{"email": "..."}`. Initiates SMTP service to email a 6-digit code.
- **POST `/api/auth/otp/verify/`**: Accepts `{"email": "...", "otp_code": "..."}`. Validates the transient OTP code.
- **POST `/api/companies/`**: Public endpoint. Accepts `{"company_name": "...", "email": "...", ...}` to create a new Tenant Space. 

### Master Data APIs
- **CRUD `/api/warehouses/`, `/api/products/`, `/api/clients/`, `/api/routes/`**: Admin/Manager routes for configuration.
- **GET `/api/products/{id}/stock/`**: Lightweight endpoint providing immediate `stock_available` snapshots to Client frontends.

### Operational APIs (Orders & Shipments)
- **POST `/api/orders/`**: 
  - *Format*: `{"client": "client_uuid", "items": [{"product": "product_uuid", "quantity": 10}]}`
  - *Logic*: Atomic transaction. Fails safely if an item is out of stock. Calculates totals internally.
- **PUT `/api/orders/{id}/status/`**: 
  - *Format*: `{"status": "Confirmed" | "Packed"}`
  - *Logic*: Manager overrides to shift order state.
- **POST `/api/shipments/`**: 
  - *Format*: `{"order": "uuid", "from_warehouse": "uuid", "to_client": "uuid", "driver": "uuid"}`.
- **PUT `/api/shipments/{id}/status/`** & **POST `/api/shipments/{id}/pod/`**: Driver-only APIs mapping the transition from *In_Transit* to *Delivered* using secure Proof of Delivery image links.

### Reverse Logistics (Returns)
- **POST `/api/returns/`**: 
  - *Format*: `{"old_order": "uuid", "return_reason": "Broken", "return_items": [{"product": "uuid", "quantity": 2, "condition": "Damaged"}]}`
  - *Logic*: Initiates a review. Can only happen post-Delivery.
- **PUT `/api/returns/{id}/approve/`** & **PUT `/api/returns/{id}/reject/`**: Manager actions handling the approval state.
- **PUT `/api/returns/{id}/receive/`**: Finalizes return, generating Return/Damage Inventory logs and adjusting available stock logic.

---

## 4. System Validation & Seeding
The integrity and business logic stability of the aforementioned workflows are structurally guaranteed by two distinct mechanisms:

### Automated Validation (`tests.py`)
Provides strict regression and logic verification via Python `unittest` workflows:
- **`B2BWorkflowTest`**: Executes the complete supply chain lifecycle programmatically without manual intervention. It tests tenant creation, product induction, live stock deduction upon Order creation, logistics dispatch, simulated driver deliveries, and proper numerical additions to the Inventory module post-Return authorization.
- **`OTPWorkflowTest`**: Directly tests the transient nature of the SMTP email functionality. Asserts that an OTP is accurately created, validates a correct user submission, and rigorously ensures it *cannot be reused* once consumed.
- **Multi-Tenant Tests**: Verify that Managers can only see data relative to their `Company`, protecting enterprise privacy.

### Visualization & Initialization (`seed_data.py`)
This Django management command (`python manage.py seed_data`) acts as a critical visualization tool for stakeholders:
- **Data Cleanup**: Purges old conflicting state safely.
- **Multi-Tenant Generation**: Seamlessly builds overlapping, yet isolated data for two companies ("Acme Corp" and "Globex Inc").
- **Rich State Generation**: Pre-populates all modules including initial Master Data (`Warehouses`, `Drivers`, `Clients`), populates robust `InventoryLog` traces, establishes simulated Orders in multiple states (Pending, Delivered, Returned), and drafts simulated `Shipments` with pseudo GPS coordinates and Pod URLs.
- **Audit Proving**: Generates visual representations of System `Notification` alerts and robust `AuditLog` JSON trails so stakeholders can immediately inspect the traceability of the system on any frontend panel connected to the API.
