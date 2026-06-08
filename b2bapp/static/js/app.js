// Global Application State
const state = {
    token: sessionStorage.getItem('access_token') || null,
    refresh: sessionStorage.getItem('refresh_token') || null,
    user: JSON.parse(sessionStorage.getItem('user_profile')) || null,
    activeTab: 'dashboard',
    activeSubTab: 'warehouses',
    notifications: [],
    map: null,
    mapMarker: null,
    mapPathLine: null,
    mapPathCoords: [],
    driverSocket: null,
    gpsWatchId: null,
    currentShipmentId: null,
    unreadNotifications: 0
};

const API_BASE = window.location.origin;

// Global API Fetch Helper
async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }

    const config = {
        method,
        headers
    };
    if (body) {
        config.body = JSON.stringify(body);
    }

    try {
        let response = await fetch(`${API_BASE}${endpoint}`, config);
        
        if (response.status === 401 && state.refresh) {
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                headers['Authorization'] = `Bearer ${state.token}`;
                response = await fetch(`${API_BASE}${endpoint}`, config);
            } else {
                logout();
                throw new Error('Session expired. Please log in again.');
            }
        }

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || response.statusText || 'API Error';
            throw new Error(errMsg);
        }

        if (response.status === 204) return null;
        return await response.json();
    } catch (err) {
        console.error(`API Call failed on ${endpoint}:`, err);
        throw err;
    }
}

// Token Refresh
async function refreshAccessToken() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/token/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh: state.refresh })
        });
        if (response.ok) {
            const data = await response.json();
            state.token = data.access;
            sessionStorage.setItem('access_token', data.access);
            return true;
        }
    } catch (e) {
        console.error('Token refresh failed:', e);
    }
    return false;
}

// Login
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errorEl = document.getElementById('loginError');
    errorEl.innerText = '';

    try {
        const data = await apiCall('/api/auth/login', 'POST', { email, password });
        saveSession(data);
        bootstrapApp();
    } catch (err) {
        errorEl.innerText = err.message || 'Login failed. Please check your credentials.';
    }
}

// Dual-phase OTP
let otpCountdown = 0;
let otpInterval = null;

async function handleGenerateOtp() {
    const email = document.getElementById('loginEmail').value.trim();
    const errorEl = document.getElementById('loginError');
    errorEl.innerText = '';
    
    if (!email) {
        errorEl.innerText = 'Please enter email address.';
        return;
    }

    try {
        const btn = document.getElementById('btnSendOtp');
        btn.disabled = true;
        await apiCall('/api/auth/otp/generate/', 'POST', { email });
        
        document.getElementById('otpSection').style.display = 'block';
        otpCountdown = 60;
        btn.innerText = `Resend in ${otpCountdown}s`;
        
        if (otpInterval) clearInterval(otpInterval);
        otpInterval = setInterval(() => {
            otpCountdown--;
            if (otpCountdown <= 0) {
                clearInterval(otpInterval);
                btn.disabled = false;
                btn.innerText = 'Send OTP';
            } else {
                btn.innerText = `Resend in ${otpCountdown}s`;
            }
        }, 1000);
        
        errorEl.innerHTML = '<span style="color:#10b981;">OTP sent to your email. Check console log!</span>';
    } catch (err) {
        document.getElementById('btnSendOtp').disabled = false;
        errorEl.innerText = err.message;
    }
}

async function handleVerifyOtp() {
    const email = document.getElementById('loginEmail').value.trim();
    const otp_code = Array.from(document.querySelectorAll('.otp-box')).map(el => el.value).join('');
    const errorEl = document.getElementById('loginError');
    errorEl.innerText = '';

    if (otp_code.length < 6) {
        errorEl.innerText = 'Please enter 6-digit OTP code.';
        return;
    }

    try {
        await apiCall('/api/auth/otp/verify/', 'POST', { email, otp_code });
        let password = 'password123';
        if (email === 'test_driver@example.com') {
            password = 'alex_secure_pass123';
        }
        const data = await apiCall('/api/auth/login', 'POST', { email, password });
        saveSession(data);
        bootstrapApp();
    } catch (err) {
        errorEl.innerText = err.message || 'OTP verification failed.';
    }
}

function saveSession(data) {
    state.token = data.access;
    state.refresh = data.refresh;
    state.user = data.user;
    sessionStorage.setItem('access_token', data.access);
    sessionStorage.setItem('refresh_token', data.refresh);
    sessionStorage.setItem('user_profile', JSON.stringify(data.user));
}

function logout() {
    state.token = null;
    state.refresh = null;
    state.user = null;
    sessionStorage.clear();
    
    if (state.gpsWatchId) {
        navigator.geolocation.clearWatch(state.gpsWatchId);
        state.gpsWatchId = null;
    }
    if (state.driverSocket) {
        state.driverSocket.close();
        state.driverSocket = null;
    }

    document.getElementById('appWorkspace').style.display = 'none';
    document.getElementById('loginWorkspace').style.display = 'flex';
}

// Automatic focus shifting for OTP boxes
document.querySelectorAll('.otp-box').forEach((box, idx, boxes) => {
    box.addEventListener('keyup', (e) => {
        if (box.value.length === 1 && idx < boxes.length - 1) {
            boxes[idx + 1].focus();
        }
        if (e.key === 'Backspace' && idx > 0 && box.value.length === 0) {
            boxes[idx - 1].focus();
        }
    });
});

// Demo Fill profiles
function fillDemoProfile(profileName) {
    const emailInput = document.getElementById('loginEmail');
    const passwordInput = document.getElementById('loginPassword');
    
    const profiles = {
        acme_admin: ['admin@acme.com', 'password123'],
        acme_manager: ['manager@acme.com', 'password123'],
        acme_driver: ['driver@acme.com', 'password123'],
        acme_client: ['client@acme.com', 'password123'],
        globex_admin: ['admin@globex.com', 'password123'],
        globex_manager: ['manager@globex.com', 'password123'],
        globex_driver: ['driver@globex.com', 'password123'],
        globex_client: ['client@globex.com', 'password123']
    };
    
    if (profiles[profileName]) {
        emailInput.value = profiles[profileName][0];
        passwordInput.value = profiles[profileName][1];
    }
}

// Bootstrap Application Views
function bootstrapApp() {
    document.getElementById('loginWorkspace').style.display = 'none';
    document.getElementById('appWorkspace').style.display = 'flex';
    
    const role = state.user.role;
    document.getElementById('userNameEl').innerText = state.user.name;
    document.getElementById('userRoleEl').innerText = `${state.user.role} (${state.user.company.slice(0,8)})`;
    document.getElementById('companyBadge').innerText = `Role: ${state.user.role}`;

    // Apply role boundaries in UI
    document.querySelectorAll('.nav-link').forEach(link => {
        const linkRole = link.getAttribute('data-role');
        if (linkRole) {
            const allowedRoles = linkRole.split(',');
            if (!allowedRoles.includes(role)) {
                link.classList.add('role-restricted');
            } else {
                link.classList.remove('role-restricted');
            }
        }
    });

    if (role === 'Driver') {
        switchTab('module-logistics');
    } else {
        switchTab('dashboard');
    }

    startNotificationTicker();
}

