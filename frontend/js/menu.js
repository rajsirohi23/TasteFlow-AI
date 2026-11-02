"use strict";

// TasteFlow Bistro — frontend menu logic
// This version uses sample data. It does not place real orders.

const state = {
  menu: [],
  cart: new Map(),
  category: "All",
  search: "",
  diet: "all",
  maxPrice: Infinity,
};

const elements = {
  grid: document.getElementById("menu-grid"),
  search: document.getElementById("menu-search"),
  diet: document.getElementById("diet-filter"),
  price: document.getElementById("price-filter"),
  categories: document.getElementById("category-list"),
  results: document.getElementById("results-count"),
  cartCount: document.getElementById("cart-count"),
  drawerCount: document.getElementById("drawer-item-count"),
  openCart: document.getElementById("open-cart"),
  closeCart: document.getElementById("close-cart"),
  drawer: document.getElementById("cart-drawer"),
  backdrop: document.getElementById("drawer-backdrop"),
  cartItems: document.getElementById("cart-items"),
  total: document.getElementById("cart-total"),
  checkout: document.getElementById("checkout-button"),
  toast: document.getElementById("toast"),
  tryAssistant: document.getElementById("try-assistant"),
  customerName: document.getElementById("customer-name"),
};

let toastTimer;
let previousFocus = null;

// Escape text before inserting data into HTML.
function escapeHTML(value) {
  return String(value).replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

function formatPrice(amount) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");

  clearTimeout(toastTimer);

  toastTimer = setTimeout(() => {
    elements.toast.classList.remove("show");
  }, 2500);
}

function getDietLabel(tags) {
  if (tags.includes("vegan")) return "Vegan";
  if (tags.includes("vegetarian")) return "Vegetarian";
  return "Non-vegetarian";
}

function getFilteredMenu() {
  const query = state.search.trim().toLowerCase();

  return state.menu.filter((item) => {
    const searchableText = [
      item.name,
      item.category,
      item.description,
      ...(item.ingredients || []),
      ...(item.dietary_tags || []),
    ]
      .join(" ")
      .toLowerCase();

    const matchesSearch = searchableText.includes(query);

    const matchesCategory =
      state.category === "All" || item.category === state.category;

    const matchesDiet =
      state.diet === "all" || (item.dietary_tags || []).includes(state.diet);

    const matchesPrice = item.price <= state.maxPrice;

    return matchesSearch && matchesCategory && matchesDiet && matchesPrice;
  });
}

function renderMenu() {
  const items = getFilteredMenu();

  elements.results.textContent = `${items.length} ${items.length === 1 ? "dish" : "dishes"} found`;

  if (items.length === 0) {
    elements.grid.innerHTML = `
      <div class="empty-state">
        <h3>No matching dishes yet</h3>
        <p>Try a different search or change your filters.</p>
        <button type="button" data-action="reset-filters">
          Clear all filters
        </button>
      </div>
    `;
    return;
  }

  elements.grid.innerHTML = items
    .map((item) => {
      const tags = item.dietary_tags || [];
      const ingredients = item.ingredients || [];
      const available = item.available === true;
      const quantity = state.cart.get(item.id) || 0;

      return `
      <article class="food-card">
        <div class="food-image-wrap">
          <img
            class="food-image"
            src="${escapeHTML(item.image)}"
            alt="${escapeHTML(item.name)}"
            loading="lazy"
          >

          <span class="diet-badge">
            ${escapeHTML(getDietLabel(tags))}
          </span>

          ${
            !available
              ? `
            <span class="unavailable-badge">Unavailable</span>
          `
              : ""
          }
        </div>

        <div class="food-info">
          <div class="food-meta">
            <span>${escapeHTML(item.category)}</span>
            <span class="spice-label">
              ${escapeHTML(item.spice_level)} spice
            </span>
          </div>

          <div class="food-title-row">
            <h3>${escapeHTML(item.name)}</h3>
            <span class="food-price">${formatPrice(item.price)}</span>
          </div>

          <p class="food-description">
            ${escapeHTML(item.description)}
          </p>

          <div class="food-tags">
            ${tags
              .map(
                (tag) => `
              <span class="food-tag">${escapeHTML(tag)}</span>
            `,
              )
              .join("")}

            ${ingredients
              .slice(0, 2)
              .map(
                (ingredient) => `
              <span class="food-tag">${escapeHTML(ingredient)}</span>
            `,
              )
              .join("")}
          </div>

          <div class="food-card-footer">
            <span class="availability ${available ? "" : "unavailable"}">
              ${available ? "● Available (demo)" : "● Currently unavailable"}
            </span>

            <button
              class="add-button"
              type="button"
              data-action="add"
              data-id="${item.id}"
              ${!available ? "disabled" : ""}
            >
              ${quantity > 0 ? `+ Add more (${quantity})` : "+ Add"}
            </button>
          </div>
        </div>
      </article>
    `;
    })
    .join("");

  // Give a useful fallback if a food image cannot load.
  elements.grid.querySelectorAll(".food-image").forEach((image) => {
    image.addEventListener(
      "error",
      () => {
        image.style.display = "none";
        image.parentElement.style.minHeight = "100px";
      },
      { once: true },
    );
  });
}

