# TasteFlow AI: multi-agent restaurant operating system (v5)

## Run it (macOS / Linux)
```bash
# Terminal 1: backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then set OWNER_PIN, KITCHEN_PIN, AUTH_SECRET
python init_db.py                 # loads the menu; safely upgrades an existing tasteflow.db (keeps your orders)
python seed_demo.py               # OPTIONAL: adds clearly-labelled DEMO history (remove later with --clear)
uvicorn main:app --reload         # API: http://127.0.0.1:8000   docs: /docs

# Terminal 2: frontend
cd frontend && python3 -m http.server 5500
```
Backend address for the frontend lives in ONE file: `frontend/js/config.js`.
Tests: `cd backend && pytest` (147 tests, isolated in-memory DB; never touches your real data).
Demo PINs if `.env` has none: owner `owner-demo`, kitchen `kitchen-demo`.

## Who can see what
| Area | Pages | Who |
|---|---|---|
| **Guests** (no login) | `index.html` menu + cart · `assistant.html` AI chat · `voice.html` Voice Studio · `track.html` live order tracking | everyone |
| **Kitchen staff** | `kitchen.html` kitchen board | kitchen PIN (owner can open it too) |
| **Owner** | `command.html` Command Center · `menu-admin.html` Menu Manager · `agents.html` Agent Console · `owner.html` classic dashboard | owner PIN only |

- Staff sign in at **`login.html`** (a discreet "Staff login" link is in the menu page footer). Guests never see staff links.
- Kitchen staff are refused on owner pages (sent back to sign-in); forged or expired tokens are rejected.
- The website hides pages for tidiness, but the real protection is on the **server**: every staff API checks the token, so typing a URL or calling the API directly does not bypass it.
- `kitchen-classic.html` (your original kitchen page) is kept; the old menu-page assistant scripts moved to `frontend/legacy/` (unused).

## Owner: managing the menu
Sign in as owner, open **Menu Manager**: add a dish (name, price, category, description, ingredients, dietary tags, spice, prep time, stock, cost, image URL, with a live "what guests will see" preview), edit any dish, mark unavailable, **remove** (archived, so past orders keep working) and **restore**. New dishes appear on the guest menu, in the chat/voice agents and at checkout immediately.
`python init_db.py` no longer overwrites your edits (it only inserts missing dishes). Use `python init_db.py --reset-menu` to deliberately restore demo values.

