# CLAUDE.md — read this before changing anything

This bot watches the owner's Polymarket positions, alerts in Telegram, sells
on confirmation, and runs paper-trading experiments. It is deployed on Render
from `monitor-branch`: **every merge into `monitor-branch` goes live within
minutes**, with real money behind it.

Read `LESSONS.md` too: it records past mistakes and what was learned from
trading results. Add to it when you learn something (see "Lessons" below).

## Hard rules

1. **Never rewrite `monitor-branch`.** No force-push, no reset, no rebuilding
   it from an older commit. On Oct 7 a session rewrote it from an Oct 3 commit
   and silently deleted a week of merged work (PRs #1–#8); the dashboard went
   empty for two days. Work on your own branch and open a pull request into
   `monitor-branch`; the owner merges.
2. **One session at a time.** Before starting, read the latest commits on
   `monitor-branch` (`git log origin/monitor-branch -10`) and build on them.
   Never replace a module wholesale because your copy is older.
3. **Never change an experiment's rules while it runs.** The paper tests
   (Bitcoin model, football hybrid stop-loss, stop-alert review) compare
   results over weeks; changing entry or exit rules mid-way mixes two
   experiments into one meaningless number. Add a new variant instead
   (see `VARIANTS` in `match_strategy.py`) or start a new section
   (like `strict_test` in `strict_strategy.py`).
4. **Money and keys.**
   - The bot only sells, never buys, and only after the owner taps
     "تأكيد البيع" in Telegram. Do not add automatic selling or buying
     without the owner's explicit decision in that session.
     One exception, decided by the owner on 2026-10-23: `auto_stop.py` sells
     a covered football position at its −20% stop by itself, only when
     `AUTO_STOP=1` is set in Render. It never buys and never sells at the
     take-profit.
   - Private keys live only in Render environment variables
     (`TRADING_PRIVATE_KEY`, `TRADING_PRIVATE_KEY_2`). Never ask for a key or
     the 12 words in chat, never log or return them; errors go through
     `trading._redact`.
   - Public pages (`/api/positions`, `/api/alerts/status`, `/api/paper`) must
     never show keys or balances.
   - No VPN or geoblock workarounds.
5. **Tests before every push**, and they must not touch the network:

   ```bash
   python -m unittest test_alerts.py test_trading.py test_paper.py test_exposure.py test_match.py test_alert_memory.py test_strict.py test_auto_stop.py test_restore.py test_live.py
   ```

   A suite that suddenly takes seconds is calling the internet: mock it.
   If a change breaks tests that were green, fix them in the same PR.
6. **Evidence before conclusions.** No rule, threshold or strategy is "proven"
   from fewer than 30 independent settled cases. Say so when a sample is small.

## Where things are

| What | Where |
| - | - |
| Monitor, alerts, generic stop/target levels | `polymarket_monitor.py`, `positions.py`, `alerts.py` |
| Selling (bot wallet + optional second wallet) | `trading.py`, `telegram_actions.py` |
| Ledger loop (every minute), Bitcoin paper model | `paper_trading.py`, ledger stored by `paper_store.py` as a file pinned in Telegram |
| Football hybrid stop-loss: shadow test + alerts on real positions | `match_strategy.py` |
| Strategy 3.0 "الميزان الصارم" paper test; ±20% alerts on real positions | `strict_strategy.py` (alerts in `match_strategy.position_alerts`) |
| Automatic sale at the stop-loss (`AUTO_STOP=1`) | `auto_stop.py` |
| Live prices and scores (WebSockets): instant stops, goal-vs-price timing | `live_feed.py` (`LIVE_FEED=0` turns it off) |
| Wiping paper trades (archive first, then clear) | `paper_trading.RESET_ID`, `wipe` |
| Restoring the ledger lost on Oct 23 (once) | `paper_trading.restore`, `restore/` |
| Stop/target alert review (sell at alert vs hold) | `stop_review.py` |
| Position size alert | `exposure.py` |
| Alert cooldowns kept across restarts | `alert_memory.py` |
| Paper results as JSON | `GET /api/paper` |

## Lessons

When a result or a mistake teaches something, add a dated entry to
`LESSONS.md`: what happened, why, what changes. Trading lessons need data
(sample size, numbers); engineering lessons can be written right away.
