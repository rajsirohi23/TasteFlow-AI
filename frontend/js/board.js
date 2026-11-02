"use strict";
/* Kitchen display board: polls /api/kitchen/board every 5s, ticks timers every second,
   and moves orders forward with one tap. Text is inserted with textContent only. */
(() => {
  const $ = (id) => document.getElementById(id);
  const NEXT = { pending: ["preparing", "Start cooking"], preparing: ["ready", "Mark ready"], ready: ["completed", "Handed over"] };
  let orders = [], fetchedAt = Date.now(), seenPending = null, soundOn = false, audio = null;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  function beep() {
    if (!soundOn) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const o = audio.createOscillator(), g = audio.createGain();
      o.connect(g); g.connect(audio.destination); o.frequency.value = 880; g.gain.value = 0.08;
      o.start(); o.stop(audio.currentTime + 0.25);
    } catch { /* sound is optional */ }
  }

  function elapsed(o) { return o.elapsed_seconds + (Date.now() - fetchedAt) / 1000; }

  function ticket(o) {
    const late = o.late || (["pending", "preparing"].includes(o.status) && elapsed(o) > o.eta_minutes * 60);
    const t = el("article", "ticket" + (late ? " late" : "")); t.dataset.status = o.status; t.dataset.id = o.id;
    const head = el("div", "t-head"); head.append(el("b", "", `#${o.id}`), el("span", "t-name", o.customer_name)); t.append(head);
    const chips = el("div", "chips2");
    chips.append(el("span", "chip2" + (o.order_type === "dine_in" ? " dine" : ""), o.order_type === "dine_in" ? `Dine-in${o.table_number ? " · table " + o.table_number : ""}` : "Takeaway"));
    chips.append(el("span", "chip2 web", o.source));
    if (o.stale) chips.append(el("span", "chip2 stale", "Old order, please clear"));
    t.append(chips);
    if (o.notes) t.append(el("div", "note", `📝 ${o.notes}`));
    const ul = el("ul", "t-items");
    o.items.forEach((i) => { const li = el("li"); li.append(el("span", "q", `${i.quantity}×`), el("span", "", i.name)); ul.append(li); });
    t.append(ul);
    if (o.status !== "ready") {
      const timer = el("div", "timer"); timer.append(el("span", "", `ETA ${o.eta_minutes} min`));
      const b = el("b", "elapsed", ""); timer.append(b); t.append(timer);
      const bar = el("div", "bar"); bar.append(el("i")); t.append(bar);
    }
    const [to, label] = NEXT[o.status];
    const btn = el("button", "advance", label); btn.type = "button"; btn.dataset.to = to;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { await TasteFlowAPI.request(`/api/kitchen/orders/${o.id}/status`, { method: "PATCH", body: JSON.stringify({ status: to }) }, "kitchen"); await refresh(); }
      catch (err) { btn.disabled = false; $("foot").textContent = err.message; }
    });
    t.append(btn);
    return t;
  }

  function paint() {
    ["pending", "preparing", "ready"].forEach((s) => {
      const col = $("col-" + s); col.replaceChildren();
      const list = orders.filter((o) => o.status === s);
      $("c-" + s).textContent = list.length;
      if (!list.length) col.append(el("div", "empty-col", s === "pending" ? "No new orders" : "Nothing here"));
      list.forEach((o) => col.append(ticket(o)));
    });
    tick();
  }

  function tick() {
    document.querySelectorAll(".ticket").forEach((t) => {
      const o = orders.find((x) => String(x.id) === t.dataset.id); if (!o) return;
      const b = t.querySelector(".elapsed"); if (!b) return;
      const e = elapsed(o), total = o.eta_minutes * 60;
      b.textContent = e > total ? `+${mmss(e - total)} over` : `${mmss(e)} elapsed`;
      t.querySelector(".bar i").style.width = Math.min(100, (e / total) * 100) + "%";
      t.classList.toggle("late", e > total);
    });
  }

  async function refresh() {
    try {
      const d = await TasteFlowAPI.request("/api/kitchen/board", {}, "kitchen");
      orders = d.orders; fetchedAt = Date.now();
      const pending = orders.filter((o) => o.status === "pending").length;
      if (seenPending !== null && pending > seenPending) beep();
      seenPending = pending;
      const l = d.load; $("m-level").textContent = l.level; $("m-level").className = `level ${l.level}`;
      $("m-active").textContent = l.active_orders; $("m-late").textContent = l.late_orders; $("m-wait").textContent = l.estimated_wait_minutes;
      $("foot").dataset.stale = l.stale_orders || 0;
      const stale = l.stale_orders ? ` · ${l.stale_orders} old order(s) are excluded from wait times; complete or cancel them` : "";
      $("foot").textContent = `Updated ${new Date().toLocaleTimeString()} · refreshes every 5 s · wait times are estimates${stale}`;
      paint();
    } catch (err) { $("foot").textContent = err.message === "Failed to fetch" ? "Can’t reach the server. Retrying…" : err.message; }
  }

  $("sound").addEventListener("change", (e) => { soundOn = e.target.checked; if (soundOn) beep(); });
  refresh(); setInterval(() => { if (!document.hidden) refresh(); }, 5000); setInterval(tick, 1000);
})();
