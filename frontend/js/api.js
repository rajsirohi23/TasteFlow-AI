"use strict";
/* Shared API client. One place for the backend address, error handling and staff tokens.
   Staff pages call request(url, opts, role). A missing/expired staff session sends the user to
   login.html (the server also checks the token on every staff API, so hiding pages is only UX). */
window.TasteFlowAPI = (() => {
  const BASE = window.TASTEFLOW_API_BASE;
  const key = (role) => `tasteflow.token.${role}`;
  const getToken = (role) => sessionStorage.getItem(key(role));
  const setToken = (role, t) => sessionStorage.setItem(key(role), t);
  const clearToken = (role) => sessionStorage.removeItem(key(role));
  // The owner may do everything the kitchen can, so an owner token also works for kitchen routes.
  const tokenFor = (role) => getToken(role) || (role === "kitchen" ? getToken("owner") : null);
  const currentPage = () => (location.pathname.split("/").pop() || "index.html") + location.search;

  function redirect(url) { (window.__tfRedirect || ((u) => location.replace(u)))(url); }
  function redirectToLogin(role) { redirect(`login.html?role=${role}&next=${encodeURIComponent(currentPage())}`); }

  async function request(url, options = {}, role = null) {
    const full = url.startsWith("http") ? url : BASE + url;
    const headers = { ...(options.headers || {}) };
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const token = role && tokenFor(role);
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(full, { ...options, headers });
    if (response.status === 401 && role) {
      clearToken(role); if (role === "kitchen") clearToken("owner");
      redirectToLogin(role);
      const err = new Error("Please sign in to continue."); err.status = 401; throw err;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => (d.msg || "").replace(/^Value error, /, "")).join("; ") : data.detail;
      const error = new Error((typeof detail === "string" ? detail : JSON.stringify(detail || data)) || `Request failed: HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  return { BASE, request, getToken, setToken, clearToken, tokenFor, redirect, redirectToLogin };
})();
