"use strict";
/* Agent Console: chat + live view of the multi-agent orchestration.
   All server text is inserted with textContent (never innerHTML), so dish names
   or customer messages cannot inject markup. */
(() => {
  const SESSION_KEY = "tasteflow.chat.session";
  const $ = (id) => document.getElementById(id);
  const els = {
    messages: $("messages"), form: $("chat-form"), input: $("chat-input"), send: $("send-btn"),
    quick: $("quick-replies"), chips: $("chips"), lanes: $("agent-lanes"), trace: $("trace"),
    traceEmpty: $("trace-empty"), summary: $("run-summary"), prefs: $("prefs"), cart: $("cart"),
    kitchen: $("kitchen"), staffBtn: $("staff-btn"), staffPanel: $("staff-panel"),
    insights: $("insights"), unmet: $("unmet"), runs: $("runs"), reset: $("reset-btn"),
    ops: $("ops"), fb: $("fb"), inv: $("inv"),
  };
  const EXAMPLES = [
    "I need a vegetarian high-protein meal under ₹300, something not too spicy",
    "Show me vegan desserts",
    "mujhe kuch veg khana hai 250 ke andar",
    "Dine in table 4",
    "Note: extra crispy please",
    "How busy is the kitchen?",
    "How long will my order take?",
    "Order the same again",
    "Place my order",
  ];
  const FALLBACK_AGENTS = [
    { id: "supervisor", label: "Supervisor Agent", role: "Understands and routes" },
    { id: "menu", label: "Smart Menu & Nutrition", role: "Searches the real menu" },
    { id: "order", label: "Intelligent Order", role: "Cart and confirmation" },
    { id: "kitchen", label: "Kitchen Coordination", role: "Workload and ETA" },
    { id: "intelligence", label: "Restaurant Intelligence", role: "Demand and insights" },
    { id: "tracking", label: "Order Tracking", role: "Minutes left from real timestamps" },
    { id: "feedback", label: "Feedback & Recovery", role: "Ratings and follow-ups" },
    { id: "inventory", label: "Inventory", role: "Stock levels (staff)" },
  ];

  const customerMode = document.body.classList.contains("customer-mode");  // assistant.html: no internals, no staff data
  let sessionId = sessionStorage.getItem(SESSION_KEY) || null;
  let busy = false;
  let replayTimers = [];
  const laneEls = {};

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");
  const scrollDown = () => { els.messages.scrollTop = els.messages.scrollHeight; };
  const ownerHeaders = () => {
    const t = TasteFlowAPI.getToken("owner");
    return t ? { Authorization: `Bearer ${t}` } : {};
  };

  // ---------------------------------------------------------------- lanes
  function buildLanes(agents) {
    els.lanes.replaceChildren();
    agents.forEach((a) => {
      const lane = el("div", "lane");
      lane.append(el("h4", "", a.label), el("p", "", a.role));
      const last = el("div", "last", "idle");
      lane.append(last);
      lane.dataset.agent = a.id;
      laneEls[a.id] = { lane, last };
      els.lanes.append(lane);
    });
  }
  async function loadRegistry() {
    try {
      const data = await TasteFlowAPI.request("/api/agents/registry");
      buildLanes(data.agents);
    } catch { buildLanes(FALLBACK_AGENTS); }
  }
  function resetLanes() {
    Object.values(laneEls).forEach(({ lane, last }) => { lane.className = "lane"; last.textContent = "idle"; });
  }

  // ---------------------------------------------------------------- trace
  function stepNode(step) {
    const li = el("li", "step" + (step.ok ? "" : " fail"));
    const head = el("div", "step-head");
    head.append(el("span", `badge b-${step.agent}`, step.agent), el("span", "action", step.action),
      el("span", "ms", `${step.duration_ms} ms`));
    const details = el("details");
    details.append(el("summary", "", "input → output"));
    details.append(el("pre", "", JSON.stringify({ input: step.input, output: step.output }, null, 2)));
    li.append(head, details);
    return li;
  }
  function showTrace(steps, summaryText) {
    replayTimers.forEach(clearTimeout);
    replayTimers = [];
    els.trace.replaceChildren();
    resetLanes();
    els.traceEmpty.hidden = steps.length > 0;
    els.summary.hidden = !summaryText;
    els.summary.textContent = summaryText || "";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    steps.forEach((step, i) => {
      const run = () => {
        els.trace.append(stepNode(step));
        const lane = laneEls[step.agent];
        if (lane) {
          Object.values(laneEls).forEach((l) => l.lane.classList.remove("active"));
          lane.lane.classList.add("used", "active");
          lane.last.textContent = step.action;
        }
        if (i === steps.length - 1 && lane) setTimeout(() => lane.lane.classList.remove("active"), 400);
      };
      if (reduce) run(); else replayTimers.push(setTimeout(run, i * 170));
    });
  }

  // ---------------------------------------------------------------- chat rendering
  function addUser(text) { els.messages.append(el("div", "msg user", text)); scrollDown(); }
  function addBot(reply, cards, isError) {
    const box = el("div", "msg bot" + (isError ? " error" : ""));
    box.append(document.createTextNode(reply));
    if (cards && cards.length) {
      const wrap = el("div", "cards");
      cards.forEach((c) => {
        const d = el("div", "dish");
        const top = el("div", "dish-top");
        top.append(el("b", "", c.name), el("span", "price", inr(c.price)));
        d.append(top, el("div", "dish-meta", `${c.category} · ${c.spice_level} spice${c.dietary_tags.length ? " · " + c.dietary_tags.join(", ") : ""}`));
        if (c.reasons && c.reasons.length) {
          const ul = el("ul", "reasons");
          c.reasons.slice(0, 3).forEach((r) => ul.append(el("li", "", r)));
          d.append(ul);
        }
        const btn = el("button", "", "Add to cart");
        btn.type = "button";
        btn.addEventListener("click", () => send(`add ${c.name}`));
        d.append(btn);
        wrap.append(d);
      });
      box.append(wrap);
    }
    els.messages.append(box);
    scrollDown();
  }
  function renderQuick(pending) {
    els.quick.replaceChildren();
    const make = (label, msg, primary) => {
      const b = el("button", primary ? "primary" : "", label);
      b.type = "button";
      b.addEventListener("click", () => send(msg));
      els.quick.append(b);
    };
    if (!pending) return;
    if (pending.type === "confirm_order") { make("Yes, place order", "yes", true); make("No, not yet", "no, don't place the order"); }
    else if (pending.type === "offer_item") { make("Yes, add it", "yes", true); make("No thanks", "no"); }
    else if (pending.type === "confirm_cancel") { make("Yes, cancel", "yes", true); make("Keep it", "no"); }
  }

  // ---------------------------------------------------------------- state panels
  function renderPrefs(prefs) {
    els.prefs.replaceChildren();
    const pills = [];
    if (prefs.diet) pills.push(prefs.diet);
    if (prefs.budget != null) pills.push(`under ${inr(prefs.budget)}`);
    if (prefs.category) pills.push(prefs.category);
    if (prefs.max_spice_level) pills.push(`spice ≤ ${prefs.max_spice_level}`);
    if (prefs.spice_level) pills.push(`${prefs.spice_level} spice`);
    if (prefs.protein_focus) pills.push("protein-rich");
    (prefs.exclude_ingredients || []).forEach((i) => pills.push(`no ${i}`));
    if (!pills.length) { els.prefs.append(el("span", "muted", "None yet")); return; }
    pills.forEach((p) => els.prefs.append(el("span", "pill", p)));
  }
  function renderCart(cart) {
    els.cart.replaceChildren();
    if (!cart || !cart.lines.length) { els.cart.append(el("span", "muted", "Empty")); return; }
    cart.lines.forEach((l) => {
      const row = el("div", "cart-line");
      row.append(el("span", "", `${l.quantity} × ${l.name}`), el("span", "", inr(l.subtotal)));
      els.cart.append(row);
    });
    const total = el("div", "cart-total");
    total.append(el("span", "", "Total (calculated by backend)"), el("span", "", inr(cart.total_amount)));
    els.cart.append(total);
  }
  function renderKitchen(k) {
    if (!k) return;
    els.kitchen.replaceChildren();
    els.kitchen.append(el("span", `level ${k.level}`, k.level));
    els.kitchen.append(el("p", "muted", `${k.active_orders} active order(s) · ~${k.estimated_wait_minutes} min wait (estimate)`));
  }

  // ---------------------------------------------------------------- live order tracker (inside the chat)
  let tracker = null;
  const STATUS_TEXT = {
    preparing: "🍳 The kitchen has started cooking your order.",
    ready: "✅ Your order is ready for pickup!",
    completed: "🎉 Order completed. Enjoy your meal!",
    cancelled: "Your order was cancelled.",
  };
  function stopTracker() { if (tracker) { clearInterval(tracker.poll); clearInterval(tracker.clock); tracker = null; } }
  function startTracker(code) {
    stopTracker();
    const card = el("div", "msg bot live");
    const title = el("h4", "", "Live order tracking");
    const big = el("div", "big", "--:--");
    const status = el("div", "muted", "Checking…");
    const bar = el("div", "mini-bar"); const fill = el("i"); bar.append(fill);
    const link = el("a", "", "Open full tracking page ↗"); link.href = `track.html?code=${encodeURIComponent(code)}`; link.target = "_blank"; link.rel = "noopener";
    const rate = el("div", "rate-row"); rate.hidden = true;
    for (let i = 1; i <= 5; i++) { const b = el("button", "", "★"); b.type = "button"; b.title = `${i} star${i > 1 ? "s" : ""}`; b.addEventListener("click", () => { rate.hidden = true; send(`rate ${i} stars`); }); rate.append(b); }
    card.append(title, big, bar, status, rate, link);
    els.messages.append(card); scrollDown();
    const t = { code, data: null, fetchedAt: 0, last: null, poll: null, clock: null };
    tracker = t;
    const paintClock = () => {
      const d = t.data; if (!d) return;
      card.className = `msg bot live ${d.state}`;
      if (d.remaining_seconds == null) { big.textContent = d.status === "ready" || d.status === "completed" ? "Ready" : "—"; fill.style.width = d.status === "cancelled" ? "0%" : "100%"; return; }
      const left = Math.max(0, d.remaining_seconds - (Date.now() - t.fetchedAt) / 1000), total = d.eta_minutes * 60;
      if (left === 0) { const over = d.elapsed_seconds + (Date.now() - t.fetchedAt) / 1000 - total; big.textContent = `+${Math.floor(over / 60)}:${String(Math.floor(over % 60)).padStart(2, "0")} over`; fill.style.width = "100%"; }
      else { big.textContent = `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, "0")}`; fill.style.width = Math.min(100, 100 - (left / total) * 100) + "%"; }
    };
    const refresh = async () => {
      try {
        const d = await TasteFlowAPI.request(`/api/track/${code}`);
        t.data = d; t.fetchedAt = Date.now(); status.textContent = d.message; paintClock();
        if (t.last && t.last !== d.status && STATUS_TEXT[d.status]) addBot(STATUS_TEXT[d.status]);
        t.last = d.status;
        rate.hidden = !d.can_rate;
        if (["completed", "cancelled"].includes(d.status) && !d.can_rate) stopTracker();
      } catch { /* try again on the next poll */ }
    };
    refresh();
    t.poll = setInterval(() => { if (!document.hidden) refresh(); }, 6000);
    t.clock = setInterval(paintClock, 1000);
  }

  // ---------------------------------------------------------------- send
  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; els.send.disabled = true; els.input.value = "";
    els.quick.replaceChildren();
    addUser(text);
    try {
      const data = await TasteFlowAPI.request("/api/chat", {
        method: "POST", headers: ownerHeaders(),
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      sessionId = data.session_id;
      sessionStorage.setItem(SESSION_KEY, sessionId);
      addBot(data.reply, data.cards);
      renderPrefs(data.prefs || {});
      renderCart(data.cart);
      renderKitchen(data.kitchen);
      renderQuick(data.pending);
      if (data.intent === "confirm_yes" && data.order && data.order.tracking_code) startTracker(data.order.tracking_code);
      const names = data.agents_used.map((a) => a.label).join(" → ");
      showTrace(data.trace.steps, `Intent: ${data.intent} · ${data.trace.steps.length} steps · ${data.trace.duration_ms} ms · ${names}`);
      if (!customerMode) loadStaff();
    } catch (err) {
      const offline = err.message === "Failed to fetch";
      addBot(offline ? `I can't reach the server at ${TasteFlowAPI.BASE}. Please check that the backend is running.` : err.message, null, true);
    } finally {
      busy = false; els.send.disabled = false; els.input.focus();
    }
  }

  // ---------------------------------------------------------------- staff panel
  async function loadStaff() {
    if (customerMode || !TasteFlowAPI.getToken("owner")) return;
    try {
      const [ins, unmet, runs] = await Promise.all([
        TasteFlowAPI.request("/api/owner/insights", {}, "owner"),
        TasteFlowAPI.request("/api/owner/unmet-demand", {}, "owner"),
        TasteFlowAPI.request("/api/agents/runs?limit=8", {}, "owner"),
      ]);
      els.staffPanel.hidden = false;
      if (els.staffBtn) els.staffBtn.textContent = "Staff · signed in";
      els.insights.replaceChildren();
      ins.insights.forEach((i) => els.insights.append(el("div", "insight" + (i.type === "data_warning" ? " warn" : ""), i.text)));
      if (!ins.insights.length) els.insights.append(el("span", "muted", "No insights yet."));
      const f = ins.forecast;
      els.insights.append(el("p", "muted", f.available ? `Forecast (${f.method}): ~${f.expected_orders_per_day} orders/day` : `Forecast unavailable: ${f.reason}`));
      renderOps(ins);
      els.unmet.replaceChildren();
      if (!unmet.requests.length) els.unmet.append(el("span", "muted", "None recorded yet."));
      unmet.requests.forEach((r) => els.unmet.append(el("div", "insight", `${r.request} — ${r.count}×`)));
      els.runs.replaceChildren();
      runs.forEach((r) => {
        const b = el("button", "run-row", r.message);
        b.type = "button";
        b.append(el("small", "", `${r.intent} · ${r.steps.length} steps · ${r.duration_ms} ms`));
        b.addEventListener("click", () => showTrace(r.steps, `Past run #${r.run_id}: “${r.message}” → ${r.intent}`));
        els.runs.append(b);
      });
    } catch (err) { /* sign-in cancelled or server unreachable: panel stays hidden */ }
  }

  function kv(box, k, v) { const r = el("div", "kv"); r.append(el("span", "", k), el("b", "", v)); box.append(r); }
  function renderOps(ins) {
    const o = ins.operations, fb = ins.feedback, inv = ins.inventory;
    els.ops.replaceChildren();
    if (o.samples) {
      kv(els.ops, "Avg time to ready", `${o.avg_minutes_to_ready} min`); kv(els.ops, "Median", `${o.median_minutes_to_ready} min`);
      if (o.on_time_rate_pct != null) kv(els.ops, "Ready within estimate", `${o.on_time_rate_pct}%`);
      kv(els.ops, "Orders measured", String(o.samples));
    } else els.ops.append(el("span", "muted", "No timed orders yet. Timings are recorded from kitchen status changes."));
    els.fb.replaceChildren();
    if (!fb.count) els.fb.append(el("span", "muted", "No ratings yet."));
    else {
      kv(els.fb, "Average rating", `${fb.average} / 5 (${fb.count})`); kv(els.fb, "Needs follow-up", String(fb.needs_follow_up));
      fb.top_complaints.slice(0, 3).forEach((c) => kv(els.fb, `Complaint: ${c.topic}`, `${c.count}×`));
      fb.recent.filter((r) => !r.resolved).slice(0, 4).forEach((r) => {
        const row = el("div", "fb-row flag");
        row.append(el("span", "stars-s", "★".repeat(r.rating) + "☆".repeat(5 - r.rating)), el("div", "", r.comment || "(no comment)"));
        const b = el("button", "btn-s", "Mark resolved"); b.type = "button";
        b.addEventListener("click", async () => { b.disabled = true; try { await TasteFlowAPI.request(`/api/owner/feedback/${r.id}/resolve`, { method: "PATCH" }, "owner"); loadStaff(); } catch (e) { b.disabled = false; } });
        row.append(b); els.fb.append(row);
      });
    }
    els.inv.replaceChildren();
    if (!inv.tracked) els.inv.append(el("span", "muted", "Stock tracking is off. Set a stock quantity on a dish to enable alerts."));
    [...inv.sold_out.map((m) => ({ ...m, tag: "sold out" })), ...inv.low_stock.map((m) => ({ ...m, tag: "low" }))].forEach((m) => {
      const row = el("div", "fb-row" + (m.tag === "sold out" ? " flag" : "")); row.append(el("b", "", `${m.name}: ${m.stock} left (${m.tag})`));
      const b = el("button", "btn-s", "+10 stock"); b.type = "button";
      b.addEventListener("click", async () => { b.disabled = true; try { await TasteFlowAPI.request(`/api/owner/menu/${m.id}/stock`, { method: "PATCH", body: JSON.stringify({ stock_quantity: m.stock + 10 }) }, "owner"); loadStaff(); } catch (e) { b.disabled = false; } });
      row.append(el("br"), b); els.inv.append(row);
    });
    if (inv.tracked && !inv.sold_out.length && !inv.low_stock.length) els.inv.append(el("span", "muted", `All ${inv.tracked} tracked dishes are well stocked.`));
  }

  // ---------------------------------------------------------------- events
  els.form.addEventListener("submit", (e) => { e.preventDefault(); send(els.input.value); });
  if (els.staffBtn) els.staffBtn.addEventListener("click", () => loadStaff());
  els.reset.addEventListener("click", async () => {
    if (sessionId) { try { await TasteFlowAPI.request("/api/chat/reset", { method: "POST", body: JSON.stringify({ session_id: sessionId }) }); } catch { /* start fresh anyway */ } }
    els.messages.replaceChildren(); els.quick.replaceChildren();
    stopTracker(); renderPrefs({}); renderCart(null); showTrace([], "");
    addBot("Fresh start! What are you in the mood for?");
  });
  EXAMPLES.forEach((t) => {
    const b = el("button", "", t.length > 38 ? t.slice(0, 36) + "…" : t);
    b.type = "button"; b.title = t;
    b.addEventListener("click", () => send(t));
    els.chips.append(b);
  });

  buildLanes(FALLBACK_AGENTS);
  loadRegistry();
  loadStaff();
  addBot("Welcome to TasteFlow Bistro! Tell me what you feel like eating — budget, diet and spice level all work — and I'll check our real menu and the kitchen.");
})();
