
"use strict";

const API_BASE_URL = window.TASTEFLOW_API_BASE;

const elements = {
  form: document.getElementById("sales-filter"),
  startDate: document.getElementById("start-date"),
  endDate: document.getElementById("end-date"),
  clearButton: document.getElementById("clear-filters"),
  message: document.getElementById("dashboard-message"),

  totalRevenue: document.getElementById("total-revenue"),
  totalOrders: document.getElementById("total-orders"),
  averageOrderValue: document.getElementById("average-order-value"),
  salesDays: document.getElementById("sales-days"),

  statusPending: document.getElementById("status-pending"),
  statusPreparing: document.getElementById("status-preparing"),
  statusReady: document.getElementById("status-ready"),
  statusCompleted: document.getElementById("status-completed"),

  percentPending: document.getElementById("percent-pending"),
  percentPreparing: document.getElementById("percent-preparing"),
  percentReady: document.getElementById("percent-ready"),
  percentCompleted: document.getElementById("percent-completed"),

  chart: document.getElementById("daily-sales-chart"),
  chartMessage: document.getElementById("chart-message"),

  topDishes: document.getElementById("top-revenue-dishes"),
  topDishesMessage: document.getElementById("top-dishes-message"),

  revenueStatusChart: document.getElementById("revenue-status-chart"),
  revenueStatusMessage: document.getElementById("revenue-status-message"),

  busyPeriodsList: document.getElementById("busy-periods-list"),
  busyPeriodsMessage: document.getElementById("busy-periods-message")
};

const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2
});

const numberFormatter = new Intl.NumberFormat("en-IN");

function formatCurrency(amount) {
  return currencyFormatter.format(Number(amount) || 0);
}

function formatNumber(value) {
  return numberFormatter.format(Number(value) || 0);
}

function getDateParameters() {
  const params = new URLSearchParams();

  if (elements.startDate.value) {
    params.set("start_date", elements.startDate.value);
  }

  if (elements.endDate.value) {
    params.set("end_date", elements.endDate.value);
  }

  const query = params.toString();
  return query ? `?${query}` : "";
}

function fetchJSON(url) {
  // Owner analytics need the owner PIN; the shared client prompts for it.
  return TasteFlowAPI.request(url, {}, "owner");
}

function setLoading(isLoading) {
  elements.form.querySelector('button[type="submit"]').disabled = isLoading;
  elements.clearButton.disabled = isLoading;

  if (isLoading) {
    elements.message.classList.remove("owner-error");
    elements.message.textContent = "Loading restaurant analytics...";
  }
}

function showError(message) {
  elements.message.classList.add("owner-error");
  elements.message.textContent = message;

  elements.totalRevenue.textContent = "—";
  elements.totalOrders.textContent = "—";
  elements.averageOrderValue.textContent = "—";
  elements.salesDays.textContent = "—";

  for (const status of [
    "pending",
    "preparing",
    "ready",
    "completed"
  ]) {
    document.getElementById(`status-${status}`).textContent = "—";
    document.getElementById(`percent-${status}`).textContent = "—";
  }

  elements.chartMessage.textContent = "Chart unavailable.";
  elements.topDishesMessage.textContent = "Dish analytics unavailable.";
  elements.revenueStatusMessage.textContent = "Revenue breakdown unavailable.";
  elements.busyPeriodsMessage.textContent = "Busy-period analytics unavailable.";

  elements.topDishes.replaceChildren();
  elements.revenueStatusChart.replaceChildren();
  elements.busyPeriodsList.replaceChildren();

  const context = elements.chart.getContext("2d");
  context.clearRect(0, 0, elements.chart.width, elements.chart.height);
}

