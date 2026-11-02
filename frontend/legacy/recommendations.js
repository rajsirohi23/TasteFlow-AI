const RECOMMENDATION_API_URL =
  window.TASTEFLOW_API_BASE + "/api/agents/menu/recommend";

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("recommendation-form");
  const budgetInput = document.getElementById("recommendation-budget");
  const dietInput = document.getElementById("recommendation-diet");
  const categoryInput = document.getElementById("recommendation-category");
  const spiceInput = document.getElementById("recommendation-spice");
  const statusElement = document.getElementById("recommendation-status");
  const resultsElement = document.getElementById("recommendation-results");

  if (
    !form ||
    !budgetInput ||
    !dietInput ||
    !categoryInput ||
    !spiceInput ||
    !statusElement ||
    !resultsElement
  ) {
    console.error("TasteFlow recommendation form elements were not found.");
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const payload = { limit: 5 };

    const budgetText = budgetInput.value.trim();

    if (budgetText !== "") {
      const budget = Number(budgetText);

      if (!Number.isSafeInteger(budget) || budget < 0 || budget > 100000) {
        statusElement.textContent =
          "Enter a whole-number budget between ₹0 and ₹100,000.";
        resultsElement.replaceChildren();
        return;
      }

      payload.budget = budget;
    }

    if (dietInput.value) {
      payload.diet = dietInput.value;
    }

    if (categoryInput.value) {
      payload.category = categoryInput.value;
    }

    if (spiceInput.value) {
      payload.spice_level = spiceInput.value;
    }

    statusElement.textContent = "Finding dishes for you...";
    resultsElement.replaceChildren();

    try {
      const response = await fetch(RECOMMENDATION_API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Recommendation request failed (${response.status}).`);
      }

      const data = await response.json();

      if (!Array.isArray(data.recommendations)) {
        throw new Error("The API returned an unexpected response.");
      }

      if (data.recommendations.length === 0) {
        statusElement.textContent =
          "No dishes match all your selected preferences. Try changing your filters.";
        return;
      }

      statusElement.textContent = `We found ${data.recommendations.length} recommendation(s).`;

      const fragment = document.createDocumentFragment();

      data.recommendations.forEach((dish) => {
        const card = document.createElement("article");
        card.className = "recommendation-card";

        const title = document.createElement("h3");
        title.textContent = dish.name;

        const addButton = document.createElement("button");
        addButton.type = "button";
        addButton.className = "button button-primary";
        addButton.textContent = "Add to Cart";

        addButton.addEventListener("click", () => {
          if (typeof window.addToCart !== "function") {
            statusElement.textContent =
              "Cart integration is not available. Please refresh the page.";
            return;
          }

          window.addToCart(Number(dish.id));
        });

        const price = document.createElement("p");
        price.className = "recommendation-price";
        price.textContent = `₹${dish.price}`;

        const category = document.createElement("p");
        category.textContent = dish.category;

        const description = document.createElement("p");
        description.textContent = dish.description || "";

        const reasonsHeading = document.createElement("strong");
        reasonsHeading.textContent = "Why we recommend it";

        const reasonsList = document.createElement("ul");

        (Array.isArray(dish.reasons) ? dish.reasons : []).forEach((reason) => {
          const reasonItem = document.createElement("li");
          reasonItem.textContent = reason;
          reasonsList.appendChild(reasonItem);
        });

        card.append(
          title,
          price,
          category,
          description,
          reasonsHeading,
          reasonsList,
          addButton,
        );

        fragment.appendChild(card);
      });

      resultsElement.replaceChildren(fragment);
    } catch (error) {
      console.error("TasteFlow recommendations error:", error);

      statusElement.textContent =
        "We couldn't load recommendations. Check that the TasteFlow backend is running and try again.";
    }
  });
});
