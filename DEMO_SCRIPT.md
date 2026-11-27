# 7-Minute Uncut Demo Script and Verification Checklist

Single take, no cuts. Wi-Fi/Ethernet off from 0:00 and visible on screen. Server running (`uvicorn app:app --host 127.0.0.1 --port 8000`), browser at http://127.0.0.1:8000 with DevTools Network open, a second terminal in the project folder. Scenario: Peak-season replay, stock 60%, crews 40, surge 1x.

| Time | Screen | Say / do |
|---|---|---|
| 0:00-0:35 | Terminal + banner | Say BLUEPINE. `ping -c1 8.8.8.8` fails. Point at `MODE: 100% OFFLINE DETERMINISTIC ENGINE`. |
| 0:35-1:25 | Overview page, then `/app` | Open the overview at `/`, hover a few tiles, then click Open command center. |
| 0:35-1:25 | Dashboard top | 31,320 rows, 60 wards, 5 cities, 2016-01-04 to 2025-12-29. Weekly cases median 0, p90 9, max 41. Forecast origin 2025-06-09, targets 2025-06-23, 06-30, 07-07, from out-of-sample models (holdout MAE 1.07 at h=2 vs 1.80 persistence). Flip to Live once: near-zero in off-season, flip back. |
| 1:25-2:40 | Heatmap + allocation table | Priority formula. Drag stock 100% to 30%, crews 120 to 10: tiles gain red base edges, `CRITICAL DEFICIT` badges show exact shortfalls. Highest-priority wards stay fully supplied. |
| 2:40-3:40 | Bed routing | Set surge 1.5x. Show transfer manifest (same city only), utilization %, unmet beds. Filter to Gazipur to show the city boundary. |
| 3:40-5:00 | Vector simulator | Auto-assign 12 crews. Read crews, cases prevented (weeks 2 to 4), beds freed, saline saved, ROI. Show the 60-ward ROI ranking and the Engine column. Pick 2 crews for one ward and 3 for another, click Simulate my selection. |
| 5:00-5:55 | Dispatch preview | Select CCC_Ward_03: SMS with character count (<= 160), WhatsApp brief, commissioner brief, Print brief (print preview). Select DNCC_Ward_01. Reload: identical text. |
| 5:55-6:40 | Kill-switch | Click **Offline kill-switch and stress test** with Wi-Fi still off. Read the PASS lines: blocked-network run, probe to 8.8.8.8 blocked, identical repeat hash, no cross-city transfers. In terminal: `grep -rEn "https?://" static/` returns nothing. DevTools: only 127.0.0.1. |
| 6:40-7:00 | Terminal | `ls exports/`, `grep -c BLUEPINE README.md`, `grep -n "AI Disclosure" README.md`, `git log --oneline -3` (each contains `version-onsite-final`). |

## Verification checklist

Offline
- [ ] Network off before recording, visible on screen
- [ ] `ping` to external host fails
- [ ] Banner `MODE: 100% OFFLINE DETERMINISTIC ENGINE` visible
- [ ] Stress test: 9 of 9 checks PASS with Wi-Fi off
- [ ] `grep -rEn "https?://" static/` is empty
- [ ] DevTools Network: only 127.0.0.1

Modules
- [ ] Allocation: stock 30%-100% and crews 10-120 both moved; `CRITICAL DEFICIT` with exact shortfalls
- [ ] Bed routing: manifest, city utilization %, unmet beds; no cross-city transfer
- [ ] Simulator: auto-assign and manual selection; cases prevented, beds freed, saline saved, ROI; 60-ward ranking
- [ ] Dispatch: SMS <= 160 chars, WhatsApp brief, printable commissioner brief; reload gives identical text
- [ ] Exports present: `sms_alerts.txt`, `whatsapp_dispatch.md`, `commissioner_brief_CCC_Ward_03.html`, `commissioner_brief_DNCC_Ward_01.html`

Docs and repo
- [ ] `README.md` contains `BLUEPINE` and an `AI Disclosure` section
- [ ] `ARCHITECTURE.md` has equations, data flow, offline guarantees
- [ ] Every commit message contains `version-onsite-final`
- [ ] Recording is one take, 7:00 or less
