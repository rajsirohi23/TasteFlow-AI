"use strict";
/* Owner Command Center. All numbers come from /api/owner/*; nothing is hard-coded.
   Charts are plain SVG/DOM (no libraries). Text is inserted with textContent only. */
(() => {
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const sv = (tag, attrs = {}, text) => { const n = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); if (text !== undefined) n.textContent = text; return n; };
  const api = (path, opts) => TasteFlowAPI.request(path, opts || {}, "owner");
  const inr = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const QUAD = { star: "#3ecf8e", workhorse: "#5aa9ff", puzzle: "#ffc857", dog: "#ff6b6b" };

  function countUp(node, to, fmtIn) {
    const fmt = fmtIn || ((x) => String(Math.round(x)));
    const from = Number(node.dataset.v || 0); node.dataset.v = to;
    if (reduce || from === to) { node.textContent = fmt(to); return; }
    const t0 = performance.now();
    (function step(t) { const k = Math.min(1, (t - t0) / 700); node.textContent = fmt(from + (to - from) * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); })(t0);
  }
  const speak = (text) => { if (!("speechSynthesis" in window)) return; speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text.replace(/₹([\d,]+)/g, "$1 rupees")); u.lang = "en-IN"; speechSynthesis.speak(u); };

  // ---------------------------------------------------------------- KPIs
  function renderKpis(p) {
    const box = $("kpis");
    if (!box.children.length) ["Revenue today", "Orders today", "Avg order", "Kitchen", "Rating today"].forEach((l, i) => {
      const k = el("div", "kpi"); k.append(el("div", "l", l), el("div", "v", "0"), el("div", "d")); k.id = "k" + i; box.append(k);
    });
    const set = (i, val, fmt, detail, cls) => { const k = $("k" + i); countUp(k.querySelector(".v"), val, fmt); const d = k.querySelector(".d"); d.textContent = detail; d.className = "d " + (cls || ""); };
    const vs = p.revenue_vs_last_week_pct;
    set(0, p.revenue_today, inr, vs == null ? "no data for the same time last week" : `${vs >= 0 ? "▲" : "▼"} ${Math.abs(vs)}% vs same time last week`, vs == null ? "" : vs >= 0 ? "up" : "down");
    set(1, p.orders_today, null, "non-cancelled");
    set(2, p.avg_order_value || 0, inr, p.avg_order_value ? "per order" : "no orders yet");
    set(3, p.kitchen.active_orders, null, `${p.kitchen.level} · wait ≈ ${p.kitchen.estimated_wait_minutes} min · ${p.kitchen.late_orders} late`, p.kitchen.late_orders ? "down" : "");
    set(4, p.rating_today || 0, (x) => (p.rating_today ? x.toFixed(1) + " ★" : "–"), p.ratings_today ? `${p.ratings_today} ratings` : "no ratings today");
    renderSeries(p.series);
  }

  function renderSeries(series) {
    const W = 520, H = 190, pad = 24, max = Math.max(1, ...series.map((s) => s.revenue));
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Revenue per day" });
    const bw = (W - pad * 2) / series.length;
    series.forEach((s, i) => {
      const h = (s.revenue / max) * (H - 50), x = pad + i * bw, y = H - 26 - h;
      const r = sv("rect", { x: x + 3, y, width: bw - 6, height: h, rx: 4, fill: i === series.length - 1 ? "#f08a4b" : "#3ecf8e", opacity: i === series.length - 1 ? 1 : 0.75 });
      r.append(sv("title", {}, `${s.date}: ${inr(s.revenue)} from ${s.orders} orders`)); svg.append(r);
      if (i % 2 === 0 || i === series.length - 1) svg.append(sv("text", { x: x + bw / 2, y: H - 8, "text-anchor": "middle", fill: "#8da79a", "font-size": 9 }, s.date.slice(8)));
    });
    $("series").replaceChildren(svg);
    const total = series.reduce((a, s) => a + s.revenue, 0); $("series-note").textContent = `${inr(total)} total`;
  }

  // ---------------------------------------------------------------- alerts / activity / floor
  function renderAlerts(list) {
    const box = $("alerts"); box.replaceChildren();
    if (!list.length) { box.append(el("p", "ok-all", "✓ All clear. Nothing needs attention.")); return; }
    list.forEach((a) => { const d = el("div", `alert ${a.severity}`); d.append(el("b", "", a.title), el("span", "", a.detail)); box.append(d); });
  }
  function renderActivity(events) {
    const ul = $("activity"); ul.replaceChildren();
    if (!events.length) ul.append(el("li", "", "No activity yet."));
    events.slice(0, 14).forEach((e) => { const li = el("li"); li.append(el("time", "", new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })), el("span", "", e.text)); ul.append(li); });
  }
  function renderFloor(f) {
    const box = $("floor"); box.replaceChildren();
    f.tables.forEach((t) => {
      const d = el("div", `tbl s-${t.state}`); d.append(el("b", "", `T${t.table}`), el("span", "", t.info ? `${t.state === "serve" ? "SERVE · " : ""}${t.info.name} · ${t.info.minutes}m` : "free"));
      box.append(d);
    });
    const c = f.counts; $("floor-note").textContent = `${(c.ordered || 0) + (c.cooking || 0) + (c.serve || 0) + (c.dining || 0)} of ${f.tables.length} in use`;
  }

  // ---------------------------------------------------------------- heatmap / forecast
  function renderHeat(h) {
    const box = $("heat"); box.replaceChildren(); const now = new Date();
    box.append(el("div", "h")); for (let i = 0; i < 24; i++) box.append(el("div", "h", i % 3 === 0 ? String(i) : ""));
    h.days.forEach((d, w) => {
      box.append(el("div", "h", d));
      h.grid[w].forEach((n, hr) => {
        const c = el("div"); const a = h.max ? n / h.max : 0;
        c.style.background = n ? `rgba(240,138,75,${0.12 + a * 0.88})` : "#0f1f1a"; c.title = `${d} ${hr}:00 · ${n} orders`;
        if (w === (now.getDay() + 6) % 7 && hr === now.getHours()) c.classList.add("now"); box.append(c);
      });
    });
  }
  function renderForecast(f) {
    const box = $("forecast"); box.replaceChildren();
    if (!f.hours.length) { box.append(el("p", "fine", f.reason)); $("fc-basis").textContent = ""; return; }
    const W = 640, H = 200, bw = W / 24, max = Math.max(1, ...f.hours.map((x) => x.expected_orders));
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Expected orders per hour" });
    f.hours.forEach((x, i) => {
      const h = (x.expected_orders / max) * (H - 60), y = H - 34 - h, peak = x.label === f.peak.label;
      const r = sv("rect", { x: i * bw + 3, y, width: bw - 6, height: h, rx: 4, fill: peak ? "#f08a4b" : "#5aa9ff", opacity: f.available ? 1 : 0.45 });
      r.append(sv("title", {}, `${x.label}: ~${x.expected_orders} orders, ${x.recommended_stations} station(s)`)); svg.append(r);
      svg.append(sv("text", { x: i * bw + bw / 2, y: y - 14, "text-anchor": "middle", fill: "#e9f2ed", "font-size": 9 }, x.expected_orders ? String(x.expected_orders) : ""));
      svg.append(sv("text", { x: i * bw + bw / 2, y: y - 4, "text-anchor": "middle", fill: "#8da79a", "font-size": 8 }, x.expected_orders ? `${x.recommended_stations}👨‍🍳` : ""));
      if (i % 3 === 0) svg.append(sv("text", { x: i * bw + bw / 2, y: H - 18, "text-anchor": "middle", fill: "#8da79a", "font-size": 9 }, `${String(x.hour).padStart(2, "0")}h`));
    });
    box.append(svg);
    $("fc-note").textContent = f.available ? `peak ${f.peak.label} · ~${f.peak.expected_orders} orders` : "⚠ low data, indicative only";
    $("fc-basis").textContent = (f.available ? "" : f.reason + " ") + f.method + ". " + f.basis;
  }

  // ---------------------------------------------------------------- menu engineering / combos
  function renderMenu(m) {
    const box = $("menu-eng"); box.replaceChildren();
    if (!m.items.length) { box.append(el("p", "fine", "No menu.")); return; }
    const W = 520, H = 280, P = 34, mx = Math.max(1, ...m.items.map((i) => i.units)), my = Math.max(1, ...m.items.map((i) => i.value));
    const X = (u) => P + (u / mx) * (W - P * 2), Y = (v) => H - P - (v / my) * (H - P * 2);
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Menu engineering matrix" });
    svg.append(sv("line", { x1: X(m.popularity_cut), x2: X(m.popularity_cut), y1: P / 2, y2: H - P, stroke: "#244237", "stroke-dasharray": "4" }));
    svg.append(sv("line", { x1: P, x2: W - P / 2, y1: Y(m.value_cut), y2: Y(m.value_cut), stroke: "#244237", "stroke-dasharray": "4" }));
    [["Stars", W - 60, 22, "#3ecf8e"], ["Puzzles", 50, 22, "#ffc857"], ["Workhorses", W - 70, H - 40, "#5aa9ff"], ["Dogs", 40, H - 40, "#ff6b6b"]].forEach(([t, x, y, c]) => svg.append(sv("text", { x, y, fill: c, "font-size": 11, opacity: 0.8 }, t)));
    m.items.forEach((i) => { const c = sv("circle", { cx: X(i.units), cy: Y(i.value), r: 7, fill: QUAD[i.quadrant], opacity: 0.85, stroke: "#0d1a16" }); c.append(sv("title", {}, `${i.name} · ${i.units} sold · ${inr(i.value)} per unit · ${i.quadrant.toUpperCase()}: ${i.advice}`)); svg.append(c); });
    svg.append(sv("text", { x: W / 2, y: H - 6, "text-anchor": "middle", fill: "#8da79a", "font-size": 10 }, "popularity (units sold) →"));
    box.append(svg);
    $("me-note").textContent = m.sufficient ? m.basis : "⚠ little data: " + m.basis;
    const list = $("me-list"); list.replaceChildren();
    ["dog", "puzzle"].forEach((q) => { const names = m.items.filter((i) => i.quadrant === q).map((i) => i.name); if (names.length) list.append(el("div", "", `${q === "dog" ? "🔴 Rework or remove" : "🟡 Promote"}: ${names.slice(0, 5).join(", ")}`)); });
  }
  function renderCombos(c) {
    const box = $("combos"); box.replaceChildren();
    if (!c.sufficient) { box.append(el("p", "fine", `Needs 30+ orders (have ${c.orders}).`)); return; }
    c.combos.slice(0, 6).forEach((x) => {
      const d = el("div", "combo"); const l = el("div"); l.append(el("b", "", `${x.if_name} → ${x.then_name}`), el("small", "", `${x.orders_together} of ${x.of_orders} orders · lift ${x.lift}×`));
      const b = el("div", "bar2"); b.style.width = x.confidence_pct + "%"; l.append(b); d.append(l, el("b", "", x.confidence_pct + "%")); box.append(d);
    });
    box.append(el("p", "fine", c.note));
  }

  // ---------------------------------------------------------------- rush simulator
  let simTimer = null;
  async function runSim() {
    const q = new URLSearchParams({ orders: $("s-orders").value, minutes: $("s-minutes").value, stations: $("s-stations").value });
    $("v-orders").textContent = $("s-orders").value; $("v-minutes").textContent = $("s-minutes").value; $("v-stations").textContent = $("s-stations").value;
    const r = await api(`/api/owner/simulate-rush?${q}`);
    const v = $("sim-verdict"); v.textContent = r.verdict; v.className = "verdict " + (r.pct_over_target > 25 ? "bad" : r.pct_over_target === 0 ? "good" : "");
    const st = $("sim-stats"); st.replaceChildren();
    [["Avg wait", r.avg_wait_min + " min"], ["90% done within", r.p90_total_min + " min"], ["Longest wait", r.max_wait_min + " min"], ["Missing target", r.pct_over_target + "%"], ["Stations needed", r.stations_needed ?? ">20"]]
      .forEach(([l, val]) => { const d = el("div", "", l); d.prepend(el("b", "", String(val))); st.append(d); });
    const W = 640, H = 150, T = r.timeline, mx = Math.max(1, ...T.map((t) => t.waiting + t.cooking));
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Orders waiting and cooking over time" });
    const x = (i) => (i / Math.max(1, T.length - 1)) * (W - 20) + 10, y = (n) => H - 20 - (n / mx) * (H - 36);
    const area = (key, fill) => svg.append(sv("polygon", { points: `${x(0)},${H - 20} ` + T.map((t, i) => `${x(i)},${y(key(t))}`).join(" ") + ` ${x(T.length - 1)},${H - 20}`, fill, opacity: 0.8 }));
    area((t) => t.waiting + t.cooking, "#f08a4b"); area((t) => t.cooking, "#3ecf8e");
    svg.append(sv("text", { x: 12, y: 14, fill: "#8da79a", "font-size": 10 }, "🟠 waiting in queue  🟢 being cooked · minutes →"));
    $("sim-chart").replaceChildren(svg); $("sim-method").textContent = r.method;
  }
  ["s-orders", "s-minutes", "s-stations"].forEach((id) => $(id).addEventListener("input", () => { clearTimeout(simTimer); simTimer = setTimeout(runSim, 250); }));

  // ---------------------------------------------------------------- copilot
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function bubble(text, who, data) {
    const m = el("div", `m ${who === "u" ? "u" : "b"}`, text);
    if (data && data.rows && data.rows.length && data.chart) {
      const mx = Math.max(1, ...data.rows.map((r) => r.value)); const mini = el("div", "mini");
      data.rows.slice(0, 8).forEach((r) => { const row = el("div"); row.append(el("span", "", r.label)); const b = el("i"); b.style.width = (r.value / mx) * 100 + "%"; row.append(b, el("span", "", String(r.value))); mini.append(row); });
      m.append(mini);
    }
    if (data && data.basis) m.append(el("div", "basis", `Basis: ${data.basis}`));
    $("chat").append(m); $("chat").scrollTop = $("chat").scrollHeight;
  }
  async function ask(q) {
    q = q.trim(); if (!q) return; bubble(q, "u"); $("q").value = "";
    try { const r = await api("/api/owner/copilot", { method: "POST", body: JSON.stringify({ question: q }) }); bubble(r.answer, "b", r); if ($("speak").checked) speak(r.answer); }
    catch (e) { bubble(e.message, "b"); }
  }
  $("ask").addEventListener("submit", (e) => { e.preventDefault(); ask($("q").value); });
  ["Revenue this week vs last week", "Top dishes last 30 days", "How many orders today", "Busiest hour", "Which dishes never sell?", "Average order value", "Ratings this month", "What did guests ask for that we don't have?"]
    .forEach((t) => { const b = el("button", "", t); b.type = "button"; b.addEventListener("click", () => ask(t)); $("chips").append(b); });
  if (SR) {
    $("mic").addEventListener("click", () => { const r = new SR(); r.lang = "en-IN"; r.onresult = (e) => ask(e.results[0][0].transcript); r.start(); });
  } else { $("mic").hidden = true; }
  bubble("Hi! Ask me about revenue, orders, top or slow dishes, busy hours, ratings, or unmet requests. Every answer shows how it was calculated.", "b");

  // ---------------------------------------------------------------- brief
  $("brief-btn").addEventListener("click", async () => {
    const b = await api("/api/owner/briefing"); const box = $("brief-lines"); box.replaceChildren();
    b.lines.forEach((l) => box.append(el("p", "", l))); $("brief").hidden = false; $("brief-speak").onclick = () => speak(b.speech);
  });
  $("brief-close").addEventListener("click", () => { $("brief").hidden = true; if ("speechSynthesis" in window) speechSynthesis.cancel(); });

  // ---------------------------------------------------------------- loaders
  const safe = (fn) => fn().catch((e) => { if (e.status !== 401) console.warn(e.message); });
  const live = () => Promise.all([
    safe(async () => renderKpis(await api("/api/owner/pulse"))), safe(async () => renderAlerts((await api("/api/owner/alerts")).alerts)),
    safe(async () => renderFloor(await api("/api/owner/floor"))), safe(async () => renderActivity((await api("/api/owner/activity")).events))]);
  const heavy = () => Promise.all([
    safe(async () => renderHeat(await api("/api/owner/heatmap"))), safe(async () => renderForecast(await api("/api/owner/forecast"))),
    safe(async () => renderMenu(await api("/api/owner/menu-engineering"))), safe(async () => renderCombos(await api("/api/owner/combos")))]);
  setInterval(() => { $("clock").textContent = new Date().toLocaleTimeString(); }, 1000);
  live().then(() => { heavy(); safe(runSim); });
  setInterval(() => { if (!document.hidden) live(); }, 8000);
  setInterval(() => { if (!document.hidden) heavy(); }, 60000);
})();
