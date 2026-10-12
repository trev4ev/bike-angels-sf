# Bike Angels Routing App Plan

Create optimal multi-leg routes for Bay Wheels Bike Angels points from a starting location, accounting for ride duration and walking between stations.

This builds on the existing collector (`bike-angels-sf`), which snapshots station inventory, GBFS status, and Bike Angels rewards into `data/bike_angels.sqlite`.

## Product strategy: private v1 → public tool

**End goal:** a **public** routing tool anyone can use without Lyft Bike login.

Bike Angels reward amounts are **not** in public GBFS — they only come from Lyft’s authenticated inventory/map APIs. A public deployment **cannot** pull that production reward feed (auth, ToS, rate limits, token ownership). So the collector’s job is to gather labeled history so we can **train a model that predicts point amounts from public signals** (station fill, capacity, time-of-day, location, etc.).

| Phase | Who | Reward source | Live inputs |
|---|---|---|---|
| **v1 (now)** | Personal / private | **Production** inventory points (authenticated collector) | GBFS + Lyft rewards API |
| **v2 (public)** | Anyone | **Predicted** pickup/dropoff points (no Lyft auth) | Public GBFS only (+ model) |

Implications:

- Keep the **router interface identical** across phases: it consumes a station feature table with `pickup_points` / `dropoff_points` (real or predicted). Swap the data source, not the optimizer.
- Collection + modeling are first-class product work, not optional polish — they unblock the public tool.
- Never ship personal `tokens.json` or raw authenticated reward scraping in the public app.
- Public UI should label estimates as **predicted** (confidence / uncertainty), not as live Angels map values.
- Optionally keep a private “live mode” for the operator that still uses production data for validation and model drift checks.

## Problem model

Each rewarded leg is:

1. **Walk** from current position → pickup station (needs a bike *and* offers pickup points)
2. **Ride** → dropoff station (needs a dock *and* offers dropoff points)
3. Earn `pickup_points + dropoff_points`
4. Optionally walk to the next pickup

Inputs already collected fit this well: station lat/lon, bikes/docks available, `pickup_points` / `dropoff_points` / `ba_points`, plus 15-minute history once collection has run.

**Optimize for:** net dollar value per minute (or max $ given a time budget), not raw distance — convert points via the rewards catalog, then subtract ride costs (usually $0 on classic bikes).

### Membership & ride costs (assumptions; keep configurable)