function getCartItems() {
  return [...state.cart.entries()]
    .map(([id, quantity]) => {
      const item = state.menu.find((dish) => dish.id === id);

      if (!item || !item.available || quantity <= 0) {
        return null;
      }

      return {
        ...item,
        quantity,
        subtotal: item.price * quantity,
      };
    })
    .filter(Boolean);
}

function renderCart() {
  const items = getCartItems();

  const count = items.reduce((sum, item) => sum + item.quantity, 0);

  const total = items.reduce((sum, item) => sum + item.subtotal, 0);

  elements.cartCount.textContent = count;
  elements.drawerCount.textContent = `(${count})`;
  elements.total.textContent = formatPrice(total);
  elements.checkout.disabled = count === 0;

  if (items.length === 0) {
    elements.cartItems.innerHTML = `
      <div class="empty-cart">
        <span>♧</span>
        <h3>Your cart is taking a little break.</h3>
        <p>Add a dish from the menu to get started.</p>
      </div>
    `;
    return;
  }

  elements.cartItems.innerHTML = items
    .map(
      (item) => `
    <div class="cart-item">
      <img
        src="${escapeHTML(item.image)}"
        alt=""
      >

      <div>
        <h3>${escapeHTML(item.name)}</h3>
        <span class="cart-item-price">
          ${formatPrice(item.subtotal)}
        </span>

        <div class="quantity-controls">
          <button
            type="button"
            data-action="decrease"
            data-id="${item.id}"
            aria-label="Decrease ${escapeHTML(item.name)} quantity"
          >−</button>

          <span>${item.quantity}</span>

          <button
            type="button"
            data-action="increase"
            data-id="${item.id}"
            aria-label="Increase ${escapeHTML(item.name)} quantity"
          >+</button>
        </div>
      </div>

      <button
        type="button"
        class="icon-button"
        data-action="remove"
        data-id="${item.id}"
        aria-label="Remove ${escapeHTML(item.name)}"
      >✕</button>
    </div>
  `,
    )
    .join("");
}

function addToCart(id) {
  const item = state.menu.find((dish) => dish.id === id);

  if (!item || item.available !== true) {
    showToast("Sorry, this dish is not available.");
    return;
  }

  state.cart.set(id, (state.cart.get(id) || 0) + 1);

  renderMenu();
  renderCart();

  showToast(`${item.name} added to your demo cart.`);
}


window.addToCartByName = function (dishName) {
  const normalizedName = String(dishName || "").trim().toLowerCase();

  const item = state.menu.find(
    (dish) => dish.name.trim().toLowerCase() === normalizedName
  );

  if (!item) {
    showToast(`Couldn't find "${dishName}" in the customer menu.`);
    return false;
  }

  if (item.available !== true) {
    showToast(`${item.name} is currently unavailable.`);
    return false;
  }

  addToCart(Number(item.id));
  return true;
};


window.addToCart = addToCart;

function changeQuantity(id, difference) {
  const item = state.menu.find((dish) => dish.id === id);

  if (!item || item.available !== true) return;

  const currentQuantity = state.cart.get(id) || 0;
  const nextQuantity = currentQuantity + difference;

  if (nextQuantity <= 0) {
    state.cart.delete(id);
  } else {
    state.cart.set(id, nextQuantity);
  }

  renderMenu();
  renderCart();
}