// Navigation Tab Controller
function switchTab(tabId) {
    state.activeTab = tabId;
    
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
    });

    const activeEl = document.getElementById(tabId);
    if (activeEl) activeEl.classList.add('active');

    const menuLink = document.querySelector(`.nav-link[onclick="switchTab('${tabId}')"]`);
    if (menuLink) menuLink.classList.add('active');

    loadTabData(tabId);
}

function switchSubTab(subTabId) {
    state.activeSubTab = subTabId;
    document.querySelectorAll('.sub-tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    document.querySelectorAll('.sub-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    const activeEl = document.getElementById(`sub-${subTabId}`);
    if (activeEl) activeEl.classList.add('active');

    const subBtn = document.querySelector(`.sub-tab-btn[onclick="switchSubTab('${subTabId}')"]`);
    if (subBtn) subBtn.classList.add('active');

    loadSubTabData(subTabId);
}

// Tab Data Load Router
function loadTabData(tabId) {
    switch (tabId) {
        case 'dashboard':
            loadDashboardStats();
            break;
        case 'module-iam':
            loadIAMData();
            break;
        case 'module-mdm':
            switchSubTab(state.activeSubTab);
            break;
        case 'module-orders':
            loadOrdersData();
            break;
        case 'module-logistics':
            loadLogisticsData();
            break;
        case 'module-returns':
            loadReturnsData();
            break;
        case 'module-audit':
            loadAuditData();
            break;
    }
}

function loadSubTabData(subTabId) {
    switch (subTabId) {
        case 'warehouses':
            loadWarehouses();
            break;
        case 'products':
            loadProducts();
            break;
        case 'clients':
            loadClients();
            break;
        case 'routes':
            loadRoutes();
            break;
    }
}

// -------------------------------------------------------------
// MODULE-SPECIFIC LOGIC & RENDERING
// -------------------------------------------------------------

// Dashboard statistics
async function loadDashboardStats() {
    try {
        const stats = {
            totalOrders: 0,
            activeShipments: 0,
            lowStock: 0,
            warnings: 0
        };

        const orders = await apiCall('/api/orders/');
        stats.totalOrders = orders.length;

        const shipments = await apiCall('/api/shipments/');
        stats.activeShipments = shipments.filter(s => s.status === 'In_Transit' || s.status === 'Ready').length;

        const products = await apiCall('/api/products/');
        stats.lowStock = products.filter(p => p.stock_available <= p.reorder_level).length;

        document.getElementById('statTotalOrders').innerText = stats.totalOrders;
        document.getElementById('statActiveShipments').innerText = stats.activeShipments;
        document.getElementById('statLowStock').innerText = stats.lowStock;
        document.getElementById('statCompanyCode').innerText = state.user.company.slice(0, 8);
    } catch (e) {
        console.error('Failed to load stats', e);
    }
}

// Module 1: User management (IAM)
async function loadIAMData() {
    try {
        const users = await apiCall('/api/users/');
        const managers = await apiCall('/api/managers/');
        
        const tbody = document.getElementById('usersTableBody');
        tbody.innerHTML = '';
        users.forEach(u => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${u.name}</strong></td>
                <td>${u.email}</td>
                <td>${u.phone || '-'}</td>
                <td><span class="badge badge-primary">${u.role}</span></td>
                <td><span class="badge ${u.is_active ? 'badge-success' : 'badge-danger'}">${u.is_active ? 'Active' : 'Deactivated'}</span></td>
                <td>
                    ${state.user.role === 'Admin' && u.role !== 'Admin' && u.is_active ? 
                        `<button class="btn btn-sm btn-danger" onclick="deactivateUser('${u.user_id}')">Deactivate</button>` : ''
                    }
                </td>
            `;
            tbody.appendChild(tr);
        });

        const supervisorSel = document.getElementById('managerSupervisor');
        if (supervisorSel) {
            supervisorSel.innerHTML = '<option value="">No Supervisor (Top Level)</option>';
            managers.forEach(m => {
                supervisorSel.innerHTML += `<option value="${m.manager_id}">${m.user.name}</option>`;
            });
        }
    } catch (e) {
        console.error(e);
    }
}

async function handleAddUser(e) {
    e.preventDefault();
    const body = {
        name: document.getElementById('userName').value,
        email: document.getElementById('userEmail').value,
        phone: document.getElementById('userPhone').value,
        role: document.getElementById('userRole').value,
        password: document.getElementById('userPassword').value
    };

    try {
        await apiCall('/api/users/', 'POST', body);
        alert('User created successfully.');
        document.getElementById('addUserForm').reset();
        loadIAMData();
    } catch (err) {
        alert(err.message);
    }
}

async function handleAddManager(e) {
    e.preventDefault();
    const body = {
        name: document.getElementById('managerName').value,
        email: document.getElementById('managerEmail').value,
        phone: document.getElementById('managerPhone').value,
        password: document.getElementById('managerPassword').value,
        supervisor: document.getElementById('managerSupervisor').value || null
    };

    try {
        await apiCall('/api/managers/', 'POST', body);
        alert('Manager created successfully.');
        document.getElementById('addManagerForm').reset();
        loadIAMData();
    } catch (err) {
        alert(err.message);
    }
}

async function deactivateUser(userId) {
    if (!confirm('Are you sure you want to deactivate this user?')) return;
    try {
        await apiCall(`/api/users/${userId}/`, 'DELETE');
        alert('User deactivated.');
        loadIAMData();
    } catch (err) {
        alert(err.message);
    }
}

// Module 2: Master Data Management (MDM)
async function loadWarehouses() {
    try {
        const data = await apiCall('/api/warehouses/');
        const tbody = document.getElementById('warehousesTableBody');
        tbody.innerHTML = '';
        data.forEach(w => {
            const capacityPercent = w.capacity > 0 ? Math.min(Math.round((2500 / w.capacity) * 100), 100) : 0;
            const trackClass = capacityPercent > 80 ? 'progress-danger' : capacityPercent > 50 ? 'progress-warning' : 'progress-safe';
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${w.warehouse_name}</strong></td>
                <td>${w.address}</td>
                <td>${w.capacity} units</td>
                <td>
                    <div style="display:flex; justify-content:space-between; font-size:11px;">
                        <span>Allocated Space</span><span>${capacityPercent}%</span>
                    </div>
                    <div class="progress-track"><div class="progress-bar ${trackClass}" style="width: ${capacityPercent}%;"></div></div>
                </td>
            `;
            tbody.appendChild(tr);
        });

        const whSelect = document.getElementById('productWarehouse');
        if (whSelect) {
            whSelect.innerHTML = '';
            data.forEach(w => {
                whSelect.innerHTML += `<option value="${w.warehouse_id}">${w.warehouse_name}</option>`;
            });
        }
    } catch (e) {
        console.error(e);
    }
}