function drawDailySalesChart(dailySales) {
  const canvas = elements.chart;
  const context = canvas.getContext("2d");

  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const pixelRatio = window.devicePixelRatio || 1;

  canvas.width = Math.round(width * pixelRatio);
  canvas.height = Math.round(height * pixelRatio);

  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  if (dailySales.length === 0) {
    elements.chartMessage.textContent =
      "No daily sales data is available for this period.";
    return;
  }

  elements.chartMessage.textContent =
    `Showing revenue across ${dailySales.length} day(s).`;

  const padding = { top: 24, right: 20, bottom: 58, left: 76 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  if (chartWidth <= 0 || chartHeight <= 0) return;

  const values = dailySales.map(item => Number(item.revenue) || 0);
  const maxRevenue = Math.max(...values, 1);
  const axisMax = maxRevenue * 1.1;

  const compactCurrency = value =>
    new Intl.NumberFormat("en-IN", {
      notation: "compact",
      maximumFractionDigits: 1
    }).format(value);

  context.font = "12px sans-serif";
  context.textAlign = "right";
  context.textBaseline = "middle";

  for (let i = 0; i <= 4; i++) {
    const value = axisMax * i / 4;
    const y = padding.top + chartHeight - (value / axisMax) * chartHeight;

    context.beginPath();
    context.strokeStyle = "#e1e8e3";
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();

    context.fillStyle = "#52635a";
    context.fillText(compactCurrency(value), padding.left - 10, y);
  }

  const slotWidth = chartWidth / dailySales.length;
  const barWidth = Math.min(slotWidth * 0.65, 42);

  dailySales.forEach((item, index) => {
    const value = Math.max(0, Number(item.revenue) || 0);
    const barHeight = (value / axisMax) * chartHeight;

    const x = padding.left + index * slotWidth + (slotWidth - barWidth) / 2;
    const y = padding.top + chartHeight - barHeight;

    context.fillStyle = "#28765b";
    context.fillRect(x, y, barWidth, barHeight);

    if (
      dailySales.length <= 14 ||
      index % Math.ceil(dailySales.length / 10) === 0
    ) {
      context.save();
      context.translate(x + barWidth / 2, height - padding.bottom + 12);
      context.rotate(-Math.PI / 4);
      context.fillStyle = "#52635a";
      context.textAlign = "right";
      context.textBaseline = "middle";
      context.fillText(item.date.slice(5), 0, 0);
      context.restore();
    }
  });
}

function renderOrderStatuses(statusData) {
  const statusElements = {
    pending: [elements.statusPending, elements.percentPending],
    preparing: [elements.statusPreparing, elements.percentPreparing],
    ready: [elements.statusReady, elements.percentReady],
    completed: [elements.statusCompleted, elements.percentCompleted]
  };

  const counts = statusData.status_counts || {};
  const percentages = statusData.status_percentages || {};

  for (const [name, [countElement, percentageElement]] of
    Object.entries(statusElements)) {
    countElement.textContent = formatNumber(counts[name] ?? 0);
    percentageElement.textContent =
      `${Number(percentages[name] ?? 0).toFixed(2)}% of orders`;
  }
}

function renderTopRevenueDishes(dishes) {
  elements.topDishes.replaceChildren();

  if (dishes.length === 0) {
    elements.topDishesMessage.textContent =
      "No dish sales found for this period.";
    return;
  }

  elements.topDishesMessage.textContent =
    `Showing ${dishes.length} top dishes by revenue.`;

  const maxRevenue = Math.max(
    ...dishes.map(dish => Number(dish.revenue) || 0),
    1
  );

  dishes.forEach((dish, index) => {
    const row = document.createElement("div");
    row.className = "owner-bar-row";

    const heading = document.createElement("div");
    heading.className = "owner-bar-heading";

    const name = document.createElement("strong");
    name.textContent = `${index + 1}. ${dish.dish_name}`;

    const revenue = document.createElement("span");
    revenue.textContent = formatCurrency(dish.revenue);

    heading.append(name, revenue);

    const track = document.createElement("div");
    track.className = "owner-bar-track";

    const bar = document.createElement("div");
    bar.className = "owner-bar-fill";
    bar.style.width =
      `${Math.max(0, Number(dish.revenue) || 0) / maxRevenue * 100}%`;

    track.appendChild(bar);

    const details = document.createElement("p");
    details.className = "owner-muted";
    details.textContent = `${formatNumber(dish.quantity_sold)} items sold`;

    row.append(heading, track, details);
    elements.topDishes.appendChild(row);
  });
}

function renderRevenueByStatus(data) {
  elements.revenueStatusChart.replaceChildren();

  const breakdown = data.status_breakdown || {};
  const entries = Object.entries(breakdown);

  if (entries.length === 0) {
    elements.revenueStatusMessage.textContent =
      "No order revenue is available for this period.";
    return;
  }

  const totalRevenue = Number(data.total_revenue) || 0;

  elements.revenueStatusMessage.textContent =
    `Total revenue across statuses: ${formatCurrency(totalRevenue)}`;

  entries.sort((a, b) =>
    Number(b[1].revenue) - Number(a[1].revenue)
  );

  const maxRevenue = Math.max(
    ...entries.map(([, values]) => Number(values.revenue) || 0),
    1
  );

  for (const [status, values] of entries) {
    const revenue = Number(values.revenue) || 0;
    const orderCount = Number(values.order_count) || 0;
    const share = totalRevenue > 0 ? revenue / totalRevenue * 100 : 0;

    const row = document.createElement("div");
    row.className = "owner-bar-row";

    const heading = document.createElement("div");
    heading.className = "owner-bar-heading";

    const label = document.createElement("strong");
    label.textContent = status.charAt(0).toUpperCase() + status.slice(1);

    const amount = document.createElement("span");
    amount.textContent = formatCurrency(revenue);

    heading.append(label, amount);

    const track = document.createElement("div");
    track.className = "owner-bar-track";

    const bar = document.createElement("div");
    bar.className = "owner-bar-fill";
    bar.style.width = `${revenue / maxRevenue * 100}%`;

    track.appendChild(bar);

    const details = document.createElement("p");
    details.className = "owner-muted";
    details.textContent =
      `${formatNumber(orderCount)} orders · ${share.toFixed(1)}% of revenue`;

    row.append(heading, track, details);
    elements.revenueStatusChart.appendChild(row);
  }
}

function formatHour(hour) {
  const value = Number(hour);
  const suffix = value < 12 ? "AM" : "PM";
  const hour12 = value % 12 || 12;
  return `${hour12}:00 ${suffix}`;
}

function renderBusyPeriods(data) {
  elements.busyPeriodsList.replaceChildren();

  const periods = data.busy_periods || [];

  if (periods.length === 0) {
    elements.busyPeriodsMessage.textContent =
      "No order activity is available for this period.";
    return;
  }

  elements.busyPeriodsMessage.textContent =
    "Hours are ranked by order count, highest first.";

  const maxCount = Math.max(
    ...periods.map(period => Number(period.order_count) || 0),
    1
  );

  periods.forEach(period => {
    const row = document.createElement("div");
    row.className = "owner-bar-row";

    const heading = document.createElement("div");
    heading.className = "owner-bar-heading";

    const label = document.createElement("strong");
    label.textContent = formatHour(period.hour);

    const count = document.createElement("span");
    count.textContent =
      `${formatNumber(period.order_count)} orders`;

    heading.append(label, count);

    const track = document.createElement("div");
    track.className = "owner-bar-track";

    const bar = document.createElement("div");
    bar.className = "owner-bar-fill";
    bar.style.width =
      `${Math.max(0, Number(period.order_count) || 0) / maxCount * 100}%`;

    track.appendChild(bar);
    row.append(heading, track);
    elements.busyPeriodsList.appendChild(row);
  });
}

async function loadDashboard() {
  const startDate = elements.startDate.value;
  const endDate = elements.endDate.value;

  if (startDate && endDate && startDate > endDate) {
    showError("Start date must be on or before the end date.");
    return;
  }

  setLoading(true);

  try {
    const query = getDateParameters();

    const [
      salesData,
      orderValueData,
      statusData,
      topDishesData,
      revenueStatusData,
      busyPeriodsData
    ] = await Promise.all([
      fetchJSON(`${API_BASE_URL}/api/owner/daily-sales${query}`),
      fetchJSON(`${API_BASE_URL}/api/owner/average-order-value${query}`),
      fetchJSON(`${API_BASE_URL}/api/owner/order-status${query}`),
      fetchJSON(`${API_BASE_URL}/api/owner/top-revenue-dishes${query}`),
      fetchJSON(`${API_BASE_URL}/api/owner/revenue-by-status${query}`),
      fetchJSON(`${API_BASE_URL}/api/owner/busy-periods${query}`)
    ]);

    if (
      !Array.isArray(salesData.daily_sales) ||
      !Number.isFinite(orderValueData.total_revenue) ||
      !Number.isFinite(orderValueData.total_orders) ||
      !Number.isFinite(orderValueData.average_order_value) ||
      !Array.isArray(topDishesData.dishes)
    ) {
      throw new Error("The API returned an unexpected response format.");
    }

    elements.totalRevenue.textContent =
      formatCurrency(orderValueData.total_revenue);

    elements.totalOrders.textContent =
      formatNumber(orderValueData.total_orders);

    elements.averageOrderValue.textContent =
      formatCurrency(orderValueData.average_order_value);

    elements.salesDays.textContent =
      formatNumber(salesData.daily_sales.length);

    renderOrderStatuses(statusData);
    drawDailySalesChart(salesData.daily_sales);
    renderTopRevenueDishes(topDishesData.dishes);
    renderRevenueByStatus(revenueStatusData);
    renderBusyPeriods(busyPeriodsData);

    elements.message.classList.remove("owner-error");
    elements.message.textContent = orderValueData.total_orders === 0
      ? "No eligible orders were found for this period."
      : "Restaurant analytics loaded successfully.";
  } catch (error) {
    console.error("TasteFlow dashboard error:", error);

    showError(
      "Unable to load analytics. Check that the backend is running and try again."
    );
  } finally {
    setLoading(false);
  }
}

elements.form.addEventListener("submit", event => {
  event.preventDefault();
  loadDashboard();
});

elements.clearButton.addEventListener("click", () => {
  elements.startDate.value = "";
  elements.endDate.value = "";
  loadDashboard();
});

window.addEventListener("resize", () => {
  if (window.dashboardResizeTimer) {
    clearTimeout(window.dashboardResizeTimer);
  }

  window.dashboardResizeTimer = setTimeout(loadDashboard, 200);
});

function showError(message) {
  elements.message.classList.add("owner-error");
  elements.message.textContent = message;

  elements.totalRevenue.textContent = "—";
  elements.totalOrders.textContent = "—";
  elements.averageOrderValue.textContent = "—";
  elements.salesDays.textContent = "—";

  for (const status of ["pending", "preparing", "ready", "completed"]) {
    document.getElementById(`status-${status}`).textContent = "—";
    document.getElementById(`percent-${status}`).textContent = "—";
  }

  elements.chartMessage.textContent = "Chart unavailable.";
  elements.topDishesMessage.textContent = "Dish analytics unavailable.";
  elements.revenueStatusMessage.textContent = "Revenue breakdown unavailable.";
  elements.busyPeriodsMessage.textContent = "Busy-period analytics unavailable.";

  elements.topDishes.replaceChildren();
  elements.revenueStatusChart.replaceChildren();
  elements.busyPeriodsList.replaceChildren();

  const context = elements.chart.getContext("2d");
  context.clearRect(0, 0, elements.chart.width, elements.chart.height);
}

loadDashboard();
