"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const HOME = { owner: "command.html", kitchen: "kitchen.html" };
  const ALLOWED = { owner: ["command.html", "owner.html", "agents.html", "menu-admin.html", "kitchen.html", "kitchen-classic.html"], kitchen: ["kitchen.html", "kitchen-classic.html"] };
  const safeNext = (role) => { const n = (params.get("next") || "").split("?")[0]; return ALLOWED[role].includes(n) ? params.get("next") : HOME[role]; };
  const want = params.get("role");
  if (want === "kitchen") document.querySelector('input[value="kitchen"]').checked = true;
  if (params.get("denied")) $("denied").hidden = false;

  const current = () => (TasteFlowAPI.getToken("owner") ? "owner" : TasteFlowAPI.getToken("kitchen") ? "kitchen" : null);
  const showSigned = () => { const r = current(); if (!r) return; $("signed").hidden = false; $("who").textContent = r === "owner" ? "Owner" : "Kitchen staff"; $("continue").href = safeNext(r); };
  showSigned();
  $("signout").addEventListener("click", () => { TasteFlowAPI.clearToken("owner"); TasteFlowAPI.clearToken("kitchen"); $("signed").hidden = true; });

  $("form").addEventListener("submit", async (e) => {
    e.preventDefault(); $("err").textContent = ""; $("go").disabled = true;
    const role = document.querySelector('input[name="role"]:checked').value;
    try {
      const res = await fetch(`${TasteFlowAPI.BASE}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, pin: $("pin").value }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Sign-in failed");
      TasteFlowAPI.clearToken("owner"); TasteFlowAPI.clearToken("kitchen"); TasteFlowAPI.setToken(role, data.token);
      TasteFlowAPI.redirect(safeNext(role));
    } catch (err) {
      $("err").textContent = err.message === "Failed to fetch" ? `Can't reach the server at ${TasteFlowAPI.BASE}. Is the backend running?` : err.message;
      $("go").disabled = false; $("pin").select();
    }
  });
})();
