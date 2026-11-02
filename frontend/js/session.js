"use strict";
/* Role handling for the website.
   - Customers need no login and never see staff links.
   - Staff pages call guard([...roles]) first: no valid session for that role => login.html.
   - Staff pages get a role-specific navigation (owner vs kitchen) and a Sign out button.
   The API enforces the same rules server-side; this layer only keeps the website tidy. */
window.TasteFlowSession = (() => {
  const A = () => window.TasteFlowAPI;
  const HOME = { owner: "command.html", kitchen: "kitchen.html" };
  const NAV = {
    owner: [["command.html", "Command Center"], ["menu-admin.html", "Menu Manager"], ["kitchen.html", "Kitchen"], ["agents.html", "Agent Console"], ["owner.html", "Classic dashboard"]],
    kitchen: [["kitchen.html", "Kitchen board"]],
  };
  const here = () => location.pathname.split("/").pop() || "index.html";

  function role() { return A().getToken("owner") ? "owner" : A().getToken("kitchen") ? "kitchen" : null; }

  function logout() { A().clearToken("owner"); A().clearToken("kitchen"); A().redirect("index.html"); }

  function renderStaffNav() {
    const r = role(); if (!r) return;
    let nav = document.querySelector("header nav, .topbar nav, .bar nav, nav[aria-label='Pages']");
    if (!nav) {  // pages without their own nav get a small fixed staff bar
      const bar = document.createElement("div");
      bar.style.cssText = "position:fixed;top:10px;right:10px;z-index:9998;background:#173f35;color:#fff;border-radius:12px;padding:8px 14px;font:600 13px system-ui;display:flex;gap:12px;align-items:center;box-shadow:0 6px 20px rgba(0,0,0,.25)";
      nav = document.createElement("nav"); nav.style.cssText = "display:flex;gap:12px;align-items:center"; bar.append(nav); document.body.append(bar);
    }
    nav.replaceChildren();
    NAV[r].forEach(([href, label]) => {
      const a = document.createElement("a"); a.href = href; a.textContent = label;
      if (href === here()) a.setAttribute("aria-current", "page");
      a.style.color = "inherit"; nav.append(a);
    });
    const who = document.createElement("span"); who.textContent = r === "owner" ? "Owner" : "Kitchen staff"; who.style.cssText = "opacity:.7;font-size:.8em;border:1px solid currentColor;border-radius:99px;padding:2px 9px";
    const out = document.createElement("button"); out.type = "button"; out.textContent = "Sign out"; out.style.cssText = "background:transparent;border:1px solid currentColor;color:inherit;border-radius:99px;padding:4px 12px;cursor:pointer;font:inherit";
    out.addEventListener("click", logout);
    nav.append(who, out);
  }

  /** Call from <head> of every staff page. Hides the page until the session is verified. */
  async function guard(allowed) {
    const root = document.documentElement; root.style.visibility = "hidden";
    const need = allowed[0];
    const r = role();
    if (!r || !allowed.includes(r)) { if (r && !allowed.includes(r)) A().redirect(`login.html?role=${need}&next=${encodeURIComponent(here())}&denied=1`); else A().redirectToLogin(need); return false; }
    try {
      const res = await fetch(`${A().BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${A().tokenFor(r === "owner" ? "owner" : "kitchen")}` } });
      if (!res.ok) throw new Error("expired");
      const me = await res.json();
      if (!allowed.includes(me.role)) throw new Error("role");
    } catch { A().clearToken("owner"); A().clearToken("kitchen"); A().redirectToLogin(need); return false; }
    const ready = () => { renderStaffNav(); root.style.visibility = ""; };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready); else ready();
    return true;
  }

  return { role, guard, logout, HOME, renderStaffNav };
})();