function removeFromCart(id) {
  state.cart.delete(id);
  renderMenu();
  renderCart();
  showToast("Item removed from your cart.");
}

function resetFilters() {
  state.category = "All";
  state.search = "";
  state.diet = "all";
  state.maxPrice = Infinity;

  elements.search.value = "";
  elements.diet.value = "all";
  elements.price.value = "all";

  elements.categories.querySelectorAll(".category-chip").forEach((button) => {
    button.classList.toggle("active", button.dataset.category === "All");
  });

  renderMenu();
}

function openCart() {
  previousFocus = document.activeElement;

  elements.drawer.classList.add("open");
  elements.drawer.setAttribute("aria-hidden", "false");
  elements.drawer.inert = false;
  elements.backdrop.hidden = false;
  document.body.classList.add("drawer-open");

  elements.closeCart.focus();
}

function closeCart() {
  elements.drawer.classList.remove("open");
  elements.drawer.setAttribute("aria-hidden", "true");
  elements.drawer.inert = true;
  elements.backdrop.hidden = true;
  document.body.classList.remove("drawer-open");

  if (previousFocus && typeof previousFocus.focus === "function") {
    previousFocus.focus();
  }
}

// Event delegation: handle menu buttons through one listener.
elements.grid.addEventListener("click", (event) => {
  const resetButton = event.target.closest('[data-action="reset-filters"]');

  if (resetButton) {
    resetFilters();
    return;
  }

  const button = event.target.closest('[data-action="add"]');

  if (button) {
    addToCart(Number(button.dataset.id));
  }
});

elements.cartItems.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");

  if (!button) return;

  const id = Number(button.dataset.id);

  switch (button.dataset.action) {
    case "increase":
      changeQuantity(id, 1);
      break;
    case "decrease":
      changeQuantity(id, -1);
      break;
    case "remove":
      removeFromCart(id);
      break;
  }
});

elements.categories.addEventListener("click", (event) => {
  const button = event.target.closest("[data-category]");

  if (!button) return;

  state.category = button.dataset.category;

  elements.categories.querySelectorAll(".category-chip").forEach((chip) => {
    chip.classList.toggle("active", chip === button);
  });

  renderMenu();
});

elements.search.addEventListener("input", (event) => {
  state.search = event.target.value;
  renderMenu();
});

elements.diet.addEventListener("change", (event) => {
  state.diet = event.target.value;
  renderMenu();
});

elements.price.addEventListener("change", (event) => {
  state.maxPrice =
    event.target.value === "all" ? Infinity : Number(event.target.value);

  renderMenu();
});

elements.openCart.addEventListener("click", openCart);
elements.closeCart.addEventListener("click", closeCart);
elements.backdrop.addEventListener("click", closeCart);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.drawer.classList.contains("open")) {
    closeCart();
  }

  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }

  // Keep keyboard focus within the open cart dialog.
  if (event.key === "Tab" && elements.drawer.classList.contains("open")) {
    const focusable = elements.drawer.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
    );

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});


/* Submit the cart after the customer reviews the server-generated preview. */
let orderSubmitting = false;

