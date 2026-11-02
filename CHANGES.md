# Changes
## v5 (this release): suggested commits
1. `feat(roles): staff login page, page guards, role-specific navigation; guests never see staff links`
2. `feat(menu): owner Menu Manager (add/edit/archive/restore dishes) + /api/owner/menu`
3. `fix(init_db): never overwrite owner edits (insert-only; --reset-menu to reset)`
4. `feat(voice): rebuilt voice engine (voice-core.js) with diagnostics, robust restart, chunked speech, clear errors`
5. `feat(site): customer assistant page, menu page uses the new assistant/voice; old scripts moved to legacy/`
6. `fix: remove debug console logging from menu.js; fatal mic error message no longer overwritten`
7. `test: 16 backend tests (147 total) + headless role/menu/voice checks`
## v4 (this release): suggested commits
1. `feat(analytics): command-center engine (pulse, heatmap, forecast, alerts, menu engineering, combos, floor, activity, briefing)`
2. `feat(simulation): rush simulator (repeatable queue simulation + stations needed)`
3. `feat(copilot): plain-language business questions answered by audited analytics functions`
4. `feat(nlu): Devanagari Hindi normaliser for voice input`
5. `feat(agents): add-on suggestions from real market-basket statistics; owner analytics via copilot`
6. `feat(frontend): command.html (Command Center) and voice.html (Voice Studio)`
7. `fix(frontend): KPI formatter crash found by headless test`
8. `test: 27 new tests (131 total)`
## v3 (this release): suggested commits
1. `feat(db): order tracking, status events, feedback, stock, order type/table/notes; additive migration`
2. `feat(orders): tracking code + ETA at placement, stock reservation/restore, single set_status()`
3. `feat(tracking): public /api/track (countdown data, delay detection, cancel, feedback)`
4. `feat(agents): Order Tracking, Feedback & Recovery, Inventory agents; reorder, dine-in/table/notes intents`
5. `feat(kitchen): board endpoint, stale-order handling, late-order counts`
6. `feat(ops): measured kitchen speed, feedback summary, inventory summary, owner endpoints`
7. `feat(frontend): track.html, kitchen board, console live tracker + staff panels`
8. `feat(demo): seed_demo.py (labelled simulated data)`
9. `test: 18 new tests (104 total)`
## v2
Auth, config, sessions, multi-agent orchestrator, Agent Console, test isolation (see git history).
## Breaking changes
- Orders now include `tracking_code`, `eta_minutes`, `order_type`, `table_number`, `notes` (additive).
- `kitchen.html` is now the board; the old page is `kitchen-classic.html`.
