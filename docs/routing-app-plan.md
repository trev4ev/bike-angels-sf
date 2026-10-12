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

**Optimize for:** points per minute (or max points given a time budget), not raw distance.

### Scoring rules (domain)

**Both ends must match direction, or the whole ride pays 0.**  
Pickup points only count when you unlock at a pickup-rewarded station; dropoff points only count when you dock at a dropoff-rewarded station. Starting a trip at a dropoff station (or docking at a pickup station) yields **0 points for that ride**, even if the other end would have paid. The optimizer must never treat “pickup anywhere → dropoff with points” (or the reverse) as a valid scored edge.

**High-value stations tend to persist across the next refresh.**  
A station offering 3–4 points now is likely to still offer points after the next `:00` / `:15` / `:30` / `:45` tick, usually at a lower value. Multi-leg plans that cross a refresh should not assume mid-route stations go to zero; prefer decaying expected points (e.g. discount next-window legs) over discarding them. Validate/refine this persistence curve from collected snapshots.

## Constraints

| Constraint | Why it matters |
|---|---|
| Both-end direction match | Wrong-way pickup or dropoff → 0 for the whole ride |
| Walk time to first pickup + between legs | Often dominates short sessions |
| Ride duration (distance ÷ bike speed + unlock/dock overhead) | Core cost |
| Bike/dock availability | Illegal edges if 0 bikes or 0 docks |
| Optional max walk distance | Avoid absurd long walks to pickups |
| Session time budget (e.g. 30–90 min) | Primary user knob |
| Points refresh (`:00` / `:15` / `:30` / `:45`) | Live values change; high-point stations often persist lower |

Later (from SQLite history): point persistence / decay curves, station fill patterns by hour/weekday.

## Algorithm (phased)

### v1 — Live greedy + beam search (ship first)

1. Take latest inventory + GBFS snapshot.
2. Build candidate edges **only** from stations with `pickup_points > 0` to stations with `dropoff_points > 0` (within ride-radius R). Exclude any reverse or zero-side pair — those score 0.
3. Edge score = `(pickup_points + dropoff_points) / (walk_in + ride + dock_overhead)`.
4. From start lat/lon, search sequences of edges under the time budget (beam search or limited DFS).
5. For legs that finish after the next refresh, apply a simple decay discount to expected points (high current values → still positive but lower), rather than assuming zero.
6. Return top N itineraries with map geometry and step times.

### v2 — Better cost model

- Walking: Haversine × ~1.3 path factor, ~4.5 km/h
- Riding: ~12–15 km/h classic / faster e-bike if preferred
- Soft-penalize low bike/dock counts (race-condition risk)
- Prefer `ba_high_value` when tied
- Explicit 0-score rejection for wrong-direction station pairs (defense in depth)

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
- Sliders: time budget, max walk
- Map: pickup → ride → dropoff legs; list: points, walk min, ride min, total
- Refresh after each points tick

### CLI first

A CLI is enough before UI:

```bash
bike-angels route --lat … --lon … --minutes 45
```

## Build order

1. **Feasibility script** — from one snapshot, list best single legs from a fixed start (validates both-end scoring; assert wrong-direction pairs score 0).
2. **Multi-leg search** — beam search + time budget + walk between legs.
3. **Availability filters + high-value bias + cross-refresh decay heuristic.**
4. **Live API wrapper** around collector.
5. **Simple map UI.**
6. **Historical persistence model** once ~2 weeks of SQLite exist (replace the heuristic decay).

## Definition of done (v1)

Given a start point and 45 minutes, the app returns 1–3 routes with:

- total Bike Angel points (only legs with pickup *and* dropoff rewards)
- walk vs ride breakdown
- stations that currently have bikes/docks
- expected points for post-refresh legs discounted, not zeroed, when current value is high (3–4)

Routes are recomputed from the latest snapshot, not stale history alone.