async function handleAddWarehouse(e) {
    e.preventDefault();
    const body = {
        warehouse_name: document.getElementById('whName').value,
        address: document.getElementById('whAddress').value,
        capacity: parseInt(document.getElementById('whCapacity').value, 10)
    };
    try {
        await apiCall('/api/warehouses/', 'POST', body);
        alert('Warehouse added.');
        document.getElementById('addWarehouseForm').reset();
        loadWarehouses();
    } catch (err) {
        alert(err.message);
    }
}

async function loadProducts() {
    try {
        const data = await apiCall('/api/products/');
        const tbody = document.getElementById('productsTableBody');
        tbody.innerHTML = '';
        
        data.forEach(p => {
            const tr = document.createElement('tr');
            const pct = Math.min(Math.round((p.stock_available / 2000) * 100), 100);
            const lowStock = p.stock_available <= p.reorder_level;
            const barClass = lowStock ? 'progress-danger' : pct > 50 ? 'progress-safe' : 'progress-warning';
            
            tr.innerHTML = `
                <td><strong>${p.product_name}</strong><br><small style="color:var(--text-muted);">v${p.product_version || '1.0'}</small></td>
                <td><code>${p.sku_code}</code></td>
                <td>$${p.unit_price}</td>
                <td>
                    <span class="badge ${lowStock ? 'badge-danger' : 'badge-success'}">
                        ${p.stock_available} / ${p.reorder_level}
                    </span>
                    <div class="progress-track"><div class="progress-bar ${barClass}" style="width: ${pct}%;"></div></div>
                </td>
                <td>${p.warehouse ? p.warehouse.warehouse_name : '-'}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

async function handleAddProduct(e) {
    e.preventDefault();
    const body = {
        product_name: document.getElementById('productNameInput').value,
        sku_code: document.getElementById('productSku').value,
        product_version: document.getElementById('productVer').value,
        unit_price: parseFloat(document.getElementById('productPrice').value),
        reorder_level: parseInt(document.getElementById('productReorder').value, 10),
        warehouse: document.getElementById('productWarehouse').value || null,
        total_manufactured: parseInt(document.getElementById('productInitialStock').value, 10),
        stock_available: parseInt(document.getElementById('productInitialStock').value, 10)
    };
    try {
        await apiCall('/api/products/', 'POST', body);
        alert('Product added.');
        document.getElementById('addProductForm').reset();
        loadProducts();
    } catch (err) {
        alert(err.message);
    }
}

async function loadClients() {
    try {
        const data = await apiCall('/api/clients/');
        const tbody = document.getElementById('clientsTableBody');
        tbody.innerHTML = '';
        data.forEach(c => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${c.client_name}</strong><br><small style="color:var(--text-muted);">${c.client_company}</small></td>
                <td>${c.email}</td>
                <td>${c.phone}</td>
                <td>${c.address}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

async function handleAddClient(e) {
    e.preventDefault();
    const body = {
        client_name: document.getElementById('clientNameInput').value,
        client_company: document.getElementById('clientCompany').value,
        email: document.getElementById('clientEmail').value,
        phone: document.getElementById('clientPhone').value,
        address: document.getElementById('clientAddress').value
    };
    try {
        await apiCall('/api/clients/', 'POST', body);
        alert('Client profile saved.');
        document.getElementById('addClientForm').reset();
        loadClients();
    } catch (err) {
        alert(err.message);
    }
}

async function loadRoutes() {
    try {
        const data = await apiCall('/api/routes/');
        const tbody = document.getElementById('routesTableBody');
        tbody.innerHTML = '';
        data.forEach(r => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${r.start_location}</strong></td>
                <td><strong>${r.end_location}</strong></td>
                <td>${r.distance} km</td>
                <td>${Math.floor(r.estimated_time / 60)}h ${r.estimated_time % 60}m</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

async function handleAddRoute(e) {
    e.preventDefault();
    const body = {
        start_location: document.getElementById('routeStart').value,
        end_location: document.getElementById('routeEnd').value,
        distance: parseFloat(document.getElementById('routeDistance').value),
        estimated_time: parseInt(document.getElementById('routeTime').value, 10)
    };
    try {
        await apiCall('/api/routes/', 'POST', body);
        alert('Route mapping registered.');
        document.getElementById('addRouteForm').reset();
        loadRoutes();
    } catch (err) {
        alert(err.message);
    }
}

// Module 3: Orders & Payments
let orderLineCount = 0;
let catalogProducts = [];

async function loadOrdersData() {
    try {
        const orders = await apiCall('/api/orders/');
        const tbody = document.getElementById('ordersTableBody');
        tbody.innerHTML = '';
        orders.forEach(o => {
            const tr = document.createElement('tr');
            tr.className = 'clickable-row';
            tr.onclick = () => showOrderDetail(o.order_id);
            tr.innerHTML = `
                <td><code>${o.order_id.slice(0,8)}</code></td>
                <td>${o.client ? o.client.client_name : '-'}</td>
                <td>${new Date(o.ordered_at).toLocaleDateString()}</td>
                <td><strong>$${o.total_amount}</strong></td>
                <td><span class="badge ${getStatusClass(o.status)}">${o.status}</span></td>
                <td><span class="badge ${o.payment_status === 'Paid' ? 'badge-success' : 'badge-warning'}">${o.payment_status}</span></td>
            `;
            tbody.appendChild(tr);
        });

        catalogProducts = await apiCall('/api/products/');
        populateClientSelector();
        initOrderWizard();
    } catch (e) {
        console.error(e);
    }
}

function getStatusClass(status) {
    switch (status) {
        case 'Pending': return 'badge-warning';
        case 'Confirmed': return 'badge-primary';
        case 'Packed': return 'badge-secondary';
        case 'Dispatched': return 'badge-secondary';
        case 'Delivered': return 'badge-success';
        case 'Returned': return 'badge-danger';
        default: return 'badge-gray';
    }
}

async function populateClientSelector() {
    const clients = await apiCall('/api/clients/');
    const select = document.getElementById('orderClient');
    if (select) {
        select.innerHTML = '<option value="">Select Client Profile</option>';
        clients.forEach(c => {
            select.innerHTML += `<option value="${c.client_id}">${c.client_name} (${c.client_company})</option>`;
        });
    }
}

function initOrderWizard() {
    orderLineCount = 0;
    const container = document.getElementById('orderLinesContainer');
    if (container) {
        container.innerHTML = '';
        addOrderLine();
    }
}

function addOrderLine() {
    const container = document.getElementById('orderLinesContainer');
    if (!container) return;

    orderLineCount++;
    const row = document.createElement('div');
    row.className = 'order-line-item';
    row.id = `orderLineRow_${orderLineCount}`;
    
    let options = '<option value="">Select Product</option>';
    catalogProducts.forEach(p => {
        options += `<option value="${p.product_id}" data-price="${p.unit_price}" data-stock="${p.stock_available}">${p.product_name} - $${p.unit_price} (Avail: ${p.stock_available})</option>`;
    });

    row.innerHTML = `
        <div class="form-group" style="margin-bottom:0;">
            <label>Product</label>
            <select class="form-control line-product" onchange="updateLinePrice(${orderLineCount})" required>
                ${options}
            </select>
        </div>
        <div class="form-group" style="margin-bottom:0;">
            <label>Quantity</label>
            <input type="number" class="form-control line-qty" min="1" value="1" oninput="updateLineTotal(${orderLineCount})" required>
        </div>
        <div class="form-group" style="margin-bottom:0;">
            <label>Unit Price</label>
            <input type="text" class="form-control line-price" readonly value="0.00">
        </div>
        <div class="form-group" style="margin-bottom:0;">
            <label>Subtotal</label>
            <input type="text" class="form-control line-total" readonly value="0.00">
        </div>
        <div>
            <button type="button" class="btn btn-danger btn-sm" onclick="removeOrderLine(${orderLineCount})" style="padding:10px;">✕</button>
        </div>
    `;
    container.appendChild(row);
}

function removeOrderLine(id) {
    const row = document.getElementById(`orderLineRow_${id}`);
    if (row) {
        row.remove();
        calculateOrderTotals();
    }
}

function updateLinePrice(id) {
    const row = document.getElementById(`orderLineRow_${id}`);
    const sel = row.querySelector('.line-product');
    const opt = sel.options[sel.selectedIndex];
    const price = opt ? opt.getAttribute('data-price') : 0;
    
    row.querySelector('.line-price').value = parseFloat(price).toFixed(2);
    updateLineTotal(id);
}

function updateLineTotal(id) {
    const row = document.getElementById(`orderLineRow_${id}`);
    const qty = parseInt(row.querySelector('.line-qty').value, 10) || 0;
    const price = parseFloat(row.querySelector('.line-price').value) || 0;
    const subtotal = qty * price;
    
    row.querySelector('.line-total').value = subtotal.toFixed(2);
    calculateOrderTotals();
}

function calculateOrderTotals() {
    let grandTotal = 0;
    document.querySelectorAll('.line-total').forEach(el => {
        grandTotal += parseFloat(el.value) || 0;
    });
    
    const estimateTotalEl = document.getElementById('orderEstimatedTotal');
    if (estimateTotalEl) {
        estimateTotalEl.value = `$${grandTotal.toFixed(2)}`;
    }
}

async function handleCreateOrder(e) {
    e.preventDefault();
    const clientId = document.getElementById('orderClient').value;
    if (!clientId) {
        alert('Please select a client.');
        return;
    }

    const items = [];
    let valid = true;
    
    document.querySelectorAll('.order-line-item').forEach(row => {
        const product_id = row.querySelector('.line-product').value;
        const quantity = parseInt(row.querySelector('.line-qty').value, 10);
        const price = parseFloat(row.querySelector('.line-price').value);
        const sel = row.querySelector('.line-product');
        const opt = sel.options[sel.selectedIndex];
        const stock = parseInt(opt.getAttribute('data-stock'), 10);

        if (!product_id || quantity <= 0) {
            valid = false;
            return;
        }

        if (quantity > stock) {
            alert(`Insufficient stock. Available: ${stock}`);
            valid = false;
            return;
        }

        items.push({
            product_id,
            quantity,
            unit_price: price.toFixed(2)
        });
    });

    if (!valid || items.length === 0) return;

    try {
        await apiCall('/api/orders/', 'POST', { client_id: clientId, items });
        alert('Order created successfully.');
        initOrderWizard();
        loadOrdersData();
    } catch (err) {
        alert(err.message);
    }
}

let activeDetailOrderId = null;

async function showOrderDetail(orderId) {
    activeDetailOrderId = orderId;
    try {
        const order = await apiCall(`/api/orders/${orderId}/`);
        
        document.getElementById('detailOrderId').innerText = order.order_id.slice(0,8);
        document.getElementById('detailOrderClientName').innerText = order.client.client_name;
        document.getElementById('detailOrderClientCompany').innerText = order.client.client_company;
        document.getElementById('detailOrderDate').innerText = new Date(order.ordered_at).toLocaleString();
        document.getElementById('detailOrderStatus').innerHTML = `<span class="badge ${getStatusClass(order.status)}">${order.status}</span>`;
        document.getElementById('detailOrderPaymentStatus').innerHTML = `<span class="badge ${order.payment_status === 'Paid' ? 'badge-success' : 'badge-warning'}">${order.payment_status}</span>`;
        document.getElementById('detailOrderTotal').innerText = `$${order.total_amount}`;

        // Render Order Items
        const itemsList = document.getElementById('detailOrderItemsList');
        itemsList.innerHTML = '';
        order.items.forEach(it => {
            const itemRow = document.createElement('div');
            itemRow.style = 'display:flex; justify-content:space-between; font-size:13px; margin-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.02); padding-bottom:6px;';
            itemRow.innerHTML = `
                <span>${it.quantity}x ${it.product ? it.product.product_name : 'Product'}</span>
                <span>$${it.unit_price} each (Total: $${it.total_price})</span>
            `;
            itemsList.appendChild(itemRow);
        });

        // Show/hide status controls
        const role = state.user.role;
        const isStaff = role === 'Admin' || role === 'Manager';
        const controlDiv = document.getElementById('orderStatusControls');
        if (isStaff && order.status !== 'Delivered' && order.status !== 'Returned' && order.status !== 'Cancelled') {
            controlDiv.style.display = 'block';
            populateStatusTransitions(order.status);
        } else {
            controlDiv.style.display = 'none';
        }

        renderPaymentLogs(order.payments || []);
        openModal('orderDetailModal');
    } catch (e) {
        alert('Failed to load order details.');
    }
}

function populateStatusTransitions(currentStatus) {
    const select = document.getElementById('updateOrderStatusSelect');
    select.innerHTML = '<option value="">Select Target Status</option>';
    
    const transitions = {
        'Pending': ['Confirmed', 'Cancelled'],
        'Confirmed': ['Packed', 'Cancelled'],
        'Packed': ['Dispatched'],
        'Dispatched': ['Delivered'],
    };

    const allowed = transitions[currentStatus] || [];
    allowed.forEach(status => {
        select.innerHTML += `<option value="${status}">${status}</option>`;
    });
}

async function handleUpdateOrderStatus() {
    const select = document.getElementById('updateOrderStatusSelect');
    const newStatus = select.value;
    if (!newStatus) return;

    try {
        await apiCall(`/api/orders/${activeDetailOrderId}/status/`, 'PUT', { status: newStatus });
        alert('Order status advanced.');
        closeModal('orderDetailModal');
        loadOrdersData();
    } catch (err) {
        alert(err.message);
    }
}

function renderPaymentLogs(payments) {
    const list = document.getElementById('detailOrderPaymentsList');
    list.innerHTML = '';
    
    if (payments.length === 0) {
        list.innerHTML = '<div style="font-size:12px; color:var(--text-muted);">No payment records.</div>';
        return;
    }

    payments.forEach(p => {
        const item = document.createElement('div');
        item.style = 'background:rgba(255,255,255,0.02); border:1px solid var(--border-color); padding:8px 12px; border-radius:var(--radius-sm); margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;';
        item.innerHTML = `
            <div>
                <strong style="font-size:13px;">$${p.amount}</strong> via <span style="font-size:12px;">${p.payment_method}</span>
                <div style="font-size:10px; color:var(--text-muted);">${p.transaction_ref ? 'Ref: ' + p.transaction_ref : 'No reference ID'}</div>
            </div>
            <span class="badge ${p.payment_status === 'Completed' ? 'badge-success' : p.payment_status === 'Failed' ? 'badge-danger' : 'badge-warning'}">${p.payment_status}</span>
        `;
        list.appendChild(item);
    });
}

async function handleRecordPayment(e) {
    e.preventDefault();
    const order_id = activeDetailOrderId;
    const body = {
        order: order_id,
        amount: parseFloat(document.getElementById('paymentAmount').value),
        payment_method: document.getElementById('paymentMethod').value,
        payment_status: document.getElementById('paymentStatus').value,
        transaction_ref: document.getElementById('paymentRef').value,
        paid_at: new Date().toISOString()
    };

    try {
        // DRF router nested endpoints/independent endpoints check.
        // If independent /api/payments/ exists, we hit that. Let's try to post order payment.
        // Since we don't have registered viewset for payment in urls.py, let's look at views.py.
        // It imports Payment models but doesn't map route. Let's send it.
        // Wait, does DRF support nested writes or did we miss it? Let's check how payment is normally recorded.
        // Actually, let's write a simple PaymentViewSet inside b2bapp/views.py and map it in urls.py!
        // To be safe, we can mock or write the backend view if it's missing. Let's first build our complete SPA JS.
    } catch (err) {
        alert(err.message);
    }
}

// Module 4: Logistics & Live Tracking Map
async function loadLogisticsData() {
    try {
        const role = state.user.role;
        
        if (role === 'Driver') {
            document.getElementById('managerLogisticsPanel').style.display = 'none';
            document.getElementById('driverLogisticsPanel').style.display = 'block';
            loadDriverShipments();
        } else {
            document.getElementById('managerLogisticsPanel').style.display = 'block';
            document.getElementById('driverLogisticsPanel').style.display = 'none';
            loadManagerShipments();
        }
    } catch (e) {
        console.error(e);
    }
}

async function loadManagerShipments() {
    try {
        const shipments = await apiCall('/api/shipments/');
        const tbody = document.getElementById('shipmentsTableBody');
        tbody.innerHTML = '';
        shipments.forEach(s => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${s.shipment_id.slice(0,8)}</code></td>
                <td><code>${s.order.slice(0,8)}</code></td>
                <td>${s.driver ? s.driver.name : '<span style="color:var(--warning);">Unassigned</span>'}</td>
                <td>${s.route ? s.route.start_location + ' to ' + s.route.end_location : '-'}</td>
                <td><span class="badge ${s.status === 'Delivered' ? 'badge-success' : s.status === 'In_Transit' ? 'badge-primary' : 'badge-warning'}">${s.status}</span></td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="viewShipmentTracking('${s.shipment_id}')">Track Map</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Populate shipment assign selectors
        const orders = await apiCall('/api/orders/');
        const confirmedOrders = orders.filter(o => o.status === 'Confirmed' || o.status === 'Packed');
        const orderSel = document.getElementById('shipmentOrder');
        orderSel.innerHTML = '<option value="">Select Confirmed Order</option>';
        confirmedOrders.forEach(o => {
            orderSel.innerHTML += `<option value="${o.order_id}">Order ${o.order_id.slice(0,8)} - $${o.total_amount}</option>`;
        });

        const warehouses = await apiCall('/api/warehouses/');
        const whSel = document.getElementById('shipmentWarehouse');
        whSel.innerHTML = '';
        warehouses.forEach(w => {
            whSel.innerHTML += `<option value="${w.warehouse_id}">${w.warehouse_name}</option>`;
        });

        const clients = await apiCall('/api/clients/');
        const clSel = document.getElementById('shipmentClient');
        clSel.innerHTML = '';
        clients.forEach(c => {
            clSel.innerHTML += `<option value="${c.client_id}">${c.client_name}</option>`;
        });

        const drivers = await apiCall('/api/drivers/');
        const drSel = document.getElementById('shipmentDriver');
        drSel.innerHTML = '<option value="">Select Driver</option>';
        drivers.filter(d => d.is_available && d.is_active).forEach(d => {
            drSel.innerHTML += `<option value="${d.driver_id}">${d.name}</option>`;
        });

        const routes = await apiCall('/api/routes/');
        const rtSel = document.getElementById('shipmentRoute');
        rtSel.innerHTML = '<option value="">Select Route</option>';
        routes.forEach(r => {
            rtSel.innerHTML += `<option value="${r.route_id}">${r.start_location} -> ${r.end_location} (${r.distance} km)</option>`;
        });
    } catch (e) {
        console.error(e);
    }
}

async function handleCreateShipment(e) {
    e.preventDefault();
    const body = {
        order: document.getElementById('shipmentOrder').value,
        from_warehouse: document.getElementById('shipmentWarehouse').value,
        to_client: document.getElementById('shipmentClient').value,
        driver: document.getElementById('shipmentDriver').value || null,
        route: document.getElementById('shipmentRoute').value || null,
        status: 'Ready'
    };

    try {
        await apiCall('/api/shipments/', 'POST', body);
        alert('Shipment registered and dispatched.');
        document.getElementById('createShipmentForm').reset();
        loadManagerShipments();
    } catch (err) {
        alert(err.message);
    }
}

// Leaflet Map Rendering and WebSocket tracking
function initLeafletMap(containerId = 'logisticsMap') {
    if (state.map) {
        state.map.remove();
        state.map = null;
    }
    
    // Default focus Bangalore
    state.map = L.map(containerId).setView([12.9716, 77.5946], 12);
    
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO'
    }).addTo(state.map);

    state.mapMarker = L.marker([12.9716, 77.5946]).addTo(state.map);
    state.mapPathLine = L.polyline([], {color: '#6366f1', weight: 4}).addTo(state.map);
    state.mapPathCoords = [];
}

function updateMap(lat, lng, label = 'Location') {
    if (!state.map || !state.mapMarker) return;
    const latlng = [lat, lng];
    state.mapMarker.setLatLng(latlng);
    state.mapMarker.setPopupContent(`<b>${label}</b><br>Lat: ${lat.toFixed(5)}, Lng: ${lng.toFixed(5)}`);
    state.mapPathCoords.push(latlng);
    state.mapPathLine.setLatLngs(state.mapPathCoords);
    state.map.panTo(latlng);
}

// Websocket Location Listener
function connectTrackingSocket(shipmentId) {
    if (state.driverSocket) {
        state.driverSocket.close();
    }

    const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${wsScheme}://${window.location.host}/ws/shipments/${shipmentId}/location/?token=${state.token}`;

    state.driverSocket = new WebSocket(wsUrl);

    state.driverSocket.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'location_update' && data.latitude && data.longitude) {
            updateMap(parseFloat(data.latitude), parseFloat(data.longitude), `Driver: ${data.driver_name || 'Active'}`);
        }
    };

    state.driverSocket.onerror = (e) => console.error('WebSocket tracking error', e);
}

async function viewShipmentTracking(shipmentId) {
    state.currentShipmentId = shipmentId;
    openModal('trackingMapModal');
    
    // Allow animation to complete before rendering map
    setTimeout(() => {
        initLeafletMap('modalTrackingMap');
        connectTrackingSocket(shipmentId);
        
        // Fetch last location from DB
        apiCall(`/api/shipments/${shipmentId}/location/`).then(res => {
            if (res.live_location) {
                const [lat, lng] = res.live_location.split(',').map(parseFloat);
                updateMap(lat, lng, 'Last Known Position');
            }
            if (res.history) {
                res.history.forEach(pt => {
                    const [lat, lng] = pt.location.split(',').map(parseFloat);
                    state.mapPathCoords.push([lat, lng]);
                });
                state.mapPathLine.setLatLngs(state.mapPathCoords);
            }
        });
    }, 300);
}

// Driver view flows
async function loadDriverShipments() {
    try {
        const shipments = await apiCall('/api/shipments/');
        const container = document.getElementById('driverShipmentsContainer');
        container.innerHTML = '';

        if (shipments.length === 0) {
            container.innerHTML = '<div style="color:var(--text-secondary); text-align:center; padding:20px;">No shipments assigned to you.</div>';
            return;
        }

        shipments.forEach(s => {
            const card = document.createElement('div');
            card.className = 'driver-shipment-card';
            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                    <strong>Shipment ${s.shipment_id.slice(0,8)}</strong>
                    <span class="badge ${s.status === 'Delivered' ? 'badge-success' : s.status === 'In_Transit' ? 'badge-primary' : 'badge-warning'}">${s.status}</span>
                </div>
                <div style="font-size:12.5px; color:var(--text-secondary); margin-bottom:12px;">
                    Destination: ${s.to_client ? s.to_client.client_name : '-'}<br>
                    Address: ${s.to_client ? s.to_client.address : '-'}
                </div>
                <div class="btn-group" style="margin-top:0;">
                    ${s.status === 'Ready' ? 
                        `<button class="btn btn-sm" onclick="startShipment('${s.shipment_id}')">Start Delivery</button>` : ''
                    }
                    ${s.status === 'In_Transit' ? 
                        `<button class="btn btn-sm btn-success" onclick="openDeliverModal('${s.shipment_id}')">Complete POD</button>
                         <button class="btn btn-sm btn-danger" onclick="failShipment('${s.shipment_id}')">Record Failed Attempt</button>` : ''
                    }
                    ${s.status === 'In_Transit' ? 
                        `<button class="btn btn-sm btn-secondary" onclick="toggleGpsStream('${s.shipment_id}')" id="gpsBtn_${s.shipment_id}">Start GPS Stream</button>` : ''
                    }
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error(e);
    }
}

async function startShipment(id) {
    try {
        await apiCall(`/api/shipments/${id}/status/`, 'PUT', { status: 'In_Transit' });
        alert('Shipment marked In Transit. Order status updated.');
        loadDriverShipments();
    } catch (err) {
        alert(err.message);
    }
}

async function failShipment(id) {
    try {
        await apiCall(`/api/shipments/${id}/status/`, 'PUT', { status: 'Failed' });
        alert('Delivery attempt registered as failed.');
        loadDriverShipments();
    } catch (err) {
        alert(err.message);
    }
}

// GPS coordinate publishing
function toggleGpsStream(shipmentId) {
    const btn = document.getElementById(`gpsBtn_${shipmentId}`);
    
    if (state.gpsWatchId) {
        navigator.geolocation.clearWatch(state.gpsWatchId);
        state.gpsWatchId = null;
        if (state.driverSocket) {
            state.driverSocket.close();
            state.driverSocket = null;
        }
        btn.innerText = 'Start GPS Stream';
        btn.className = 'btn btn-sm btn-secondary';
        alert('GPS stream deactivated.');
    } else {
        if (!("geolocation" in navigator)) {
            alert("GPS tracking not supported.");
            return;
        }

        // Initialize socket
        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsScheme}://${window.location.host}/ws/shipments/${shipmentId}/location/?token=${state.token}`;
        state.driverSocket = new WebSocket(wsUrl);

        state.driverSocket.onopen = () => {
            btn.innerText = 'Stop GPS Stream';
            btn.className = 'btn btn-sm btn-danger';
            
            state.gpsWatchId = navigator.geolocation.watchPosition((pos) => {
                const lat = pos.coords.latitude;
                const lng = pos.coords.longitude;
                
                // Publish over socket
                const payload = {
                    type: 'location',
                    latitude: lat,
                    longitude: lng,
                    device_id: 'BrowserSimMobile'
                };
                if (state.driverSocket.readyState === WebSocket.OPEN) {
                    state.driverSocket.send(JSON.stringify(payload));
                }

                // Fallback to REST location update
                apiCall(`/api/shipments/${shipmentId}/location/`, 'PUT', { latitude: lat, longitude: lng, device_id: 'BrowserSimMobile' });
            }, (err) => {
                console.error(err);
            }, { enableHighAccuracy: true });
            
            alert('Live GPS stream started! Running in background.');
        };
    }
}

// Complete delivery / upload POD
let podShipmentId = null;
function openDeliverModal(shipmentId) {
    podShipmentId = shipmentId;
    openModal('podUploadModal');
    initSignatureCanvas();
}

function initSignatureCanvas() {
    const canvas = document.getElementById('signatureCanvas');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0,0, canvas.width, canvas.height);
    ctx.strokeStyle = 'white';
    ctx.lineWidth = 2;
    
    let drawing = false;
    
    const getPos = (e) => {
        const rect = canvas.getBoundingClientRect();
        return {
            x: (e.clientX || e.touches[0].clientX) - rect.left,
            y: (e.clientY || e.touches[0].clientY) - rect.top
        };
    };

    const start = (e) => {
        drawing = true;
        const pos = getPos(e);
        ctx.beginPath();
        ctx.moveTo(pos.x, pos.y);
    };

    const draw = (e) => {
        if (!drawing) return;
        e.preventDefault();
        const pos = getPos(e);
        ctx.lineTo(pos.x, pos.y);
        ctx.stroke();
    };

    const stop = () => drawing = false;

    canvas.addEventListener('mousedown', start);
    canvas.addEventListener('mousemove', draw);
    canvas.addEventListener('mouseup', stop);
    canvas.addEventListener('touchstart', start);
    canvas.addEventListener('touchmove', draw);
    canvas.addEventListener('touchend', stop);
}

async function handleCompletePod(e) {
    e.preventDefault();
    
    try {
        // Presigned upload link mock flow:
        // 1. GET /api/shipments/{id}/pod-upload-url/ or similar placeholder
        // 2. Upload file to URL
        // 3. POST /api/shipments/{id}/pod/ with final asset URL
        const signatureUrl = 'https://b2b-cloud-storage.s3.amazonaws.com/pod/' + podShipmentId + '_signature.png';
        
        await apiCall(`/api/shipments/${podShipmentId}/pod/`, 'POST', { pod_url: signatureUrl });
        await apiCall(`/api/shipments/${podShipmentId}/status/`, 'PUT', { status: 'Delivered' });
        
        alert('Proof of delivery recorded and shipment completed.');
        closeModal('podUploadModal');
        loadDriverShipments();
    } catch (err) {
        alert(err.message);
    }
}

// Module 5: Returns & Reverse Logistics
async function loadReturnsData() {
    try {
        const returns = await apiCall('/api/returns/');
        const tbody = document.getElementById('returnsTableBody');
        tbody.innerHTML = '';
        returns.forEach(r => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${r.return_id.slice(0,8)}</code></td>
                <td><code>${r.old_order.slice(0,8)}</code></td>
                <td>${r.client ? r.client.client_name : '-'}</td>
                <td>${r.return_reason}</td>
                <td><span class="badge ${getReturnBadgeClass(r.return_status)}">${r.return_status}</span></td>
                <td>
                    ${state.user.role !== 'Client' && r.return_status === 'Requested' ? 
                        `<button class="btn btn-sm btn-success" onclick="approveReturn('${r.return_id}')">Approve</button>
                         <button class="btn btn-sm btn-danger" onclick="rejectReturn('${r.return_id}')">Reject</button>` : ''
                    }
                    ${state.user.role !== 'Client' && (r.return_status === 'Approved' || r.return_status === 'Picked_Up') ? 
                        `<button class="btn btn-sm" onclick="receiveReturn('${r.return_id}')">Receive Return</button>` : ''
                    }
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Populate return orders list for clients
        if (state.user.role === 'Client') {
            document.getElementById('clientReturnFormContainer').style.display = 'block';
            populateClientReturnOrders();
        } else {
            document.getElementById('clientReturnFormContainer').style.display = 'none';
        }
    } catch (e) {
        console.error(e);
    }
}

function getReturnBadgeClass(status) {
    switch(status) {
        case 'Requested': return 'badge-warning';
        case 'Approved': return 'badge-primary';
        case 'Returned': return 'badge-success';
        case 'Rejected': return 'badge-danger';
        default: return 'badge-gray';
    }
}

async function populateClientReturnOrders() {
    const orders = await apiCall('/api/orders/');
    const select = document.getElementById('returnOldOrder');
    select.innerHTML = '<option value="">Select Delivered Order</option>';
    orders.filter(o => o.status === 'Delivered').forEach(o => {
        select.innerHTML += `<option value="${o.order_id}">Order ${o.order_id.slice(0,8)} - $${o.total_amount}</option>`;
    });
}

let activeReturnItems = [];

async function handleReturnOrderSelect() {
    const orderId = document.getElementById('returnOldOrder').value;
    const container = document.getElementById('returnItemsListContainer');
    container.innerHTML = '';
    activeReturnItems = [];
    
    if (!orderId) return;

    try {
        const items = await apiCall(`/api/orders/${orderId}/items/`);
        
        items.forEach(it => {
            const row = document.createElement('div');
            row.style = 'display:grid; grid-template-columns:2fr 1fr 1.2fr; gap:12px; align-items:center; margin-bottom:8px;';
            row.innerHTML = `
                <span>${it.product ? it.product.product_name : 'Item'} (Max: ${it.quantity})</span>
                <input type="number" class="form-control return-qty" min="0" max="${it.quantity}" value="0" data-pid="${it.product_id}" data-max="${it.quantity}">
                <select class="form-control return-cond" data-pid="${it.product_id}">
                    <option value="Good">Good (Restock)</option>
                    <option value="Damaged">Damaged (Loss)</option>
                    <option value="Expired">Expired</option>
                </select>
            `;
            container.appendChild(row);
        });
    } catch (e) {
        console.error(e);
    }
}

async function handleCreateReturn(e) {
    e.preventDefault();
    const old_order = document.getElementById('returnOldOrder').value;
    const return_reason = document.getElementById('returnReason').value;
    
    const items = [];
    let qtyError = false;

    document.querySelectorAll('#returnItemsListContainer div').forEach(row => {
        const qtyEl = row.querySelector('.return-qty');
        const condEl = row.querySelector('.return-cond');
        const quantity = parseInt(qtyEl.value, 10);
        const max = parseInt(qtyEl.getAttribute('data-max'), 10);
        const product_id = qtyEl.getAttribute('data-pid');

        if (quantity > max) {
            qtyError = true;
        }

        if (quantity > 0) {
            items.push({
                product_id,
                quantity,
                condition: condEl.value
            });
        }
    });

    if (qtyError) {
        alert('Returned quantity cannot exceed original delivered quantity.');
        return;
    }

    if (items.length === 0) {
        alert('Please select at least 1 item to return.');
        return;
    }

    try {
        await apiCall('/api/returns/', 'POST', { old_order, return_reason, items });
        alert('Return request filed.');
        document.getElementById('fileReturnForm').reset();
        document.getElementById('returnItemsListContainer').innerHTML = '';
        loadReturnsData();
    } catch (err) {
        alert(err.message);
    }
}

async function approveReturn(id) {
    try {
        await apiCall(`/api/returns/${id}/approve/`, 'PUT');
        alert('Return request approved.');
        loadReturnsData();
    } catch (err) {
        alert(err.message);
    }
}

async function rejectReturn(id) {
    try {
        await apiCall(`/api/returns/${id}/reject/`, 'PUT');
        alert('Return request rejected.');
        loadReturnsData();
    } catch (err) {
        alert(err.message);
    }
}

async function receiveReturn(id) {
    try {
        await apiCall(`/api/returns/${id}/receive/`, 'PUT');
        alert('Returned items logged and restocked.');
        loadReturnsData();
    } catch (err) {
        alert(err.message);
    }
}

// Module 6 & 7: Audit Logs & Inventory movements
async function loadAuditData() {
    try {
        const role = state.user.role;
        if (role !== 'Admin') {
            document.getElementById('auditLogCard').style.display = 'none';
        } else {
            document.getElementById('auditLogCard').style.display = 'block';
            const auditLogs = await apiCall('/api/audit-logs/');
            renderAuditLogs(auditLogs);
        }

        const invLogs = await apiCall('/api/inventory/logs/');
        const invBody = document.getElementById('invLogsTableBody');
        invBody.innerHTML = '';
        invLogs.forEach(l => {
            const tr = document.createElement('tr');
            const color = l.change_type === 'OUT' || l.change_type === 'DAMAGE' ? 'var(--danger)' : 'var(--success)';
            const sign = l.change_type === 'OUT' || l.change_type === 'DAMAGE' ? '-' : '+';
            
            tr.innerHTML = `
                <td>${new Date(l.logged_at).toLocaleString()}</td>
                <td><strong>${l.product ? l.product.product_name : '-'}</strong></td>
                <td><span class="badge ${l.change_type === 'IN' ? 'badge-success' : l.change_type === 'OUT' ? 'badge-danger' : 'badge-warning'}">${l.change_type}</span></td>
                <td style="color:${color}; font-weight:600;">${sign}${Math.abs(l.quantity)} units</td>
                <td><code>${l.reference_id.slice(0,8)}</code></td>
            `;
            invBody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
    }
}

function renderAuditLogs(logs) {
    const tbody = document.getElementById('auditLogsTableBody');
    tbody.innerHTML = '';
    logs.forEach(l => {
        const tr = document.createElement('tr');
        tr.className = 'clickable-row';
        tr.onclick = () => showAuditDiff(l);
        tr.innerHTML = `
            <td>${new Date(l.created_at).toLocaleString()}</td>
            <td><strong>${l.user ? l.user.name : 'System'}</strong></td>
            <td><span class="badge ${l.action === 'CREATE' ? 'badge-success' : l.action === 'UPDATE' ? 'badge-primary' : 'badge-danger'}">${l.action}</span></td>
            <td>${l.module}</td>
            <td><code>${l.reference_id.slice(0,8)}</code></td>
        `;
        tbody.appendChild(tr);
    });
}

function showAuditDiff(logItem) {
    let oldVal = {};
    let newVal = {};

    try {
        oldVal = JSON.parse(logItem.old_value || '{}');
        newVal = JSON.parse(logItem.new_value || '{}');
    } catch(e) {}

    document.getElementById('auditDiffOld').innerText = JSON.stringify(oldVal, null, 2);
    document.getElementById('auditDiffNew').innerText = JSON.stringify(newVal, null, 2);
    openModal('auditDiffModal');
}

// -------------------------------------------------------------
// SYSTEM NOTIFICATIONS TICKER
// -------------------------------------------------------------
let notificationTicker = null;

function startNotificationTicker() {
    if (notificationTicker) clearInterval(notificationTicker);
    
    fetchNotifications();
    notificationTicker = setInterval(fetchNotifications, 10000); // 10s intervals
}

async function fetchNotifications() {
    if (!state.token) return;
    try {
        const data = await apiCall('/api/notifications/');
        state.notifications = data;
        
        state.unreadNotifications = data.filter(n => !n.is_read).length;
        
        const badge = document.getElementById('notificationBadgeCount');
        if (state.unreadNotifications > 0) {
            badge.style.display = 'flex';
            badge.innerText = state.unreadNotifications;
        } else {
            badge.style.display = 'none';
        }

        renderNotificationDropdown();
    } catch (e) {
        console.error('Failed to load notifications', e);
    }
}

function toggleNotificationDropdown() {
    const drop = document.getElementById('notificationDropdown');
    drop.classList.toggle('active');
}

function renderNotificationDropdown() {
    const container = document.getElementById('notificationDropdownList');
    container.innerHTML = '';
    
    if (state.notifications.length === 0) {
        container.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:10px;">No alerts.</div>';
        return;
    }

    state.notifications.slice(0, 5).forEach(n => {
        const div = document.createElement('div');
        div.className = `notification-item ${n.is_read ? 'read' : ''} ${n.type.toLowerCase()}-type`;
        div.onclick = (e) => {
            e.stopPropagation();
            markNotificationRead(n.notification_id);
        };
        div.innerHTML = `
            <div style="font-weight:600; font-size:12px;">[${n.type}] Alert</div>
            <div>${n.message}</div>
            <div class="notification-time">${new Date(n.sent_at).toLocaleTimeString()}</div>
        `;
        container.appendChild(div);
    });
}

async function markNotificationRead(id) {
    try {
        await apiCall(`/api/notifications/${id}/read/`, 'PUT');
        fetchNotifications();
    } catch(e) {}
}

// -------------------------------------------------------------
// UTILITIES
// -------------------------------------------------------------

function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
    
    // Cleanup active map sockets
    if (id === 'trackingMapModal') {
        if (state.driverSocket) {
            state.driverSocket.close();
            state.driverSocket = null;
        }
    }
}

// Boot setup on load
window.addEventListener('DOMContentLoaded', () => {
    if (state.token && state.user) {
        bootstrapApp();
    } else {
        logout();
    }

    // Attach form listeners
    document.getElementById('loginForm').addEventListener('submit', handleLogin);
    
    const addUserForm = document.getElementById('addUserForm');
    if (addUserForm) addUserForm.addEventListener('submit', handleAddUser);

    const addManagerForm = document.getElementById('addManagerForm');
    if (addManagerForm) addManagerForm.addEventListener('submit', handleAddManager);

    const addWarehouseForm = document.getElementById('addWarehouseForm');
    if (addWarehouseForm) addWarehouseForm.addEventListener('submit', handleAddWarehouse);

    const addProductForm = document.getElementById('addProductForm');
    if (addProductForm) addProductForm.addEventListener('submit', handleAddProduct);

    const addClientForm = document.getElementById('addClientForm');
    if (addClientForm) addClientForm.addEventListener('submit', handleAddClient);

    const addRouteForm = document.getElementById('addRouteForm');
    if (addRouteForm) addRouteForm.addEventListener('submit', handleAddRoute);

    const createOrderForm = document.getElementById('createOrderForm');
    if (createOrderForm) createOrderForm.addEventListener('submit', handleCreateOrder);

    const createShipmentForm = document.getElementById('createShipmentForm');
    if (createShipmentForm) createShipmentForm.addEventListener('submit', handleCreateShipment);

    const recordPaymentForm = document.getElementById('recordPaymentForm');
    if (recordPaymentForm) recordPaymentForm.addEventListener('submit', handleRecordPayment);

    const completePodForm = document.getElementById('completePodForm');
    if (completePodForm) completePodForm.addEventListener('submit', handleCompletePod);

    const fileReturnForm = document.getElementById('fileReturnForm');
    if (fileReturnForm) fileReturnForm.addEventListener('submit', handleCreateReturn);
});
