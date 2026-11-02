"use strict";
/* Owner Menu Manager. Talks to /api/owner/menu (owner token required). Text via textContent only. */
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const api = (path, opts) => TasteFlowAPI.request(path, opts || {}, "owner");
  const PLACEHOLDER = "data/placeholder.svg";
  let dishes = [], editingId = null;

  const imgFor = (url) => { const i = el("img"); i.alt = ""; i.loading = "lazy"; i.src = url || PLACEHOLDER; i.addEventListener("error", () => { i.src = PLACEHOLDER; }, { once: true }); return i; };
  function flash(text, bad) { const f = $("flash"); f.textContent = text; f.className = "flash" + (bad ? " bad" : ""); f.hidden = false; clearTimeout(flash.t); flash.t = setTimeout(() => { f.hidden = true; }, 5000); }

  // ------------------------------------------------------------ list
  function renderList() {
    const q = $("search").value.trim().toLowerCase(), cat = $("cat-filter").value, showGone = $("show-archived").checked;
    const rows = dishes.filter((d) => (showGone || !d.archived) && (!cat || d.category === cat) && (!q || (d.name + " " + d.category).toLowerCase().includes(q)));
    $("count").textContent = `${rows.length} dish${rows.length === 1 ? "" : "es"}`;
    const list = $("list"); list.replaceChildren();
    if (!rows.length) list.append(el("p", "muted", "No dishes match."));
    rows.forEach((d) => {
      const r = el("div", "dish" + (d.archived ? " gone" : ""));
      const name = el("div"); name.append(el("b", "", d.name), el("small", "", `${d.category} · ${d.spice_level} · ${(d.dietary_tags || []).join(", ") || "no tags"}`));
      const status = el("span", "pill " + (d.archived ? "arch" : d.available ? "on" : "off"), d.archived ? "Removed" : d.available ? "Available" : "Unavailable");
      const stock = el("small", "hide-s", d.stock_quantity == null ? "stock: not tracked" : `stock: ${d.stock_quantity}`);
      const acts = el("div", "acts");
      const btn = (label, fn, cls) => { const b = el("button", "sm " + (cls || ""), label); b.type = "button"; b.addEventListener("click", fn); acts.append(b); };
      if (d.archived) btn("Restore", () => act(() => api(`/api/owner/menu/${d.id}/restore`, { method: "POST" }), `${d.name} restored.`));
      else {
        btn("Edit", () => openEditor(d));
        btn(d.available ? "Mark unavailable" : "Mark available", () => act(() => api(`/api/owner/menu/${d.id}`, { method: "PATCH", body: JSON.stringify({ available: !d.available }) }), `${d.name} is now ${d.available ? "unavailable" : "available"}.`));
        btn("Remove", () => { if (confirm(`Remove “${d.name}” from the menu? Past orders are kept and you can restore it later.`)) act(() => api(`/api/owner/menu/${d.id}`, { method: "DELETE" }), `${d.name} removed from the menu.`); }, "danger");
      }
      r.append(imgFor(d.image), name, el("b", "", "₹" + d.price), status, stock, acts); list.append(r);
    });
  }
  async function act(fn, okMsg) { try { await fn(); flash(okMsg); await load(); } catch (e) { flash(e.message, true); } }

  async function load() {
    dishes = await api("/api/owner/menu");
    const cats = [...new Set(dishes.map((d) => d.category))].sort();
    const sel = $("cat-filter"), keep = sel.value; sel.replaceChildren(new Option("All categories", "")); cats.forEach((c) => sel.append(new Option(c, c))); sel.value = cats.includes(keep) ? keep : "";
    const dl = $("cats"); dl.replaceChildren(); cats.forEach((c) => dl.append(new Option(c)));
    renderList();
  }

  // ------------------------------------------------------------ editor
  const tagBoxes = () => [...document.querySelectorAll('input[name="tag"]')];
  function readForm() {
    const num = (id) => ($(id).value === "" ? null : Number($(id).value));
    return { name: $("f-name").value, price: num("f-price"), category: $("f-category").value, description: $("f-desc").value,
      ingredients: $("f-ing").value.split(",").map((s) => s.trim()).filter(Boolean), dietary_tags: tagBoxes().filter((c) => c.checked).map((c) => c.value),
      spice_level: $("f-spice").value, prep_minutes: num("f-prep"), stock_quantity: num("f-stock"), cost_price: num("f-cost"),
      image: $("f-image").value.trim() || null, available: $("f-avail").checked };
  }
  function renderPreview() {
    const d = readForm(), box = $("preview"); box.replaceChildren();
    const b = el("div", "b"); b.append(el("span", "p", d.price ? "₹" + d.price : "₹–"), el("h4", "", d.name || "Dish name"), el("div", "m", `${d.category || "Category"} · ${d.spice_level} spice`));
    if (d.description) b.append(el("div", "m", d.description));
    const t = el("div", "t"); d.dietary_tags.forEach((x) => t.append(el("span", "", x))); b.append(t);
    box.append(imgFor(d.image), b);
  }
  function openEditor(d) {
    editingId = d ? d.id : null; $("ed-title").textContent = d ? `Edit “${d.name}”` : "Add a new dish"; $("form-err").textContent = "";
    $("form").reset(); $("f-avail").checked = true;
    if (d) {
      $("f-name").value = d.name; $("f-price").value = d.price; $("f-category").value = d.category; $("f-desc").value = d.description || ""; $("f-ing").value = (d.ingredients || []).join(", ");
      tagBoxes().forEach((c) => { c.checked = (d.dietary_tags || []).includes(c.value); }); $("f-spice").value = d.spice_level;
      $("f-prep").value = d.prep_minutes ?? ""; $("f-stock").value = d.stock_quantity ?? ""; $("f-cost").value = d.cost_price ?? ""; $("f-image").value = d.image === PLACEHOLDER ? "" : d.image; $("f-avail").checked = d.available;
    }
    $("editor").hidden = false; renderPreview(); $("f-name").focus(); $("editor").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  $("form").addEventListener("input", renderPreview);
  $("add").addEventListener("click", () => openEditor(null));
  $("cancel").addEventListener("click", () => { $("editor").hidden = true; });
  $("form").addEventListener("submit", async (e) => {
    e.preventDefault(); $("form-err").textContent = ""; const body = readForm();
    if (!body.name.trim() || !body.category.trim() || !body.price) { $("form-err").textContent = "Name, price and category are required."; return; }
    $("save").disabled = true;
    try {
      const saved = editingId ? await api(`/api/owner/menu/${editingId}`, { method: "PATCH", body: JSON.stringify(body) }) : await api("/api/owner/menu", { method: "POST", body: JSON.stringify(body) });
      $("editor").hidden = true; flash(`${saved.name} ${editingId ? "updated" : "added"}. Guests can see it now.`); await load();
    } catch (err) { $("form-err").textContent = err.message; } finally { $("save").disabled = false; }
  });
  ["search", "cat-filter", "show-archived"].forEach((id) => $(id).addEventListener("input", renderList));

  load().catch((e) => { if (e.status !== 401) flash(e.message, true); });
})();
