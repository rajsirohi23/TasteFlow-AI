(() => {
  "use strict";

  const API_BASE = window.TASTEFLOW_API_BASE;

  const openButton = document.getElementById("voice-open");
  const closeButton = document.getElementById("voice-close");
  const muteButton = document.getElementById("voice-mute");
  const endButton = document.getElementById("voice-end");
  const modal = document.getElementById("voice-modal");
  const statusText = document.getElementById("voice-status");
  const transcript = document.getElementById("voice-transcript");
  const orb = document.getElementById("voice-orb");

  if (!openButton || !modal || !statusText || !transcript || !orb) {
    console.error("TasteFlow voice interface elements are missing.");
    return;
  }

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  let recognition = null;
  let listening = false;
  let muted = false;
  let speaking = false;
  let busy = false;
  let conversationId = 0;
  let pendingCartItem = null;

  // --------------------------------------------------
  // UI HELPERS
  // --------------------------------------------------

  function setStatus(message, state = "") {
    statusText.textContent = message;
    orb.dataset.state = state;
  }

  function showModal() {
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
  }

  function hideModal() {
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
  }

  function addMessage(speaker, message) {
    const entry = document.createElement("p");
    entry.className = "voice-transcript-entry";

    const label = document.createElement("strong");
    label.textContent = `${speaker}: `;

    const text = document.createElement("span");
    text.textContent = message;

    entry.append(label, text);
    transcript.appendChild(entry);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function stopRecognition() {
    if (!recognition) {
      listening = false;
      return;
    }

    const current = recognition;
    recognition = null;
    listening = false;

    try {
      current.stop();
    } catch {
      // Recognition may already have stopped.
    }
  }

  // --------------------------------------------------
  // SPEECH
  // --------------------------------------------------

  function speak(message, id = conversationId) {
    if (!("speechSynthesis" in window)) {
      setStatus("Reply displayed. Speech playback is unavailable.", "error");
      return;
    }

    window.speechSynthesis.cancel();
    speaking = true;

    const utterance = new SpeechSynthesisUtterance(message);
    utterance.lang = "en-IN";
    utterance.rate = 1;
    utterance.pitch = 1;

    utterance.onstart = () => {
      if (id !== conversationId) return;
      setStatus("TasteFlow AI is speaking…", "speaking");
    };

    utterance.onend = () => {
      if (id !== conversationId) return;

      speaking = false;

      // Wait for the assistant's confirmation prompt to finish.
      if (pendingCartItem && !muted && !busy) {
        setStatus("Listening for your yes or no…", "listening");

        // Give the browser time to finish the speech output.
        window.setTimeout(() => {
          if (
            id === conversationId &&
            pendingCartItem &&
            !muted &&
            !busy &&
            !listening
          ) {
            startListening();
          }
        }, 700);

        return;
      }

      setStatus("Ready — ask another question", "");
    };

    utterance.onerror = () => {
      if (id !== conversationId) return;

      speaking = false;
      setStatus("Reply displayed. Speech playback stopped.", "");
    };

    window.speechSynthesis.speak(utterance);
  }

  function stopVoice() {
    conversationId++;
    stopRecognition();

    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }

    speaking = false;
    busy = false;
    muted = false;
    pendingCartItem = null;

    if (muteButton) {
      muteButton.disabled = true;
      muteButton.textContent = "Mute microphone";
      muteButton.setAttribute("aria-pressed", "false");
    }

    if (endButton) {
      endButton.disabled = true;
    }

    setStatus("Disconnected", "");
  }

  // --------------------------------------------------
  // MENU HELPERS
  // --------------------------------------------------

  async function getMenu() {
    const response = await fetch(`${API_BASE}/api/menu`);

    if (!response.ok) {
      throw new Error(`Could not load menu. HTTP status: ${response.status}`);
    }

    const result = await response.json();

    const items = Array.isArray(result)
      ? result
      : result.items || result.menu || [];

    if (!Array.isArray(items)) {
      throw new Error("The menu API returned an unexpected response.");
    }

    return items;
  }

  function getName(item) {
    return item.name || item.item_name || item.title || "Menu item";
  }

  function getPrice(item) {
    const price = Number(item.price);

    return Number.isFinite(price) ? `₹${price}` : "price unavailable";
  }

  function isAvailable(item) {
    if (
      item.is_available === false ||
      item.available === false ||
      item.is_available === 0 ||
      item.available === 0
    ) {
      return false;
    }

    if (String(item.status || "").toLowerCase() === "unavailable") {
      return false;
    }

    return true;
  }

  // --------------------------------------------------
  // CONFIRMATION DETECTION
  // --------------------------------------------------

  function normalizeText(message) {
    return String(message || "")
      .toLowerCase()
      .replace(/[’‘]/g, "'")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/[.!?,]+$/g, "");
  }

  function isYesConfirmation(message) {
    const text = normalizeText(message);

    // Accept "yes", "yes please", "yes add it to my cart",
    // "yeah go ahead", "yep please do", etc.
    const startsWithYes =
      /^(yes|yeah|yep|yup|sure|certainly|absolutely|okay|ok|of course|go ahead|please do)\b/.test(
        text,
      );

    if (!startsWithYes) return false;

    // Avoid treating "yes, but don't add it" as approval.
    if (
      /\b(no|don't|dont|do not|cancel|not now|never mind|nevermind)\b/.test(
        text,
      )
    ) {
      return false;
    }

    return true;
  }

  function isNoConfirmation(message) {
    const text = normalizeText(message);

    return /^(no|nope|nah|no thanks|no thank you|cancel|don't|dont|do not|not now|never mind|nevermind)\b/.test(
      text,
    );
  }

  // --------------------------------------------------
  // CART INTEGRATION
  // --------------------------------------------------

  async function addItemToCart(item) {
    const itemName = getName(item);
    const itemId = item.id ?? item.menu_item_id ?? item.item_id;

    console.log("TasteFlow: attempting to add item to cart", {
      item,
      itemName,
      itemId,
    });

    // Try common globally exposed cart functions.
    // Your customer-menu JavaScript may expose one of these.
    const attempts = [];

    if (typeof window.addToCartByName === "function") {
      attempts.push({
        name: "window.addToCartByName",
        run: () => window.addToCartByName(itemName),
      });
    }

    if (typeof window.addItemToCart === "function") {
      attempts.push({
        name: "window.addItemToCart",
        run: () => window.addItemToCart(item),
      });
    }

    if (typeof window.addToCartItem === "function") {
      attempts.push({
        name: "window.addToCartItem",
        run: () => window.addToCartItem(item),
      });
    }

    if (
      typeof window.addToCart === "function" &&
      itemId !== undefined &&
      itemId !== null &&
      itemId !== ""
    ) {
      attempts.push({
        name: "window.addToCart",
        run: () => window.addToCart(Number(itemId)),
      });
    }

    if (window.cart && typeof window.cart.addItem === "function") {
      attempts.push({
        name: "window.cart.addItem",
        run: () => window.cart.addItem(item),
      });
    }

    for (const attempt of attempts) {
      try {
        const result = await attempt.run();

        // A cart function may explicitly report failure.
        if (result === false) {
          console.warn(`TasteFlow: ${attempt.name} returned false.`);
          continue;
        }

        console.log(
          `TasteFlow: cart function invoked: ${attempt.name}`,
          result,
        );

        return {
          success: true,
          method: attempt.name,
        };
      } catch (error) {
        console.error(`TasteFlow: ${attempt.name} failed:`, error);
      }
    }

    // Fallback: find the dish's rendered menu card and click its
    // Add to Cart button. This depends on your actual menu HTML.
    const cardSelectors = [
      "[data-menu-item-id]",
      ".menu-item",
      ".menu-card",
      ".food-card",
      ".dish-card",
      ".product-card",
      ".menu-card-item",
    ];

    const cards = [
      ...new Set(
        cardSelectors.flatMap((selector) =>
          Array.from(document.querySelectorAll(selector)),
        ),
      ),
    ];

    const normalizedName = normalizeText(itemName);

    const matchingCard = cards.find((card) => {
      const cardId =
        card.dataset.menuItemId || card.dataset.itemId || card.dataset.id;

      if (
        itemId !== undefined &&
        itemId !== null &&
        String(cardId) === String(itemId)
      ) {
        return true;
      }

      return normalizeText(card.innerText || "").includes(normalizedName);
    });

    if (matchingCard) {
      const buttons = Array.from(
        matchingCard.querySelectorAll("button, [role='button']"),
      );

      const addButton = buttons.find((button) =>
        /\b(add to cart|add to basket|add item|add)\b/i.test(
          button.innerText || button.getAttribute("aria-label") || "",
        ),
      );

      if (addButton && !addButton.disabled) {
        addButton.click();

        console.log("TasteFlow: clicked the menu card's Add to Cart button.");

        return {
          success: true,
          method: "menu-card-button",
        };
      }
    }

    console.error(
      "TasteFlow: no compatible cart function or menu-card button was found.",
      {
        item,
        availableFunctions: {
          addToCartByName: typeof window.addToCartByName,
          addItemToCart: typeof window.addItemToCart,
          addToCartItem: typeof window.addToCartItem,
          addToCart: typeof window.addToCart,
          cartAddItem: typeof window.cart?.addItem,
        },
      },
    );

    return {
      success: false,
      method: null,
    };
  }

  // --------------------------------------------------
  // GENERAL MENU QUESTIONS
  // --------------------------------------------------

  function answerFromMenu(message, items) {
    const text = normalizeText(message);
    const available = items.filter(isAvailable);

    if (!items.length) {
      return "I couldn't find any menu items right now. Please try again later.";
    }

    if (
      /\b(hello|hi|hey|good morning|good afternoon|good evening)\b/.test(text)
    ) {
      return "Hello! Welcome to TasteFlow. You can ask me about our menu, prices, or vegetarian dishes. What would you like to explore?";
    }

    if (/\b(vegetarian|veg|plant based|plant-based)\b/.test(text)) {
      const vegItems = available.filter((item) => {
        const tags = Array.isArray(item.dietary_tags)
          ? item.dietary_tags.map((tag) => String(tag).toLowerCase())
          : [];

        const category = String(item.category || "").toLowerCase();
        const name = getName(item).toLowerCase();

        return (
          tags.includes("vegetarian") ||
          tags.includes("vegan") ||
          category.includes("vegetarian") ||
          item.is_vegetarian === true ||
          item.is_vegetarian === 1 ||
          item.vegetarian === true ||
          item.vegetarian === 1 ||
          name.includes("paneer") ||
          name.includes("veg ")
        );
      });

      if (vegItems.length) {
        return (
          "Here are some options to explore: " +
          vegItems
            .slice(0, 4)
            .map((item) => `${getName(item)}, ${getPrice(item)}`)
            .join("; ") +
          ". Please confirm ingredients with the restaurant if you have dietary restrictions."
        );
      }

      return "I couldn't reliably identify vegetarian dishes from the menu data. Please check the menu descriptions or ask the restaurant.";
    }

    if (/\b(cheap|cheapest|budget|affordable|under \d+)\b/.test(text)) {
      const match = text.match(
        /\b(?:under|below|less than)\s*(?:₹|rs\.?\s*)?(\d+)\b/,
      );

      const limit = match ? Number(match[1]) : Infinity;

      const budgetItems = available
        .filter((item) => Number.isFinite(Number(item.price)))
        .filter((item) => Number(item.price) <= limit)
        .sort((a, b) => Number(a.price) - Number(b.price))
        .slice(0, 4);

      if (budgetItems.length) {
        return (
          "Here are some budget-friendly options: " +
          budgetItems
            .map((item) => `${getName(item)}, ${getPrice(item)}`)
            .join("; ") +
          "."
        );
      }

      return "I couldn't find a priced item matching that budget. You can browse the menu for more options.";
    }

    if (/\b(menu|dishes|options|what do you have|show me food)\b/.test(text)) {
      if (!available.length) {
        return "There are no available dishes on the menu right now.";
      }

      return (
        "Here are some available menu items: " +
        available
          .slice(0, 6)
          .map((item) => `${getName(item)}, ${getPrice(item)}`)
          .join("; ") +
        ". Ask me about a specific dish or your budget."
      );
    }

    const matched = available.filter((item) => {
      const searchable = [
        getName(item),
        item.category || "",
        item.description || "",
      ]
        .join(" ")
        .toLowerCase();

      return text.split(/\s+/).some((word) => {
        return word.length > 3 && searchable.includes(word);
      });
    });

    if (matched.length) {
      return matched
        .slice(0, 3)
        .map(
          (item) =>
            `${getName(item)}, ${getPrice(item)}. ${item.description || ""}`,
        )
        .join(" ");
    }

    if (/\b(thank you|thanks)\b/.test(text)) {
      return "You're welcome! Let me know if you'd like to explore the menu.";
    }

    return "I can help you explore the menu, find dishes by name, and look for budget-friendly options. What would you like to eat?";
  }

  // --------------------------------------------------
  // VOICE MESSAGE HANDLER
  // --------------------------------------------------

  async function handleMessage(message) {
    const id = conversationId;
    const text = String(message || "").trim();
    const normalized = normalizeText(text);

    if (!text || busy) return;

    addMessage("You", text);
    stopRecognition();

    busy = true;
    setStatus("Processing your request…", "thinking");

    try {
      // IMPORTANT: Handle confirmation BEFORE fetching the menu.
      // This means a temporary menu API failure won't block "yes".
      if (pendingCartItem && isYesConfirmation(normalized)) {
        console.log("VOICE CONFIRMATION:", {
          message: text,
          normalized,
          pendingCartItem,
          yesDetected: isYesConfirmation(normalized),
        });
        const item = pendingCartItem;

        setStatus(`Adding ${getName(item)} to your cart…`, "thinking");

        const result = await addItemToCart(item);
        console.log("VOICE CART RESULT:", result);
        if (id !== conversationId) return;

        if (result.success) {
          pendingCartItem = null;

          const reply =
            `${getName(item)} has been sent to the cart using ` +
            `${result.method}. Please check your cart to confirm the item and quantity.`;

          addMessage("TasteFlow AI", reply);
          speak(reply, id);
        } else {
          // Keep the pending item so the user can retry.
          const reply =
            `I heard your confirmation, but I couldn't connect to the cart ` +
            `for ${getName(item)}. Your item has not been confirmed as added. ` +
            "Please check the browser console or use the menu's Add to Cart button.";

          addMessage("TasteFlow AI", reply);
          speak(reply, id);
        }

        return;
      }

      // Handle "no", "no thanks", "cancel", etc.
      if (pendingCartItem && isNoConfirmation(normalized)) {
        pendingCartItem = null;

        const reply = "No problem. I haven't added anything to your cart.";

        addMessage("TasteFlow AI", reply);
        speak(reply, id);
        return;
      }

      // Cancel a pending action.
      if (
        pendingCartItem &&
        /\b(cancel|never mind|nevermind)\b/.test(normalized)
      ) {
        pendingCartItem = null;

        const reply = "Cancelled. Nothing was added to your cart.";

        addMessage("TasteFlow AI", reply);
        speak(reply, id);
        return;
      }

      const items = await getMenu();

      if (id !== conversationId) return;

      // If an item is awaiting confirmation, don't replace it with
      // an unrelated request.
      if (pendingCartItem) {
        const reply =
          `I'm still waiting for your confirmation to add ` +
          `${getName(pendingCartItem)} to your cart. ` +
          "Please say yes to add it or no to cancel.";

        addMessage("TasteFlow AI", reply);
        speak(reply, id);
        return;
      }

      // ------------------------------------------------
      // ADD-TO-CART REQUEST
      // Examples:
      // "Add paneer tikka to my cart"
      // "Please put pizza in the cart"
      // "Add this dish to my order"
      // ------------------------------------------------

      const wantsCart =
        /\b(add|put|include|order)\b/.test(normalized) &&
        /\b(cart|basket|order)\b/.test(normalized);

      if (wantsCart) {
        const available = items.filter(isAvailable);

        const requestedName = normalized
          .replace(
            /\b(please|can you|could you|add|put|include|order|to|into|my|the|cart|basket|for me|in|this|that|item|dish|food)\b/g,
            " ",
          )
          .replace(/[.,!?]/g, " ")
          .replace(/\s+/g, " ")
          .trim();

        // Match longest dish names first.
        const matches = available
          .map((dish) => ({
            dish,
            name: normalizeText(getName(dish)),
          }))
          .filter(({ name }) => {
            if (!requestedName) return false;

            return requestedName.includes(name) || name.includes(requestedName);
          })
          .sort((a, b) => b.name.length - a.name.length);

        const item = matches[0]?.dish;

        if (!item) {
          const reply =
            "I couldn't identify that dish in the available menu. " +
            "Please say its exact name, for example: add paneer tikka to my cart.";

          addMessage("TasteFlow AI", reply);
          speak(reply, id);
          return;
        }

        // Ask for confirmation before modifying the cart.
        pendingCartItem = item;

        const reply =
          `I found ${getName(item)} for ${getPrice(item)}. ` +
          "Would you like me to add it to your cart? Please say yes or no.";

        addMessage("TasteFlow AI", reply);
        speak(reply, id);
        return;
      }

      // ------------------------------------------------
      // RECOMMENDATION REQUESTS
      // ------------------------------------------------

      const wantsRecommendation =
        /\b(recommend|recommendation|suggest|suggestion|best for me|what should i eat|what can i eat|find me|looking for)\b/.test(
          normalized,
        );

      if (wantsRecommendation) {
        const payload = { limit: 5 };

        const budgetMatch = normalized.match(
          /\b(?:under|below|within|budget of|less than)\s*(?:₹|rs\.?\s*)?(\d+)\b/,
        );

        if (budgetMatch) {
          payload.budget = Number(budgetMatch[1]);
        }

        if (
          /\b(non[- ]?veg|non[- ]?vegetarian|chicken|mutton|fish)\b/.test(
            normalized,
          )
        ) {
          payload.diet = "non-vegetarian";
        } else if (/\bvegan\b/.test(normalized)) {
          payload.diet = "vegan";
        } else if (/\b(vegetarian|veg food|veg dishes)\b/.test(normalized)) {
          payload.diet = "vegetarian";
        }

        if (/\b(spicy|hot food|high spice|very spicy)\b/.test(normalized)) {
          payload.spice_level = "high";
        } else if (
          /\b(mild|less spicy|not spicy|low spice)\b/.test(normalized)
        ) {
          payload.spice_level = "low";
        }

        const response = await fetch(`${API_BASE}/api/agents/menu/recommend`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        });

        let data = {};

        try {
          data = await response.json();
        } catch {
          // The server may return an empty or non-JSON response.
        }

        if (!response.ok) {
          throw new Error(data.detail || "The recommendation service failed.");
        }

        if (id !== conversationId) return;

        const recommendations = Array.isArray(data.recommendations)
          ? data.recommendations
          : [];

        if (!recommendations.length) {
          const reply =
            "I couldn't find dishes matching those preferences. " +
            "Try a different budget or dietary preference.";

          addMessage("TasteFlow AI", reply);
          speak(reply, id);
          return;
        }

        const reply =
          "Here are my recommendations: " +
          recommendations
            .slice(0, 3)
            .map((dish) => {
              const reasons =
                Array.isArray(dish.reasons) && dish.reasons.length
                  ? ` ${dish.reasons[0]}.`
                  : "";

              return `${getName(dish)}, ${getPrice(dish)}.${reasons}`;
            })
            .join(" ") +
          " You can ask me to add a dish to your cart.";

        addMessage("TasteFlow AI", reply);
        speak(reply, id);
        return;
      }

      // ------------------------------------------------
      // GENERAL MENU QUESTIONS
      // ------------------------------------------------

      const reply = answerFromMenu(text, items);

      if (id !== conversationId) return;

      addMessage("TasteFlow AI", reply);
      speak(reply, id);
    } catch (error) {
      if (id !== conversationId) return;

      console.error("TasteFlow voice assistant error:", error);

      const reply =
        `Sorry, I couldn't complete that request. ${error.message || ""} ` +
        "Please check the backend and try again.";

      addMessage("TasteFlow AI", reply);
      speak(reply, id);
    } finally {
      if (id === conversationId) {
        busy = false;
      }
    }
  }

  // --------------------------------------------------
  // START VOICE RECOGNITION
  // --------------------------------------------------

  function startListening() {
    if (!SpeechRecognition) {
      setStatus(
        "Speech recognition is not supported in this browser. Try Chrome.",
        "error",
      );
      return;
    }

    if (busy || listening || muted || speaking) return;

    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }

    const current = new SpeechRecognition();

    recognition = current;
    current.lang = "en-IN";
    current.continuous = false;
    current.interimResults = false;
    current.maxAlternatives = 1;

    current.onstart = () => {
      listening = true;
      setStatus("Listening — speak now", "listening");

      if (endButton) endButton.disabled = false;
      if (muteButton) muteButton.disabled = false;
    };

    current.onresult = (event) => {
      const result = event.results[event.results.length - 1];
      const message = result?.[0]?.transcript?.trim();

      if (message) {
        console.log("TasteFlow recognized speech:", message);
        handleMessage(message);
      }
    };

    current.onerror = (event) => {
      listening = false;

      if (recognition === current) {
        recognition = null;
      }

      if (
        event.error === "not-allowed" ||
        event.error === "service-not-allowed"
      ) {
        setStatus(
          "Microphone permission denied. Allow microphone access in your browser settings.",
          "error",
        );
      } else if (event.error === "no-speech") {
        setStatus(
          pendingCartItem
            ? "I didn't hear your confirmation. Click the voice button and say yes or no."
            : "No speech detected. Click the voice button to try again.",
          "",
        );
      } else if (event.error !== "aborted") {
        setStatus(`Speech recognition error: ${event.error}`, "error");
      }
    };

    current.onend = () => {
      listening = false;

      if (recognition === current) {
        recognition = null;
      }

      // If a confirmation is pending, the speech utterance's onend
      // will start listening again. Don't overwrite that status.
      if (!busy && !speaking && !muted && !pendingCartItem) {
        setStatus("Ready — click the voice button to speak again", "");
      }
    };

    try {
      current.start();
    } catch (error) {
      console.error("Could not start speech recognition:", error);
      setStatus("Could not start the microphone. Please try again.", "error");
    }
  }

  // --------------------------------------------------
  // BUTTON EVENT LISTENERS
  // --------------------------------------------------

  openButton.addEventListener("click", () => {
    showModal();

    if (!busy && !listening && !speaking) {
      startListening();
    }
  });

  if (closeButton) {
    closeButton.addEventListener("click", () => {
      stopVoice();
      hideModal();
    });
  }

  if (endButton) {
    endButton.addEventListener("click", () => {
      stopVoice();
    });
  }

  if (muteButton) {
    muteButton.addEventListener("click", () => {
      muted = !muted;

      if (muted) {
        stopRecognition();

        if ("speechSynthesis" in window) {
          window.speechSynthesis.cancel();
        }

        speaking = false;
        setStatus("Microphone paused", "");
        muteButton.textContent = "Resume microphone";
      } else {
        muteButton.textContent = "Mute microphone";
        startListening();
      }

      muteButton.setAttribute("aria-pressed", String(muted));
    });
  }

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      stopVoice();
      hideModal();
    }
  });

  window.addEventListener("beforeunload", stopVoice);

  setStatus("Ready when you are", "");
})();
