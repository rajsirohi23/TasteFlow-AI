"use strict";
/* TasteFlowVoice: a small, defensive wrapper around the browser's speech APIs.
   Fixes the usual causes of "voice doesn't work":
   - a fresh recognizer per utterance (non-continuous) with auto-restart and back-off
   - clear, actionable messages for every error code (blocked mic, no mic, no internet, ...)
   - TTS voices that load late, long text split into sentences (Chrome stops long utterances)
   - half-duplex by default so the assistant never "hears itself"
   - diagnose(): checks the page address, mic permission, speech service, voices and the server */
window.TasteFlowVoice = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = "speechSynthesis" in window ? window.speechSynthesis : null;

  const ERRORS = {
    "not-allowed": { fatal: true, message: "The microphone is blocked. Click the lock/camera icon in the address bar, allow the microphone, then tap the orb again." },
    "service-not-allowed": { fatal: true, message: "This browser blocked speech recognition. Use Chrome or Edge and allow the microphone." },
    "audio-capture": { fatal: true, message: "No microphone was found. Plug one in or check your system sound settings." },
    "language-not-supported": { fatal: true, message: "This browser doesn't support recognition for the selected language. Try English (India) or type instead." },
    "network": { fatal: false, message: "The speech service couldn't be reached. Chrome sends audio to an online service, so check your internet connection." },
  };
  const explainError = (code) => ERRORS[code] || { fatal: false, message: `Speech recognition problem (${code}). Trying again…` };

  // ---------------------------------------------------------------- voices + speaking
  let voiceCache = [];
  function loadVoices() {
    return new Promise((resolve) => {
      if (!synth) return resolve([]);
      const have = synth.getVoices();
      if (have.length) { voiceCache = have; return resolve(have); }
      const t = setTimeout(() => resolve((voiceCache = synth.getVoices())), 1500);
      synth.addEventListener("voiceschanged", () => { clearTimeout(t); resolve((voiceCache = synth.getVoices())); }, { once: true });
    });
  }
  function pickVoice(voices, lang) {
    const l = lang.toLowerCase(), p = l.slice(0, 2);
    return voices.find((v) => v.lang.toLowerCase().replace("_", "-") === l) || voices.find((v) => v.lang.toLowerCase().startsWith(p)) || null;
  }
  const cleanForSpeech = (t) => t.replace(/₹\s?([\d,]+)/g, "$1 rupees").replace(/(\d+)\s×\s/g, "$1 of ").replace(/#(\d+)/g, "number $1")
    .replace(/[“”"*_`]/g, "").replace(/·|•/g, ",").replace(/→/g, "to").replace(/\s+/g, " ").trim();
  function chunk(text, max = 170) {
    const sentences = text.match(/[^.!?।]+[.!?।]*\s*/g) || [text], out = [];
    let cur = "";
    for (const s of sentences) { if ((cur + s).length > max && cur) { out.push(cur.trim()); cur = s; } else cur += s; }
    if (cur.trim()) out.push(cur.trim());
    return out.flatMap((c) => (c.length > max * 1.6 ? c.match(new RegExp(`.{1,${max}}(\\s|$)`, "g")) || [c] : [c]));
  }

  function createSpeaker() {
    let id = 0, speaking = false;
    return {
      get speaking() { return speaking; },
      /** Browsers only allow speech after a user gesture. Call once from a click. */
      unlock() { if (!synth) return; try { const u = new SpeechSynthesisUtterance(" "); u.volume = 0; synth.speak(u); } catch { /* ignore */ } },
      cancel() { id++; speaking = false; if (synth) synth.cancel(); },
      async voiceInfo(lang) { const v = pickVoice(await loadVoices(), lang); return { voice: v, exact: !!v && v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()) }; },
      /** Resolves when finished or cancelled. Never rejects. */
      async speak(text, { lang = "en-IN", rate = 1, onStart } = {}) {
        if (!synth) return;
        const mine = ++id; synth.cancel(); speaking = true;
        const voices = await loadVoices();
        const voice = pickVoice(voices, lang) || pickVoice(voices, "en-IN") || pickVoice(voices, "en");
        const parts = chunk(cleanForSpeech(text));
        let first = true;
        for (const part of parts) {
          if (id !== mine) return;
          await new Promise((resolve) => {
            const u = new SpeechSynthesisUtterance(part);
            if (voice) { u.voice = voice; u.lang = voice.lang; } else u.lang = "en-IN";
            u.rate = rate;
            const guard = setTimeout(resolve, 3000 + part.length * 130);   // never hang if the browser drops "end"
            u.onstart = () => { if (first) { first = false; onStart && onStart(); } };
            u.onend = u.onerror = () => { clearTimeout(guard); resolve(); };
            synth.speak(u);
          });
        }
        if (id === mine) speaking = false;
      },
    };
  }

  // ---------------------------------------------------------------- listening
  function createListener({ getLang, onInterim, onFinal, onState, onNotice }) {
    let wanted = false, paused = false, running = false, rec = null, timer = null, soft = 0, hard = 0;
    function begin() {
      if (!SR || !wanted || paused || running) return;
      rec = new SR();
      rec.lang = getLang(); rec.continuous = false; rec.interimResults = true; rec.maxAlternatives = 1;
      let heard = false;
      rec.onstart = () => { running = true; onState("listening"); };
      rec.onresult = (e) => {
        heard = true; soft = 0; hard = 0;
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) onFinal(r[0].transcript.trim(), r[0].confidence); else onInterim(r[0].transcript);
        }
      };
      rec.onerror = (e) => {
        if (e.error === "no-speech") { soft++; return; }
        if (e.error === "aborted") return;
        const info = explainError(e.error);
        if (info.fatal || ++hard >= 3) { wanted = false; onNotice(info.message, true); onState("idle"); } else onNotice(info.message, false);
      };
      rec.onend = () => {
        running = false;
        if (!wanted || paused) return;
        if (soft >= 6) { wanted = false; onNotice("I stopped listening after a minute of silence. Tap the orb to continue.", false); onState("idle"); return; }
        clearTimeout(timer); timer = setTimeout(begin, heard ? 120 : 400);
      };
      try { rec.start(); } catch { running = false; clearTimeout(timer); timer = setTimeout(begin, 600); }
    }
    return {
      get wanted() { return wanted; }, get paused() { return paused; },
      start() { wanted = true; paused = false; soft = 0; hard = 0; begin(); },
      stop() { wanted = false; paused = false; clearTimeout(timer); try { rec && rec.abort(); } catch { /* ignore */ } running = false; },
      pause() { paused = true; clearTimeout(timer); try { rec && rec.abort(); } catch { /* ignore */ } running = false; },
      resume() { paused = false; if (wanted) begin(); },
    };
  }

  // ---------------------------------------------------------------- diagnostics
  async function diagnose(apiBase) {
    const out = [];
    const add = (label, ok, detail, fix) => out.push({ label, ok, detail, fix: fix || "" });
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
    if (location.protocol === "file:") add("Page address", false, "Opened as a file", "Serve the site instead: run  python3 -m http.server 5500  in the frontend folder and open http://localhost:5500/voice.html");
    else if (window.isSecureContext || local) add("Page address", true, location.origin);
    else add("Page address", false, location.origin + " is not secure", "Browsers only allow the microphone on https:// or http://localhost.");
    add("Speech recognition", !!SR, SR ? "available" : "not available in this browser", SR ? "" : "Use Chrome or Edge (desktop or Android). Typing still works.");
    let micOk = false;
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try { const s = await navigator.mediaDevices.getUserMedia({ audio: true }); s.getTracks().forEach((t) => t.stop()); micOk = true; add("Microphone", true, "permission granted"); }
      catch (e) { add("Microphone", false, e.name === "NotAllowedError" ? "permission blocked" : e.name === "NotFoundError" ? "no microphone found" : e.name, e.name === "NotAllowedError" ? "Click the lock icon in the address bar → allow Microphone → reload." : "Check that a microphone is connected and not used by another app."); }
    } else add("Microphone", false, "not accessible", "Needs https:// or http://localhost.");
    add("Internet (speech service)", navigator.onLine, navigator.onLine ? "online" : "offline", navigator.onLine ? "" : "Chrome's speech recognition needs an internet connection.");
    const voices = await loadVoices();
    if (!synth) add("Voice output", false, "not supported", "Replies will be shown as text only.");
    else {
      add("Voice output", voices.length > 0, `${voices.length} voice(s) installed`, voices.length ? "" : "No system voices found; replies will be silent.");
      const has = (l) => !!pickVoice(voices, l) && pickVoice(voices, l).lang.toLowerCase().startsWith(l.slice(0, 2));
      add("English voice", has("en-IN") || has("en-US"), has("en-IN") ? "English (India)" : has("en-US") ? "English (US)" : "none");
      add("Hindi voice", has("hi-IN"), has("hi-IN") ? "installed" : "not installed (Hindi will be understood but answered in English)", has("hi-IN") ? "" : "Optional: install a Hindi voice in your OS speech settings.");
    }
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 4000);
      const r = await fetch(`${apiBase}/health`, { signal: ctl.signal }); clearTimeout(t);
      add("TasteFlow server", r.ok, r.ok ? apiBase : `HTTP ${r.status}`, r.ok ? "" : "Check the backend.");
    } catch { add("TasteFlow server", false, `cannot reach ${apiBase}`, "Start the backend:  uvicorn main:app --reload"); }
    return { checks: out, micOk };
  }

  /** Listen once for up to `ms` and report what was heard (or why not). */
  function liveTest(lang, ms = 7000) {
    return new Promise((resolve) => {
      if (!SR) return resolve({ error: "Speech recognition isn't available in this browser." });
      const r = new SR(); r.lang = lang; r.interimResults = false; let done = false;
      const finish = (v) => { if (!done) { done = true; try { r.abort(); } catch { /* ignore */ } resolve(v); } };
      r.onresult = (e) => finish({ transcript: e.results[0][0].transcript });
      r.onerror = (e) => finish({ error: e.error === "no-speech" ? "I didn't hear anything. Is the right microphone selected?" : explainError(e.error).message });
      r.onend = () => finish({ error: "Nothing was recognised." });
      setTimeout(() => finish({ error: "Timed out without hearing speech." }), ms);
      try { r.start(); } catch (e) { finish({ error: "Couldn't start listening: " + e.message }); }
    });
  }

  return { supported: !!SR, ttsSupported: !!synth, createSpeaker, createListener, diagnose, liveTest, loadVoices, explainError, chunk, cleanForSpeech };
})();