Published Lyft Bike / Bay Wheels pricing ([memberships](https://help.lyftbikes.com/hc/en-us/articles/47286633352589-Annual-memberships), [ebike](https://help.lyftbikes.com/hc/en-us/articles/46896915466893-Ebike-pricing), [Bike Angels rewards](https://lyftbikes.com/bike-angels/rewards)):

| Item | Value | Notes |
|---|---|---|
| Annual membership | ~$160–165 / yr | Published **$165/yr**; treat as a config constant |
| Classic bike (member) | **$0** for rides ≤ 45 min | Unlimited classic rides; overage ~$0.17/min after 45 |
| E-bike (member) | **$0.17 / min** | No unlock fee; rounded up per minute |
| Bike Angels eligibility | Members only | Annual (or monthly) membership required |

Default Angel-farming mode: **prefer classic bikes** (free marginal cost). Use e-bikes only when the user opts in or when the expected point value clearly exceeds e-bike spend (hills, long legs, time budget).

### Point → dollar valuation

Rewards live in the app store and as monthly milestones ([overview](https://lyftbikes.com/bike-angels/rewards)). Approximate marginal USD per point:

| Reward path | Cost in points | Cash-equivalent | ≈ $/point |
|---|---|---|---|
| E-bike credit | 10 | $2.00 (~10 min at $0.17/min) | **$0.20** |
| Lyft credit (store) | 10–150 | $2–$30 | **~$0.20** |
| Membership extension | 20 → 1 week (≤4 / month; 4th ≈ 30 days) | annual ÷ 52 ≈ $3.08–$3.17 | **~$0.15–0.16** |
| Monthly Gold (auto) | every 10 pts from 80–200 | $0.15 / point | **$0.15** |
| Monthly Platinum (auto) | every 10 pts above 200 | $0.20 / point | **$0.20** |

**Default planning rate:** use **$0.20 / point** (ebike / Lyft credit) as the optimistic redemption value; optionally show a band using **$0.15 / point** (membership-extension / Gold tier). Lifetime swag (pins, bottle, gloves, backpack) is non-cash — track separately, do not put in the route objective.

Net value of a leg:

```text
expected_usd = expected_points * usd_per_point
  - (bike_type == ebike ? ceil(ride_minutes) * 0.17 : 0)
  - classic_overage_if_any
```

Surface both **points** and **$** in the UI so the user can prefer membership weeks vs Lyft/ebike credit.

### Scoring rules (domain)

Official rules ([points overview](https://lyftbikes.com/bike-angels/points)) match field experience:

**Wrong direction zeros the whole ride.**  
Any ride that **starts at a Drop Off station** or **ends at a Pick Up station** earns **0 points**, regardless of the other end. E-bike rides that do not end at a station also earn 0.

**Neutral stations are allowed.**  
Otherwise you earn **pickup points at start + dropoff points at end**. One end may be neutral (0): e.g. pickup→neutral or neutral→dropoff still pays the non-zero side. Do **not** require both ends to be rewarded — only forbid start@dropoff and end@pickup.

**High-value stations tend to persist across the next refresh.**  
A station offering 3–4 points now is likely to still offer points after the next `:00` / `:15` / `:30` / `:45` tick, usually at a lower value. Multi-leg plans that cross a refresh should not assume mid-route stations go to zero; prefer decaying expected points (e.g. discount next-window legs) over discarding them. Validate/refine this persistence curve from collected snapshots.

## Constraints

| Constraint | Why it matters |
|---|---|
| No start@dropoff / end@pickup | Wrong direction → 0 for the whole ride |
| Neutral OK | One end may be 0; points = sum of both ends |
| Walk time to first pickup + between legs | Often dominates short sessions |
| Ride duration (+ classic 45-min free window) | Core time cost; overage if a single ride exceeds 45 |
| E-bike $0.17/min | Subtract from net $ when not on classic |
| Bike/dock availability | Illegal edges if 0 bikes or 0 docks |
| Optional max walk distance | Avoid absurd long walks to pickups |
| Session time budget (e.g. 30–90 min) | Primary user knob |
| Points refresh (`:00` / `:15` / `:30` / `:45`) | Live values change; high-point stations often persist lower |

Later (from SQLite history): point persistence / decay curves, station fill patterns by hour/weekday.

## Algorithm (phased)

### v1 — Live router on production rewards (private; ship first)

Uses authenticated inventory points. Proves the optimizer and UX before the model exists.

1. Take latest inventory + GBFS snapshot.
2. Build candidate edges from stations that are **not Drop Off** at start to stations that are **not Pick Up** at end (within ride-radius R). Require `pickup_points + dropoff_points > 0` so pure neutral→neutral is dropped. Reject start@dropoff and end@pickup entirely.
3. Edge score = `net_usd / (walk_in + ride + dock_overhead)` where `net_usd` uses the point valuation above (default $0.20/pt) minus e-bike cost if applicable.
4. From start lat/lon, search sequences of edges under the time budget (beam search or limited DFS). Prefer classic bikes by default.
5. For legs that finish after the next refresh, apply a simple decay discount to expected points (high current values → still positive but lower), rather than assuming zero.
6. Return top N itineraries with map geometry, points, $ value, and step times.

### v2 — Better cost model + private polish

- Walking: Haversine × ~1.3 path factor, ~4.5 km/h
- Riding: ~12–15 km/h classic / faster e-bike if preferred
- Soft-penalize low bike/dock counts (race-condition risk)
- Prefer `ba_high_value` when tied
- Explicit 0-score rejection for start@dropoff / end@pickup
- Optional dual objective: maximize membership-extension value ($0.15/pt) vs Lyft/ebike credit ($0.20/pt)
- Same router API; still fed by production rewards in private mode

### v3 — Points prediction model (enables public tool)

Train on collected `(GBFS features, time, station) → ba_points / pickup / dropoff` labels. At public serve time, **only** public GBFS (+ clock/geo features) are available.

Target outputs per station:

- `pickup_points` / `dropoff_points` (or signed `ba_points`)
- optional confidence / probability the station is rewarded at all

Features (public at inference):

- fill/empty ratios, bikes, docks, capacity, classic vs ebike counts
- local hour, minute bucket (15-min), weekday, holiday
- station lat/lon, neighborhood / cluster id
- short history of GBFS only (e.g. last 30–60 min of public status), if the public service caches it

Also fit **cross-refresh persistence** when training labels exist: P(still rewarded | current points, minutes-to-refresh) and expected next value — used in private mode with live points, and as a secondary head or feature for public multi-leg plans.

Evaluation: hold out time ranges; compare predicted map vs production inventory on private validation pulls. Public launch gate = usable precision/recall on “is rewarded” plus calibrated expected points for routing $/min.

Exact ILP / OR-Tools is optional later; for Bay Wheels station counts, beam search on pruned edges is enough.

## App shape

### Backend

- Abstract a `RewardSource` interface:
  - `LiveLyftSource` — authenticated collector (private v1 only)
  - `PredictedSource` — model + public GBFS (public tool)
- `POST /route` → `{ start, time_budget_min, max_walk_m, prefer_ebike }` → ranked itineraries
- Precompute / cache station graph every refresh cycle (15 min); public cache never stores Lyft auth material

### Frontend (mobile-first map)

- Start = GPS or pin
- Sliders: time budget, max walk; toggle classic vs allow e-bike
- Map: pickup → ride → dropoff legs; list: points, ≈$, walk min, ride min, e-bike cost
- Optional redemption preference: membership weeks vs Lyft/ebike credit
- Public mode: clear “predicted points” labeling + last model/GBFS update time
- Refresh after each points tick (live) or GBFS/model refresh (public)

### CLI first

A CLI is enough before UI:

```bash
bike-angels route --lat … --lon … --minutes 45
bike-angels route --lat … --lon … --minutes 45 --allow-ebike --usd-per-point 0.20
# later:
bike-angels route --lat … --lon … --minutes 45 --source predicted
```

## Build order

1. **Keep collecting** production snapshots (labels for the public model).
2. **Feasibility script** — from one snapshot, list best single legs from a fixed start (assert start@dropoff / end@pickup score 0; neutrals allowed; print points and $).
3. **Economics helpers** — configurable membership cost, $0.17/min e-bike, point→USD table; net_usd per leg.
4. **Multi-leg search** — beam search + time budget + walk between legs; classic-first; `RewardSource` abstraction with live production backend.
5. **Availability filters + high-value bias + cross-refresh decay heuristic.**
6. **Private UI / CLI** on live production data (validate routing quality).
7. **Train points model** on SQLite history; offline eval vs held-out production labels.
8. **Public deployment** — GBFS + `PredictedSource` only; no Lyft tokens; predicted labeling in UI.
9. **Ongoing private validation** — occasional authenticated pulls to measure drift and retrain.

## Definition of done

### v1 (private, production data)

Given a start point and 45 minutes, the app returns 1–3 routes with:

- total Bike Angel points from **live** inventory (no start@dropoff / end@pickup legs)
- estimated USD value at $0.15 and $0.20 per point bands
- walk vs ride breakdown; $0 classic cost (or e-bike $ if enabled)
- stations that currently have bikes/docks
- expected points for post-refresh legs discounted, not zeroed, when current value is high (3–4)

### Public tool

Same UX and optimizer, but:

- rewards come from the **prediction model** + public GBFS only
- no user or server Lyft Bike login for routing
- UI marks points as predicted; quality gated by offline eval against collected production labels
