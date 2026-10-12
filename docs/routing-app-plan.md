# Bike Angels Routing App Plan

Create optimal multi-leg routes for Bay Wheels Bike Angels points from a starting location, accounting for ride duration and walking between stations.

This builds on the existing collector (`bike-angels-sf`), which snapshots station inventory, GBFS status, and Bike Angels rewards into `data/bike_angels.sqlite`.

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

### v1 — Live greedy + beam search (ship first)

1. Take latest inventory + GBFS snapshot.
2. Build candidate edges from stations that are **not Drop Off** at start to stations that are **not Pick Up** at end (within ride-radius R). Require `pickup_points + dropoff_points > 0` so pure neutral→neutral is dropped. Reject start@dropoff and end@pickup entirely.
3. Edge score = `net_usd / (walk_in + ride + dock_overhead)` where `net_usd` uses the point valuation above (default $0.20/pt) minus e-bike cost if applicable.
4. From start lat/lon, search sequences of edges under the time budget (beam search or limited DFS). Prefer classic bikes by default.
5. For legs that finish after the next refresh, apply a simple decay discount to expected points (high current values → still positive but lower), rather than assuming zero.
6. Return top N itineraries with map geometry, points, $ value, and step times.

### v2 — Better cost model

- Walking: Haversine × ~1.3 path factor, ~4.5 km/h
- Riding: ~12–15 km/h classic / faster e-bike if preferred
- Soft-penalize low bike/dock counts (race-condition risk)
- Prefer `ba_high_value` when tied
- Explicit 0-score rejection for start@dropoff / end@pickup
- Optional dual objective: maximize membership-extension value ($0.15/pt) vs Lyft/ebike credit ($0.20/pt)

### v3 — Predictive layer (uses collected data)

- Fit persistence: P(still rewarded | current points, minutes-to-refresh) and expected next value (e.g. 4 → ~2–3)
- Prefer routes whose mid-session legs are historically stable after a tick
- Optional: learn points/minute surfaces by hour for cold starts

Exact ILP / OR-Tools is optional later; for Bay Wheels station counts, beam search on pruned edges is enough.

## App shape

### Backend

- Reuse collector auth/client for live rewards
- `POST /route` → `{ start, time_budget_min, max_walk_m, prefer_ebike }` → ranked itineraries
- Precompute / cache station graph every refresh cycle

### Frontend (mobile-first map)

- Start = GPS or pin
- Sliders: time budget, max walk; toggle classic vs allow e-bike
- Map: pickup → ride → dropoff legs; list: points, ≈$, walk min, ride min, e-bike cost
- Optional redemption preference: membership weeks vs Lyft/ebike credit
- Refresh after each points tick

### CLI first

A CLI is enough before UI:

```bash
bike-angels route --lat … --lon … --minutes 45
bike-angels route --lat … --lon … --minutes 45 --allow-ebike --usd-per-point 0.20
```

## Build order

1. **Feasibility script** — from one snapshot, list best single legs from a fixed start (assert start@dropoff / end@pickup score 0; neutrals allowed; print points and $).
2. **Economics helpers** — configurable membership cost, $0.17/min e-bike, point→USD table; net_usd per leg.
3. **Multi-leg search** — beam search + time budget + walk between legs; classic-first.
4. **Availability filters + high-value bias + cross-refresh decay heuristic.**
5. **Live API wrapper** around collector.
6. **Simple map UI.**
7. **Historical persistence model** once ~2 weeks of SQLite exist (replace the heuristic decay).

## Definition of done (v1)

Given a start point and 45 minutes, the app returns 1–3 routes with:

- total Bike Angel points (no start@dropoff / end@pickup legs)
- estimated USD value at $0.15 and $0.20 per point bands
- walk vs ride breakdown; $0 classic cost (or e-bike $ if enabled)
- stations that currently have bikes/docks
- expected points for post-refresh legs discounted, not zeroed, when current value is high (3–4)

Routes are recomputed from the latest snapshot, not stale history alone.
