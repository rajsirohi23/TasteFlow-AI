
"use strict";

const API_BASE_URL = window.TASTEFLOW_API_BASE;

const elements = {
  orders: document.getElementById("kitchen-orders"),
  status: document.getElementById("kitchen-status"),
  refresh: document.getElementById("refresh-orders"),
  pending: document.getElementById("pending-count"),
  preparing: document.getElementById("preparing-count"),
  ready: document.getElementById("ready-count"),
  completed: document.getElementById("completed-count")
};

let menuById = new Map();
let activeOrders = [];
let allOrders = [];
let busyOrderIds = new Set();

const nextStatus = {
  pending: "preparing",
  preparing: "ready",
  ready: "completed"
};

function formatPrice(amount) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0
  }).format(Number(amount) || 0);
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function formatDate(value) {
  if (!value) return "Date unavailable";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Date unavailable";
  }

  return date.toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function fetchJSON(url, options = {}) {
  // Kitchen routes need a kitchen (or owner) PIN; the shared client prompts for it.
  return TasteFlowAPI.request(url, options, "kitchen");
}

function updateSummary() {
  const counts = {
    pending: 0,
    preparing: 0,
    ready: 0,
    completed: 0
  };

  allOrders.forEach(order => {
    if (Object.hasOwn(counts, order.status)) {
      counts[order.status]++;
    }
  });

  elements.pending.textContent = counts.pending;
  elements.preparing.textContent = counts.preparing;
  elements.ready.textContent = counts.ready;
  elements.completed.textContent = counts.completed;
}

function renderOrders() {
  if (activeOrders.length === 0) {
    elements.orders.innerHTML = `
      <div class="kitchen-message">
        <h3>No active orders</h3>
        <p>New customer orders will appear here when you refresh.</p>
      </div>
    `;
    return;
  }

  elements.orders.innerHTML = activeOrders.map(order => {
    const status = String(order.status || "pending").toLowerCase();
    const safeStatus = ["pending", "preparing", "ready", "completed"]
      .includes(status) ? status : "pending";

    const items = Array.isArray(order.items) ? order.items : [];
    const isBusy = busyOrderIds.has(order.id);
    const targetStatus = nextStatus[safeStatus];

    const itemRows = items.map(item => {
      const menuItem = menuById.get(item.menu_item_id);
      const name = menuItem?.name || `Menu item #${item.menu_item_id}`;
      const quantity = Number(item.quantity) || 0;

      return `
        <li>
          <span>${escapeHTML(name)}</span>
          <strong>× ${quantity}</strong>
        </li>
      `;
    }).join("");

    const actionButton = targetStatus ? `
      <button
        class="primary-action"
        type="button"
        data-action="advance"
        data-order-id="${order.id}"
        ${isBusy ? "disabled" : ""}
      >
        ${isBusy ? "Updating..." : `Mark ${targetStatus}`}
      </button>
    ` : `
      <span class="kitchen-order-meta">Order completed</span>
    `;

    return `
      <article class="kitchen-order-card">
        <div class="kitchen-order-top">
          <div>
            <h3>Order #${order.id}</h3>
            <div class="kitchen-order-meta">
              ${escapeHTML(order.customer_name || "Customer")}
            </div>
            <div class="kitchen-order-meta">
              ${escapeHTML(formatDate(order.created_at))}
            </div>
          </div>

          <span class="kitchen-badge status-${safeStatus}">
            ${escapeHTML(safeStatus)}
          </span>
        </div>

        <ul class="kitchen-item-list">
          ${itemRows || "<li>Order items unavailable</li>"}
        </ul>

        <div class="kitchen-order-bottom">
          <span class="kitchen-total">
            ${formatPrice(order.total_amount)}
          </span>

          <div class="kitchen-order-actions">
            ${actionButton}
          </div>
        </div>
      </article>
    `;
  }).join("");
}

async function loadOrders() {
  elements.refresh.disabled = true;
  elements.status.textContent = "Loading latest orders...";

  try {
    const [kitchenData, orderData, menuData] = await Promise.all([
      fetchJSON(`${API_BASE_URL}/api/kitchen/orders?limit=100&offset=0`),
      fetchJSON(`${API_BASE_URL}/api/orders?limit=100&offset=0`),
      fetchJSON(`${API_BASE_URL}/api/menu`)
    ]);

    if (!Array.isArray(kitchenData) ||
        !Array.isArray(orderData) ||
        !Array.isArray(menuData)) {
      throw new Error("The API returned an unexpected response format.");
    }

    menuById = new Map(menuData.map(item => [item.id, item]));

    // Kitchen endpoint provides the orders currently active in the kitchen.
    activeOrders = kitchenData.filter(order =>
      ["pending", "preparing", "ready"].includes(
        String(order.status).toLowerCase()
      )
    );

    // Use the general order endpoint for all four summary counts.
    allOrders = orderData.filter(order =>
      order.status !== "cancelled"
    );

    updateSummary();
    renderOrders();

    elements.status.textContent =
      `Kitchen orders loaded successfully. ${activeOrders.length} active order(s).`;
  } catch (error) {
    console.error("Kitchen dashboard error:", error);

    elements.status.textContent = `Could not load orders: ${error.message}`;

    elements.orders.innerHTML = `
      <div class="kitchen-message">
        <h3>Unable to load orders</h3>
        <p>${escapeHTML(error.message)}</p>
        <p>Check that the backend is running on port 8000.</p>
      </div>
    `;
  } finally {
    elements.refresh.disabled = false;
  }
}

async function advanceOrder(orderId) {
  const order = activeOrders.find(item => item.id === orderId);

  if (!order || busyOrderIds.has(orderId)) return;

  const currentStatus = String(order.status).toLowerCase();
  const targetStatus = nextStatus[currentStatus];

  if (!targetStatus) return;

  const confirmed = window.confirm(
    `Move Order #${orderId} from ${currentStatus} to ${targetStatus}?`
  );

  if (!confirmed) return;

  busyOrderIds.add(orderId);
  renderOrders();
  elements.status.textContent = `Updating Order #${orderId}...`;

  try {
    await fetchJSON(
      `${API_BASE_URL}/api/kitchen/orders/${orderId}/status`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          status: targetStatus
        })
      }
    );

    elements.status.textContent =
      `Order #${orderId} updated to ${targetStatus}.`;

    await loadOrders();
  } catch (error) {
    console.error("Order status update failed:", error);

    elements.status.textContent =
      `Could not update Order #${orderId}: ${error.message}`;
  } finally {
    busyOrderIds.delete(orderId);
    renderOrders();
  }
}

elements.refresh.addEventListener("click", loadOrders);

elements.orders.addEventListener("click", event => {
  const button = event.target.closest('[data-action="advance"]');

  if (!button) return;

  const orderId = Number(button.dataset.orderId);

  if (Number.isInteger(orderId)) {
    advanceOrder(orderId);
  }
});

loadOrders();
