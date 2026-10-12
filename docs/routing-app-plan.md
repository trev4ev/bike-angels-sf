# Bike Angels Routing App Plan

Create optimal multi-leg routes for Bay Wheels Bike Angels points from a starting location, accounting for ride duration and walking between stations.

This builds on the existing collector (`bike-angels-sf`), which snapshots station inventory, GBFS status, and Bike Angels rewards into `data/bike_angels.sqlite`.

## Problem model

Each rewarded leg is:

1. **Walk** from current position → pickup station (needs a bike)
2. **Ride** → dropoff station (needs a dock)
3. Earn `pickup_points + dropoff_points`
4. Optionally walk to the next pickup

Inputs already collected fit this well: station lat/lon, bikes/docks available, `pickup_points` / `dropoff_points` / `ba_points`, plus 15-minute history once collection has run.

**Optimize for:** points per minute (or max points given a time budget), not raw distance.

## Constraints

| Constraint | Why it matters |
|---|---|
| Walk time to first pickup + between legs | Often dominates short sessions |
| Ride duration (distance ÷ bike speed + unlock/dock overhead) | Core cost |
| Bike/dock availability | Illegal edges if 0 bikes or 0 docks |
| Optional max walk distance | Avoid absurd long walks to pickups |
| Session time budget (e.g. 30–90 min) | Primary user knob |
| Points refresh (`:00` / `:15` / `:30` / `:45`) | Live routes go stale; plan must re-solve |

Later (from SQLite history): expected point decay, station fill patterns by hour/weekday.

## Algorithm (phased)

### v1 — Live greedy + beam search (ship first)

1. Take latest inventory + GBFS snapshot.
2. Build candidate edges: every pickup station × nearby dropoff stations within ride-radius R.
3. Edge score = `points / (walk_in + ride + dock_overhead)`.
4. From start lat/lon, search sequences of edges under the time budget (beam search or limited DFS).
5. Return top N itineraries with map geometry and step times.

### v2 — Better cost model

- Walking: Haversine × ~1.3 path factor, ~4.5 km/h
- Riding: ~12–15 km/h classic / faster e-bike if preferred
- Soft-penalize low bike/dock counts (race-condition risk)
- Prefer `ba_high_value` when tied

### v3 — Predictive layer (uses collected data)

- Forecast which stations will still pay in the next 15–45 min
- Prefer routes whose mid-session legs are historically stable
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

1. **Feasibility script** — from one snapshot, list best single legs from a fixed start (validates scoring).
2. **Multi-leg search** — beam search + time budget + walk between legs.
3. **Availability filters + high-value bias.**
4. **Live API wrapper** around collector.
5. **Simple map UI.**
6. **Historical prediction** once ~2 weeks of SQLite exist.

## Definition of done (v1)

Given a start point and 45 minutes, the app returns 1–3 routes with:

- total Bike Angel points
- walk vs ride breakdown
- stations that currently have bikes/docks

Routes are recomputed from the latest snapshot, not stale history alone.
