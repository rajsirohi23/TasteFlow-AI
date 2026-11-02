"use strict";
/* Voice Studio: hands-free ordering through the same multi-agent engine as the chat (/api/chat).
   Built on TasteFlowVoice (js/voice-core.js). English, Hindi (Devanagari) and Hinglish input;
   a wake word; a live waveform; "stop" to interrupt; spoken order-ready announcements. */
(() => {
  const V = window.TasteFlowVoice;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const SESSION = "tasteflow.voice.session";
  const WAKE = /\b(hey|hi|ok|okay|hello)\s*taste\s*flow\b|टेस्ट\s*फ्लो/i;
  const INTERRUPT = /^(stop|wait|cancel|quiet|ruko|रुको|बस|चुप)\b/i;
  const speaker = V.createSpeaker();
  let fatalMsg = "", sessionId = sessionStorage.getItem(SESSION), busy = false, awakeUntil = 0, tracker = null, analyser = null, audio = null, data = null;

  const setOrb = (s, text) => { $("orb").dataset.state = s; $("orb-icon").textContent = { idle: "🎤", listening: "👂", thinking: "💭", speaking: "🔊" }[s]; if (text) $("status").textContent = text; };
  const log = (text, who) => { const m = el("div", `msg ${who}`, text); m.append(el("time", "", new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))); $("log").append(m); $("log").scrollTop = $("log").scrollHeight; };
  const ownerHeaders = () => { const t = TasteFlowAPI.getToken("owner"); return t ? { Authorization: `Bearer ${t}` } : {}; };
  const idleText = () => ($("wake").checked ? "Say “Hey TasteFlow …”" : "Listening… just speak");

  const listener = V.createListener({
    getLang: () => $("lang").value,
    onInterim: (t) => { if (!speaker.speaking) $("interim").textContent = t; },
    onFinal: (t) => handleHeard(t),
    onState: (s) => { if (s === "listening" && !busy && !speaker.speaking) setOrb("listening", idleText()); if (s === "idle" && !busy && !speaker.speaking) setOrb("idle", fatalMsg || "Tap the orb and start talking"); },
    onNotice: (msg, fatal) => { log(msg, "bot"); if (fatal) { fatalMsg = msg; setOrb("idle", msg); } },
  });

  // ---------------------------------------------------------------- waveform (visual only)
  async function startAudio() {
    if (audio || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      audio = new (window.AudioContext || window.webkitAudioContext)(); analyser = audio.createAnalyser(); analyser.fftSize = 128;
      audio.createMediaStreamSource(stream).connect(analyser); data = new Uint8Array(analyser.frequencyBinCount); draw();
    } catch { /* the waveform is optional */ }
  }
  function draw() {
    const c = $("wave"), g = c.getContext && c.getContext("2d"); if (!g || !analyser) return;
    requestAnimationFrame(draw); analyser.getByteFrequencyData(data);
    g.clearRect(0, 0, c.width, c.height); const cx = c.width / 2, cy = c.height / 2, R = c.width * 0.31, n = data.length;
    const col = { listening: "240,138,75", speaking: "167,139,250", thinking: "90,169,255" }[$("orb").dataset.state] || "62,207,142";
    for (let i = 0; i < n; i++) {
      const v = data[i] / 255, a = (i / n) * Math.PI * 2 - Math.PI / 2, len = 6 + v * 70;
      g.strokeStyle = `rgba(${col},${0.35 + v * 0.65})`; g.lineWidth = 4; g.lineCap = "round"; g.beginPath();
      g.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); g.lineTo(cx + Math.cos(a) * (R + len), cy + Math.sin(a) * (R + len)); g.stroke();
    }
  }

  // ---------------------------------------------------------------- hearing -> agents -> speaking
  function handleHeard(text) {
    if (!text) return;
    if (speaker.speaking) {                       // we may be listening while talking only if "say stop" is on
      if ($("barge").checked && INTERRUPT.test(text)) { speaker.cancel(); setOrb("listening", idleText()); }
      return;
    }
    if (busy) return;
    if (/\b(stop listening|बंद करो)\b/i.test(text)) { stopAll("Stopped. Tap the orb to talk again."); return; }
    if ($("wake").checked) {
      if (WAKE.test(text)) { awakeUntil = Date.now() + 12000; text = text.replace(WAKE, "").replace(/^[\s,.:!-]+/, "").trim(); if (!text) { reply("Yes? I'm listening."); return; } }
      else if (Date.now() > awakeUntil) { $("interim").textContent = ""; return; }   // not addressed to us
    }
    send(text);
  }

  async function reply(text) {
    log(text, "bot"); setOrb("speaking", "Speaking…");
    if (!$("barge").checked) listener.pause();     // half-duplex: never hear ourselves
    await speaker.speak(text, { lang: $("lang").value, rate: Number($("rate").value) });
    afterSpeech();
  }
  function afterSpeech() {
    busy = false;
    if (listener.wanted && $("hands").checked) { awakeUntil = Date.now() + 12000; setOrb("listening", idleText()); listener.resume(); }
    else { listener.stop(); setOrb("idle", "Tap the orb to talk"); }
  }
  function stopAll(msg) { listener.stop(); speaker.cancel(); busy = false; setOrb("idle", msg || "Stopped."); }

  async function send(text) {
    busy = true; $("interim").textContent = ""; log(text, "you"); listener.pause(); setOrb("thinking", "Thinking…");
    try {
      const ctl = new AbortController(); const timeout = setTimeout(() => ctl.abort(), 15000);
      const r = await TasteFlowAPI.request("/api/chat", { method: "POST", headers: ownerHeaders(), body: JSON.stringify({ session_id: sessionId, message: text }), signal: ctl.signal });
      clearTimeout(timeout);
      sessionId = r.session_id; sessionStorage.setItem(SESSION, sessionId); renderSide(r);
      if (r.intent === "confirm_yes" && r.order && r.order.tracking_code) startTracker(r.order.tracking_code);
      await reply(r.reply);
    } catch (err) {
      const msg = err.name === "AbortError" ? "The server took too long to answer. Please try again." : err.message === "Failed to fetch" ? "I can't reach the server. Please check that the backend is running." : err.message;
      await reply(msg);
    }
  }
  function renderSide(r) {
    const cart = $("cart"); cart.replaceChildren();
    if (!r.cart || !r.cart.lines.length) cart.append(el("span", "muted", "Empty"));
    else { r.cart.lines.forEach((l) => { const d = el("div", "line"); d.append(el("span", "", `${l.quantity} × ${l.name}`), el("span", "", "₹" + l.subtotal)); cart.append(d); }); const t = el("div", "line"); t.append(el("b", "", "Total"), el("b", "", "₹" + r.cart.total_amount)); cart.append(t); }
    const ag = $("agents"); ag.replaceChildren(); r.agents_used.forEach((a) => ag.append(el("span", "", a.label))); if (!r.agents_used.length) ag.append(el("span", "muted", "–"));
  }

  function startTracker(code) {
    if (tracker) clearInterval(tracker); let last = null;
    const poll = async () => {
      try {
        const d = await TasteFlowAPI.request(`/api/track/${code}`);
        const msg = { preparing: "Good news, the kitchen has started cooking your order.", ready: "Your order is ready for pickup!", completed: "Enjoy your meal!" }[d.status];
        if (last && last !== d.status && msg) { log(msg, "bot"); if (!busy && !speaker.speaking) speaker.speak(msg, { lang: $("lang").value, rate: Number($("rate").value) }); }
        last = d.status; if (["completed", "cancelled"].includes(d.status)) { clearInterval(tracker); tracker = null; }
      } catch { /* retry on the next tick */ }
    };
    tracker = setInterval(() => { if (!document.hidden) poll(); }, 6000); poll();
  }

  // ---------------------------------------------------------------- controls
  async function toggleOrb() {
    speaker.unlock();                               // browsers require a user gesture before speech
    if (speaker.speaking) { speaker.cancel(); afterSpeech(); return; }
    if (listener.wanted) { stopAll("Stopped. Tap the orb to talk again."); return; }
    if (!V.supported) { setOrb("idle", "Speech recognition isn't supported in this browser. Type below, or open the mic check."); return; }
    fatalMsg = ""; startAudio(); listener.start(); setOrb("listening", idleText());
  }
  $("orb").addEventListener("click", toggleOrb);
  $("stop-talk").addEventListener("click", () => { speaker.cancel(); if (busy) return; afterSpeech(); });
  $("typed").addEventListener("submit", (e) => { e.preventDefault(); speaker.unlock(); const v = $("typed-in").value.trim(); if (v && !busy) { $("typed-in").value = ""; send(v); } });
  $("lang").addEventListener("change", async () => {
    if (listener.wanted) { listener.stop(); listener.start(); }
    const info = await speaker.voiceInfo($("lang").value);
    if ($("lang").value === "hi-IN" && !info.exact) log("No Hindi voice is installed on this device, so I'll understand Hindi but answer in English.", "bot");
  });

  // ---------------------------------------------------------------- mic & voice check
  $("diag-btn").addEventListener("click", async () => {
    const box = $("diag"); box.hidden = false; box.replaceChildren(el("p", "muted", "Checking your setup…"));
    const { checks } = await V.diagnose(TasteFlowAPI.BASE);
    box.replaceChildren();
    checks.forEach((c) => {
      const row = el("div", "row"); row.append(el("span", c.ok ? "ok" : (c.label === "Hindi voice" ? "warn" : "no"), c.ok ? "✓" : (c.label === "Hindi voice" ? "!" : "✗")));
      const t = el("div"); t.append(el("b", "", c.label + ": "), document.createTextNode(c.detail)); if (c.fix) t.append(el("small", "fix", c.fix)); row.append(t); box.append(row);
    });
    const bad = checks.filter((c) => !c.ok && c.label !== "Hindi voice").length;
    box.append(el("p", bad ? "no" : "ok", bad ? `${bad} problem(s) found. Fix the items marked ✗ above, then reload.` : "Everything looks good. Try the live test:"));
    const test = el("button", "chip", "🎙 Live mic test (say “hello”)"); test.type = "button";
    const result = el("p", "muted", "");
    test.addEventListener("click", async () => { result.textContent = "Listening for 7 seconds… say something."; const r = await V.liveTest($("lang").value); result.textContent = r.transcript ? `I heard: “${r.transcript}” ✓` : r.error; });
    box.append(test, result);
  });

  [["Veg under 300, not too spicy", "vegetarian under 300, not too spicy"], ["शाकाहारी खाना 300 के अंदर", "शाकाहारी खाना 300 के अंदर"], ["mujhe kuch spicy veg chahiye 250 ke andar", "mujhe kuch spicy veg chahiye 250 ke andar"],
   ["Dine in table 4", "dine in table 4"], ["Place my order", "place my order"], ["How long will it take?", "how long will my order take"], ["ऑर्डर कहाँ है", "मेरा ऑर्डर कहाँ है"]]
    .forEach(([label, msg]) => { const b = el("button", "", label); b.type = "button"; b.addEventListener("click", () => { speaker.unlock(); if (!busy) send(msg); }); $("try").append(b); });
  if (!V.supported) $("unsupported").hidden = false;
  if (location.protocol === "file:") { $("unsupported").hidden = false; $("unsupported").textContent = "This page was opened as a file, so the browser will block the microphone. Serve the site with  python3 -m http.server 5500  and open http://localhost:5500/voice.html"; }
  log(TasteFlowAPI.getToken("owner") ? "Owner mode is on: you can also ask business questions, e.g. “top dishes this week”." : "Hi! Tap the orb and just talk. English, हिन्दी and Hinglish all work. Tap the orb or say “stop” to interrupt me. If anything doesn't work, press “Check my mic & voice”.", "bot");
})();