## Voice troubleshooting (open Voice Studio -> "Check my mic & voice")
The check tests: page address (must be `http://localhost` or https, **not** a double-clicked file), browser speech recognition (Chrome/Edge), microphone permission, internet (Chrome's recognition is online), installed voices (English/Hindi) and the server, with a fix for each failure, plus a 7-second live mic test.

## Pages (all)
| Page | What it does |
|---|---|
| `index.html` | Menu + cart. After checkout you are taken to live tracking |
| `track.html?code=XXXXXXXX` | **Live order tracking**: countdown ring, "N orders ahead", progress steps, delay detection, cancel (while pending), star rating |
| `agents.html` | **Agent Console**: chat + 8 agents working + live trace + session memory; in-chat live tracking card; staff panels (insights, measured kitchen speed, feedback follow-ups, stock with +10 restock) |
| `kitchen.html` | **Kitchen display board**: New / Preparing / Ready columns, per-order timers, late + stale highlighting, workload meter, one-tap status, new-order sound |
| `command.html` | **Owner Command Center** (owner PIN): live KPIs, smart alerts, floor plan, order heatmap, 24 h demand forecast with staffing advice, menu-engineering matrix, "bought together" combos, **Rush Simulator**, **Business Copilot** (ask in plain words, voice optional), morning brief read aloud |
| `voice.html` | **Voice Studio**: hands-free ordering in English / हिन्दी / Hinglish, "Hey TasteFlow" wake word, live waveform, interrupt the assistant mid-sentence, spoken "your order is ready", owner voice analytics |
| `owner.html` | Original owner dashboard (PIN) |
| `kitchen-classic.html` | Your original kitchen page (kept) |

## The eight agents
Supervisor · Smart Menu & Nutrition · Intelligent Order · Kitchen Coordination · Restaurant Intelligence (staff) ·
**Order Tracking** · **Feedback & Service Recovery** · **Inventory** (staff). Each action is a recorded step you can inspect.

## New in v4 ("wow" release)
- **Command Center** (see table) with 10 new owner endpoints, all computed from real rows.
- **Business Copilot**: no LLM writes SQL. Questions map to audited analytics functions; each answer shows its basis and equals raw database math (tests prove it).
- **Rush Simulator**: seeded queue simulation of the kitchen ("40 orders in 10 min with 3 stations?") + how many stations you would need. Repeatable; labelled a scenario, not a prediction.
- **Smart alerts**: late orders, busy kitchen, sold-out top sellers, rating dip, revenue behind pace, unresolved feedback, stale tickets.
- **Menu engineering** (stars / workhorses / puzzles / dogs): uses price until you set cost prices, then true margin.
- **Market-basket combos**: "55% of guests who ordered X also ordered Y". The chat's add-on suggestion now cites these real statistics.
- **Hindi (Devanagari) understanding** in the agents (for voice): phrases like "शाकाहारी खाना 300 के अंदर", "मेरा ऑर्डर कहाँ है".
- **Voice Studio** (browser speech APIs; needs Chrome/Edge). Typing always works.

## New in v3
- Order tracking by an unguessable code; promised ETA stored at placement; delay is reported honestly, never hidden.
- Real timing data: every status change is timestamped, so insights show *measured* time-to-ready, not guesses.
- Stock tracking (optional per dish): decrements on order, blocks overselling, auto sold-out, restored on cancel.
- Feedback: 1-5 stars + comment, complaint topics, low scores flagged for manager follow-up (resolvable).
- Dine-in / takeaway, table number, special notes ("note: extra crispy"), "order the same again".
- Stale-order handling: abandoned tickets no longer inflate wait estimates; the board flags them.
- `seed_demo.py`: simulated history, flagged `is_demo`, announced in insights, removable with `--clear`.

## Honest limits (know these for your viva)
- Chat understanding is rule-based (English + basic Hinglish), deterministic and tested. No LLM is in the chat loop.
- LangGraph is not used yet; the orchestrator is plain Python with the same node structure.
- Demo history is simulated (including the "bought together" habits). Command Center charts on demo data show the feature, not real guests.
- Wait times are estimates from configurable prep minutes (`config.py`); "measured" figures only exist once real
  orders move through the kitchen board. Demo data is simulated.
- "High-protein" is judged from ingredient keywords (no nutrition values recorded). No verified allergen data.
- Voice Studio relies on the browser's speech recognition/synthesis (Chromium). The conversation logic (hands-free loop, wake word, pausing while speaking, sentence chunking, error messages) is tested with simulated speech APIs, but I could not test a real microphone or speakers. I could not test real microphones or speakers here: the speech parts (wake word, waveform, interruption) are UNVERIFIED on a real device; the language handling behind them is tested. Replies are spoken in English; Hindi *input* is understood, Hindi *replies* are not generated.
- Tracking updates by polling (5-6 s), not websockets. Cancel-by-numeric-id on the legacy API is still public.
- I could not open a real browser; pages were verified in a headless DOM (jsdom). Please click through them.
# TasteFlow-AI


### 4. Open the Pages

Once the frontend server is running, open the following pages in your browser:

| **Page** | **Address** | **Sign-in Required** |
|---|---|---|
| **Menu & Cart** | [http://127.0.0.1:5500/index.html](http://127.0.0.1:5500/index.html) | None |
| **Agent Console** | [http://127.0.0.1:5500/agents.html](http://127.0.0.1:5500/agents.html) | None (Click **Staff Sign-in** to access owner insights) |
| **Kitchen Dashboard** | [http://127.0.0.1:5500/kitchen.html](http://127.0.0.1:5500/kitchen.html) | Kitchen PIN |
| **Owner Dashboard** | [http://127.0.0.1:5500/owner.html](http://127.0.0.1:5500/owner.html) | Owner PIN |

**Note:** Make sure your backend API and frontend development server are running before accessing these pages.
