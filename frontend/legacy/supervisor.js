"use strict";

const SUPERVISOR_API_URL =
  window.TASTEFLOW_API_BASE + "/api/agents/supervisor/execute";

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("supervisor-form");
  const messageInput = document.getElementById("supervisor-message");
  const statusElement = document.getElementById("supervisor-status");
  const resultElement = document.getElementById("supervisor-result");

  if (!form || !messageInput || !statusElement || !resultElement) {
    console.error("TasteFlow Supervisor elements were not found.");
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const message = messageInput.value.trim();

    if (!message) {
      statusElement.textContent = "Please enter a message.";
      resultElement.replaceChildren();
      return;
    }

    statusElement.textContent =
      "Supervisor is processing your request...";
    resultElement.replaceChildren();

    try {
      const response = await fetch(SUPERVISOR_API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message }),
      });

      let data;

      try {
        data = await response.json();
      } catch {
        throw new Error("The backend returned an invalid response.");
      }

      if (!response.ok) {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : `Request failed (${response.status}).`;

        throw new Error(detail);
      }

      const fragment = document.createDocumentFragment();

      const heading = document.createElement("h3");
      heading.textContent = "TasteFlow Supervisor";

      const agent = document.createElement("p");
      agent.textContent =
        `Selected agent: ${data.selected_agent || "Unknown"}`;

      const intent = document.createElement("p");
      intent.textContent =
        `Detected intent: ${data.intent || "Unknown"}`;

      fragment.append(heading, agent, intent);

      const result = data.result;

      // --------------------------------------------------
      // MENU AGENT: Display dish recommendations.
      // --------------------------------------------------
      if (
        data.selected_agent === "menu" &&
        result &&
        Array.isArray(result.recommendations)
      ) {
        const recommendations = result.recommendations;

        const summary = document.createElement("p");
        summary.textContent = recommendations.length
          ? `Found ${recommendations.length} recommended dish(es).`
          : "No dishes match those preferences. Try another request.";

        fragment.appendChild(summary);

        recommendations.forEach((dish) => {
          const card = document.createElement("article");
          card.className = "recommendation-card";

          const title = document.createElement("h3");
          title.textContent = dish.name || "Unnamed dish";

          const price = document.createElement("p");
          price.className = "recommendation-price";

          const numericPrice = Number(dish.price);
          price.textContent = Number.isFinite(numericPrice)
            ? `₹${numericPrice.toLocaleString("en-IN")}`
            : "Price unavailable";

          const category = document.createElement("p");
          category.textContent = dish.category || "Uncategorized";

          const description = document.createElement("p");
          description.textContent = dish.description || "";

          const reasonsHeading = document.createElement("strong");
          reasonsHeading.textContent = "Why we recommend it";

          const reasonsList = document.createElement("ul");

          (
            Array.isArray(dish.reasons) ? dish.reasons : []
          ).forEach((reason) => {
            const item = document.createElement("li");
            item.textContent = String(reason);
            reasonsList.appendChild(item);
          });

          const addButton = document.createElement("button");
          addButton.type = "button";
          addButton.className = "button button-primary";
          addButton.textContent = "Add to Cart";

          addButton.addEventListener("click", () => {
            if (typeof window.addToCart !== "function") {
              statusElement.textContent =
                "Cart integration is unavailable. Please refresh the page.";
              return;
            }

            const dishId = Number(dish.id);

            if (!Number.isFinite(dishId)) {
              statusElement.textContent =
                "This dish cannot be added to the cart because its ID is invalid.";
              return;
            }

            window.addToCart(dishId);
          });

          card.append(
            title,
            price,
            category,
            description,
            reasonsHeading,
            reasonsList,
            addButton
          );

          fragment.appendChild(card);
        });

      // --------------------------------------------------
      // ORDER AGENT: Guide the customer to the menu.
      // --------------------------------------------------
      } else if (
        data.selected_agent === "order" &&
        result
      ) {
        const messageElement = document.createElement("p");
        messageElement.textContent =
          result.message ||
          "Select dishes from the menu to start your order.";

        fragment.appendChild(messageElement);

        const menuButton = document.createElement("button");
        menuButton.type = "button";
        menuButton.className = "button button-primary";
        menuButton.textContent = "Go to Menu";

        menuButton.addEventListener("click", () => {
          document.getElementById("menu")?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        });

        fragment.appendChild(menuButton);

      // --------------------------------------------------
      // ANALYTICS AGENT: Display restaurant analytics.
      // --------------------------------------------------
      } else if (
        data.selected_agent === "analytics" &&
        result &&
        result.report_type
      ) {
        const reportType = result.report_type;
        const analytics = result.data;

        const reportHeading = document.createElement("h3");

        const reportTitles = {
          sales_summary: "Restaurant Sales Summary",
          popular_dishes: "Popular Dishes",
          low_demand_dishes: "Low-Demand Dishes",
          daily_sales: "Daily Sales",
          top_revenue_dishes: "Top Revenue Dishes",
        };

        reportHeading.textContent =
          reportTitles[reportType] || "Restaurant Analytics";

        fragment.appendChild(reportHeading);

        // Add a label/value metric.
        const addMetric = (label, value) => {
          const paragraph = document.createElement("p");
          paragraph.textContent = `${label}: ${value ?? "N/A"}`;
          fragment.appendChild(paragraph);
        };

        // Format values as Indian Rupees.
        const formatCurrency = (value) => {
          const amount = Number(value || 0);

          return `₹${amount.toLocaleString("en-IN", {
            maximumFractionDigits: 2,
          })}`;
        };

        // SALES SUMMARY
        if (reportType === "sales_summary") {
          const summary = analytics || {};

          addMetric("Total orders", summary.total_orders);
          addMetric("Active orders", summary.active_orders);
          addMetric("Completed orders", summary.completed_orders);
          addMetric("Cancelled orders", summary.cancelled_orders);

          addMetric(
            "Recorded order value (excluding cancelled orders)",
            formatCurrency(summary.non_cancelled_order_value)
          );

          addMetric(
            "Completed order value",
            formatCurrency(summary.completed_order_value)
          );

          addMetric(
            "Average completed order value",
            formatCurrency(summary.average_completed_order_value)
          );

          if (summary.revenue_note) {
            addMetric("Note", summary.revenue_note);
          } else {
            addMetric(
              "Note",
              "These are recorded order values, not verified payment revenue."
            );
          }

        // POPULAR DISHES OR TOP REVENUE DISHES
        } else if (
          reportType === "popular_dishes" ||
          reportType === "top_revenue_dishes"
        ) {
          const dishes = Array.isArray(analytics)
            ? analytics
            : Array.isArray(analytics?.dishes)
              ? analytics.dishes
              : [];

          if (dishes.length === 0) {
            addMetric("Results", "No dish data available yet.");
          } else {
            const list = document.createElement("ol");

            dishes.forEach((dish) => {
              const item = document.createElement("li");

              if (reportType === "popular_dishes") {
                item.textContent =
                  `${dish.name || "Unnamed dish"}: ` +
                  `${Number(dish.quantity_ordered) || 0} ordered`;
              } else {
                item.textContent =
                  `${dish.dish_name || dish.name || "Unnamed dish"}: ` +
                  `${Number(dish.quantity_sold) || 0} sold, ` +
                  `${formatCurrency(dish.revenue)} recorded value`;
              }

              list.appendChild(item);
            });

            fragment.appendChild(list);
          }

        // LOW-DEMAND DISHES
        } else if (reportType === "low_demand_dishes") {
          const lowDemandData = analytics || {};

          addMetric("Demand threshold", lowDemandData.threshold);

          const dishes = Array.isArray(lowDemandData.dishes)
            ? lowDemandData.dishes
            : [];

          if (dishes.length === 0) {
            addMetric("Results", "No low-demand dishes found.");
          } else {
            const list = document.createElement("ul");

            dishes.forEach((dish) => {
              const item = document.createElement("li");

              item.textContent =
                `${dish.name || "Unnamed dish"}: ` +
                `${Number(dish.quantity_ordered) || 0} ordered ` +
                `(${dish.demand_label || "Low demand"})`;

              list.appendChild(item);
            });

            fragment.appendChild(list);
          }

        // DAILY SALES
        } else if (reportType === "daily_sales") {
          const dailyData = analytics || {};

          addMetric(
            "Date range",
            `${dailyData.start_date || "N/A"} to ${dailyData.end_date || "N/A"}`
          );

          const dailySales = Array.isArray(dailyData.daily_sales)
            ? dailyData.daily_sales
            : [];

          if (dailySales.length === 0) {
            addMetric("Results", "No sales recorded for this date range.");
          } else {
            const list = document.createElement("ul");

            dailySales.forEach((day) => {
              const item = document.createElement("li");

              item.textContent =
                `${day.date || "Unknown date"}: ` +
                `${Number(day.order_count) || 0} orders, ` +
                `${formatCurrency(day.revenue)}`;

              list.appendChild(item);
            });

            fragment.appendChild(list);
          }

        } else {
          addMetric("Status", "Analytics data was received.");
        }

      // --------------------------------------------------
      // OTHER AGENTS: Display a general response.
      // --------------------------------------------------
      } else {
        const messageElement = document.createElement("p");

        messageElement.textContent =
          result?.message || "Your request has been processed.";

        fragment.appendChild(messageElement);
      }

      resultElement.replaceChildren(fragment);

      statusElement.textContent =
        "Request processed successfully.";

    } catch (error) {
      console.error("TasteFlow Supervisor error:", error);

      statusElement.textContent =
        error.message ||
        "Unable to process your request. Check that the backend is running and try again.";
    }
  });
});