elements.checkout.addEventListener("click", async () => {
  if (orderSubmitting) return;

  const items = getCartItems();

  if (items.length === 0) {
    showToast("Your cart is empty.");
    return;
  }

  const customerName = elements.customerName.value.trim();

  if (customerName.length < 2) {
    showToast("Please enter your name (at least 2 characters).");
    elements.customerName.focus();
    return;
  }

  orderSubmitting = true;
  elements.checkout.disabled = true;
  elements.checkout.textContent = "Preparing preview...";

  try {
    const orderPayload = {
      customer_name: customerName,
      items: items.map((item) => ({
        menu_item_id: item.id,
        quantity: item.quantity,
      })),
    };

    // Step 1: Request an order preview from the backend.
    const previewResponse = await fetch(
      window.TASTEFLOW_API_BASE + "/api/agents/orders/preview",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(orderPayload),
      },
    );

    const preview = await previewResponse.json();

    if (!previewResponse.ok) {
      const message =
        typeof preview.detail === "string"
          ? preview.detail
          : JSON.stringify(preview.detail || preview);

      throw new Error(message || "Unable to prepare order preview.");
    }

    const orderSummary = preview.items
      .map(
        (item) =>
          `${item.name} × ${item.quantity} — ${formatPrice(item.subtotal)}`,
      )
      .join("\n");

    // Step 2: Ask for explicit customer confirmation.
    const confirmed = window.confirm(
      `Review your order\n\n` +
        `${orderSummary}\n\n` +
        `Total items: ${preview.total_items}\n` +
        `Total amount: ${formatPrice(preview.total_amount)}\n` +
        `Customer: ${preview.customer_name}\n\n` +
        `No payment will be collected.\n\n` +
        `Confirm and place this order?`,
    );

    if (!confirmed) return;

    elements.checkout.textContent = "Placing order...";

    // Step 3: Submit the order through the existing order API.
    const response = await fetch(window.TASTEFLOW_API_BASE + "/api/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(orderPayload),
    });

    const result = await response.json();

    if (!response.ok) {
      const message =
        typeof result.detail === "string"
          ? result.detail
          : JSON.stringify(result.detail || result);

      throw new Error(message || `Order failed: HTTP ${response.status}`);
    }

    // Clear the cart only after the backend confirms order creation.
    state.cart.clear();
    renderMenu();
    renderCart();

    showToast(
      `Order #${result.id} placed successfully! Total: ${formatPrice(result.total_amount)}. Opening live tracking…`,
    );

    // Take the guest straight to live tracking (countdown, progress, cancel, rating).
    if (result.tracking_code) {
      sessionStorage.setItem("tasteflow.track.code", result.tracking_code);
      setTimeout(() => { window.location.href = "track.html?code=" + encodeURIComponent(result.tracking_code); }, 1800);
    }
  } catch (error) {
    console.error("TasteFlow checkout error:", error);
    showToast(`Checkout failed: ${error.message}`);
  } finally {
    orderSubmitting = false;
    elements.checkout.innerHTML = "Place order <span>→</span>";
    elements.checkout.disabled = getCartItems().length === 0;
  }
});


if (elements.tryAssistant) {
  elements.tryAssistant.addEventListener("click", () => {
    showToast("The AI assistant is ready below.");
  });
}

// Load the live menu from the TasteFlow backend API.
const API_BASE_URL = window.TASTEFLOW_API_BASE;

async function initializeMenu() {
  elements.grid.innerHTML = `
    <div class="loading-state">Loading the latest menu...</div>
  `;

  elements.results.textContent = "Loading dishes...";

  try {
    const response = await fetch(`${API_BASE_URL}/api/menu`);

    if (!response.ok) {
      throw new Error(`Menu request failed: HTTP ${response.status}`);
    }

    const menu = await response.json();

    if (!Array.isArray(menu) || menu.length === 0) {
      throw new Error("The backend returned an empty menu.");
    }

    // Check that the backend returns the fields the UI needs.
    const validMenu = menu.every(
      (item) =>
        Number.isInteger(item.id) &&
        typeof item.name === "string" &&
        Number.isFinite(Number(item.price)) &&
        Number(item.price) >= 0 &&
        typeof item.available === "boolean" &&
        Array.isArray(item.dietary_tags) &&
        Array.isArray(item.ingredients),
    );

    if (!validMenu) {
      throw new Error("The backend returned invalid menu data.");
    }

    // Normalize numeric fields before using them in the cart.
    state.menu = menu.map((item) => ({
      ...item,
      price: Number(item.price),
    }));

    renderMenu();
    renderCart();

    showToast("Live menu loaded successfully.");
  } catch (error) {
    console.error("TasteFlow menu loading error:", error);

    elements.results.textContent = "Menu could not be loaded";

    elements.grid.innerHTML = `
      <div class="empty-state">
        <h3>We couldn't load the menu.</h3>
        <p>
          Make sure the TasteFlow backend is running
          at ${API_BASE_URL} and try again.
        </p>
        <button type="button" data-action="retry">
          Try again
        </button>
      </div>
    `;
  }
}

// Allow customers to retry if the API request fails.
elements.grid.addEventListener("click", (event) => {
  if (event.target.closest('[data-action="retry"]')) {
    initializeMenu();
  }
});

initializeMenu();
