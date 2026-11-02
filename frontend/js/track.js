"use strict";
/* Live order tracking. The server sends how many seconds are left; this page ticks the
   clock locally every second and re-checks the server every 5 seconds (paused when the tab
   is hidden). All text is inserted with textContent. */
(() => {
  const $ = (id) => document.getElementById(id);
  const C = 339.292; // ring circumference
  const params = new URLSearchParams(location.search);
  let code = (params.get("code") || sessionStorage.getItem("tasteflow.track.code") || "").toUpperCase();
  let data = null, fetchedAt = 0, pollTimer = null, tickTimer = null, rating = 0, lastStatus = null;

  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");
  const localTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  const HEADLINE = {
    on_time: { pending: "We’ve got your order", preparing: "Cooking in progress" },
    delayed: "Running a little late",
    ready: "Your order is ready!",
    completed: "Order complete",
    cancelled: "Order cancelled",
  };

  function show(which) { $("finder").hidden = which !== "finder"; $("tracker").hidden = which !== "tracker"; }

  async function load() {
    try {
      data = await TasteFlowAPI.request(`/api/track/${encodeURIComponent(code)}`);
    } catch (err) {
      if (err.status === 404) {
        stop(); sessionStorage.removeItem("tasteflow.track.code");
        show("finder"); $("finder-error").textContent = err.message; return;
      }
      $("message").textContent = err.message === "Failed to fetch" ? "Can’t reach the server. Retrying…" : err.message;
      return;
    }
    fetchedAt = Date.now();
    sessionStorage.setItem("tasteflow.track.code", code);
    render();
    if (["completed", "cancelled"].includes(data.status) && (!data.can_rate)) stopPolling();
  }

  function remaining() {
    if (data.remaining_seconds == null) return null;
    return Math.max(0, data.remaining_seconds - (Date.now() - fetchedAt) / 1000);
  }

  function render() {
    show("tracker");
    const d = data;
    $("hero").dataset.state = d.state;
    $("hello").textContent = `Hi ${d.customer_first_name},`;
    $("code-label").textContent = d.code;
    const head = d.state === "on_time" ? HEADLINE.on_time[d.status] || "Order received" : HEADLINE[d.state];
    $("headline").textContent = head;
    $("message").textContent = d.message;
    $("est-note").hidden = !["pending", "preparing"].includes(d.status);

    // steps
    const ol = $("steps"); ol.replaceChildren();
    d.steps.forEach((s) => {
      const li = el("li", (s.done ? "done " : "") + (s.current && !["completed"].includes(d.status) ? "current" : ""), s.label);
      if (s.at) li.append(el("small", "", localTime(s.at)));
      ol.append(li);
    });
    if (d.status === "cancelled") ol.replaceChildren(el("li", "done current", "Cancelled"));

    // items
    const ul = $("items"); ul.replaceChildren();
    d.items.forEach((i) => { const li = el("li"); li.append(el("span", "", `${i.quantity} × ${i.name}`)); ul.append(li); });
    $("total").textContent = inr(d.total_amount);
    const bits = [d.order_type === "dine_in" ? `Dine-in${d.table_number ? ", table " + d.table_number : ""}` : "Takeaway"];
    if (d.notes) bits.push(`Note: ${d.notes}`);
    if (d.orders_ahead) bits.push(`${d.orders_ahead} order${d.orders_ahead > 1 ? "s" : ""} ahead of yours`);
    $("meta").textContent = bits.join(" · ");
    $("cancel-btn").hidden = !d.can_cancel;
    $("rate-panel").hidden = !(d.can_rate || d.rated);
    if (d.rated) { $("stars").hidden = true; $("comment").hidden = true; $("rate-btn").hidden = true; if (!$("rate-msg").textContent) $("rate-msg").textContent = "Thanks, you’ve already shared your feedback."; }

    if (lastStatus && lastStatus !== d.status) { document.title = `${d.status === "ready" ? "✅ Ready" : "Update"} · TasteFlow`; }
    lastStatus = d.status;
    tick();
  }

  function tick() {
    if (!data) return;
    const r = remaining();
    const ring = $("ring-fg");
    if (r == null) {
      const done = data.status === "ready" || data.status === "completed";
      $("clock").textContent = done ? "Ready" : "—";
      $("clock").style.fontSize = done ? "1.9rem" : "";
      $("clock-label").textContent = done ? "enjoy your meal" : "";
      ring.style.strokeDashoffset = done ? 0 : C;
      return;
    }
    $("clock").style.fontSize = "";
    const total = data.eta_minutes * 60;
    if (r === 0) {
      const over = Math.max(0, data.elapsed_seconds + (Date.now() - fetchedAt) / 1000 - total);
      $("clock").textContent = "+" + fmt(over);
      $("clock-label").textContent = "over the estimate";
      ring.style.strokeDashoffset = 0;
    } else {
      $("clock").textContent = fmt(r);
      $("clock-label").textContent = "estimated time left";
      ring.style.strokeDashoffset = C * (r / total);
      document.title = `⏱ ${fmt(r)} · TasteFlow`;
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => { if (!document.hidden) load(); }, 5000);
    tickTimer = setInterval(tick, 1000);
  }
  function stopPolling() { clearInterval(pollTimer); }
  function stop() { stopPolling(); clearInterval(tickTimer); }

  // stars
  const starsBox = $("stars");
  for (let i = 1; i <= 5; i++) {
    const b = el("button", "", "★"); b.type = "button"; b.setAttribute("role", "radio"); b.setAttribute("aria-label", `${i} star${i > 1 ? "s" : ""}`);
    b.addEventListener("click", () => {
      rating = i; $("rate-btn").disabled = false;
      [...starsBox.children].forEach((s, idx) => s.classList.toggle("on", idx < i));
    });
    starsBox.append(b);
  }
  $("rate-btn").addEventListener("click", async () => {
    $("rate-btn").disabled = true;
    try {
      const r = await TasteFlowAPI.request(`/api/track/${code}/feedback`, { method: "POST", body: JSON.stringify({ rating, comment: $("comment").value || null }) });
      $("rate-msg").textContent = r.message;
      $("stars").hidden = true; $("comment").hidden = true; $("rate-btn").hidden = true;
    } catch (err) { $("rate-msg").className = "err"; $("rate-msg").textContent = err.message; $("rate-btn").disabled = false; }
  });
  $("cancel-btn").addEventListener("click", async () => {
    if (!confirm("Cancel this order? This can't be undone.")) return;
    try { await TasteFlowAPI.request(`/api/track/${code}/cancel`, { method: "PATCH" }); await load(); }
    catch (err) { $("message").textContent = err.message; }
  });
  $("finder-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("code-input").value.trim().toUpperCase();
    if (!/^[A-Z0-9]{4,12}$/.test(v)) { $("finder-error").textContent = "That doesn’t look like a tracking code."; return; }
    code = v; $("finder-error").textContent = ""; history.replaceState(null, "", `?code=${code}`);
    load().then(startPolling);
  });
  $("another").addEventListener("click", (e) => { e.preventDefault(); stop(); sessionStorage.removeItem("tasteflow.track.code"); history.replaceState(null, "", "track.html"); data = null; $("code-input").value = ""; show("finder"); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && data) load(); });

  if (code) { load().then(startPolling); } else { show("finder"); }
})();
