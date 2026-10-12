/**
 * Multi-leg Bike Angels beam-search router (plan v1/v2, public PredictedSource).
 *
 * Domain rules:
 * - Wrong-direction start@dropoff or end@pickup → 0 points (rejected)
 * - Neutral ends OK; points = pickup + dropoff
 * - Prefer classic bikes; optional e-bike cost
 */

import { walkMinutes, rideMinutes } from "./geo.js";
import { EBIKE_PER_MIN, USD_PER_POINT_HIGH, USD_PER_POINT_LOW } from "./rewards.js";

const DOCK_OVERHEAD_MIN = 0.75;
const DEFAULT_MAX_WALK_MIN = 12;
const DEFAULT_MAX_RIDE_KM = 4.5;
const BEAM_WIDTH = 40;
const MAX_LEGS = 6;

function bikesReady(station, preferEbike) {
  if (!station.is_renting) return false;
  if (preferEbike) return station.bikes_available > 0;
  // Classic-first: require a classic when the count is known.
  if (station.classic_bikes_available != null) {
    return station.classic_bikes_available > 0;
  }
  return station.bikes_available > 0;
}

function docksReady(station) {
  return station.is_returning && station.docks_available > 0;
}

function legPoints(pickup, dropoff) {
  // Reject wrong-direction entirely.
  if (pickup.dropoff_points > 0) return null;
  if (dropoff.pickup_points > 0) return null;
  const pts = (pickup.pickup_points || 0) + (dropoff.dropoff_points || 0);
  if (pts <= 0) return null;
  return pts;
}

function netUsd(points, rideMin, { ebike = false, usdPerPoint = USD_PER_POINT_HIGH } = {}) {
  let usd = points * usdPerPoint;
  if (ebike) usd -= Math.ceil(rideMin) * EBIKE_PER_MIN;
  return usd;
}

function buildCandidates(stations, { preferEbike, maxRideKm }) {
  const usable = stations.filter(
    (s) => s.lat != null && s.lon != null && !String(s.name || "").startsWith("VIRTUAL STATION")
  );

  // Pickup end may be rewarded or neutral; never a dropoff-marked station.
  const pickups = usable.filter(
    (s) => s.dropoff_points === 0 && bikesReady(s, preferEbike)
  );
  const dropoffs = usable.filter(
    (s) => s.pickup_points === 0 && docksReady(s)
  );

  /** @type {Map<string, Array<object>>} */
  const byPickup = new Map();

  for (const pickup of pickups) {
    const edges = [];
    for (const dropoff of dropoffs) {
      if (pickup.station_id === dropoff.station_id) continue;
      const pts = legPoints(pickup, dropoff);
      if (pts == null) continue;
      const rideKm =
        Math.hypot(
          (dropoff.lat - pickup.lat) * 111.32,
          (dropoff.lon - pickup.lon) *
            111.32 *
            Math.cos((pickup.lat * Math.PI) / 180)
        ) * 1.3;
      if (rideKm > maxRideKm) continue;
      const rideMin = rideMinutes(
        pickup.lat,
        pickup.lon,
        dropoff.lat,
        dropoff.lon,
        { ebike: preferEbike }
      );
      edges.push({
        pickup,
        dropoff,
        points: pts,
        rideMin,
        rideKm,
        usdHigh: netUsd(pts, rideMin, { ebike: preferEbike, usdPerPoint: USD_PER_POINT_HIGH }),
        usdLow: netUsd(pts, rideMin, { ebike: preferEbike, usdPerPoint: USD_PER_POINT_LOW }),
      });
    }
    // Keep strongest edges per pickup for beam pruning.
    edges.sort((a, b) => b.points / Math.max(a.rideMin, 1) - a.points / Math.max(b.rideMin, 1));
    byPickup.set(pickup.station_id, edges.slice(0, 25));
  }
  return byPickup;
}

/**
 * @param {{lat:number, lon:number}} start
 * @param {Array<object>} stations
 * @param {{timeBudgetMin?:number, maxWalkMin?:number, preferEbike?:boolean, maxRideKm?:number}} opts
 */
export function findRoutes(start, stations, opts = {}) {
  const timeBudgetMin = opts.timeBudgetMin ?? 45;
  const maxWalkMin = opts.maxWalkMin ?? DEFAULT_MAX_WALK_MIN;
  const preferEbike = Boolean(opts.preferEbike);
  const maxRideKm = opts.maxRideKm ?? DEFAULT_MAX_RIDE_KM;

  const edgeIndex = buildCandidates(stations, { preferEbike, maxRideKm });
  const pickupStations = stations.filter((s) => edgeIndex.has(s.station_id));

  /** @type {Array<object>} */
  let beam = [
    {
      lat: start.lat,
      lon: start.lon,
      elapsed: 0,
      points: 0,
      usdHigh: 0,
      usdLow: 0,
      walkMin: 0,
      rideMin: 0,
      legs: [],
      used: new Set(),
    },
  ];

  /** @type {Array<object>} */
  const finished = [];

  for (let depth = 0; depth < MAX_LEGS; depth++) {
    /** @type {Array<object>} */
    const next = [];

    for (const state of beam) {
      if (state.legs.length > 0) finished.push(state);

      for (const pickup of pickupStations) {
        if (state.used.has(pickup.station_id)) continue;
        const walkIn = walkMinutes(state.lat, state.lon, pickup.lat, pickup.lon);
        if (walkIn > maxWalkMin) continue;

        const edges = edgeIndex.get(pickup.station_id) || [];
        for (const edge of edges) {
          if (state.used.has(edge.dropoff.station_id)) continue;
          // Avoid immediate reverse of previous leg.
          if (
            state.legs.length &&
            state.legs[state.legs.length - 1].pickup.station_id ===
              edge.dropoff.station_id
          ) {
            continue;
          }

          const legTime = walkIn + edge.rideMin + DOCK_OVERHEAD_MIN;
          const elapsed = state.elapsed + legTime;
          if (elapsed > timeBudgetMin) continue;

          const used = new Set(state.used);
          used.add(pickup.station_id);
          used.add(edge.dropoff.station_id);

          next.push({
            lat: edge.dropoff.lat,
            lon: edge.dropoff.lon,
            elapsed,
            points: state.points + edge.points,
            usdHigh: state.usdHigh + edge.usdHigh,
            usdLow: state.usdLow + edge.usdLow,
            walkMin: state.walkMin + walkIn,
            rideMin: state.rideMin + edge.rideMin,
            used,
            legs: [
              ...state.legs,
              {
                pickup: edge.pickup,
                dropoff: edge.dropoff,
                points: edge.points,
                pickupPoints: edge.pickup.pickup_points || 0,
                dropoffPoints: edge.dropoff.dropoff_points || 0,
                walkMin: walkIn,
                rideMin: edge.rideMin,
                usdHigh: edge.usdHigh,
                usdLow: edge.usdLow,
                ebike: preferEbike,
              },
            ],
          });
        }
      }
    }

    if (!next.length) break;

    next.sort((a, b) => {
      const sa = a.points / Math.max(a.elapsed, 1);
      const sb = b.points / Math.max(b.elapsed, 1);
      if (sb !== sa) return sb - sa;
      return b.points - a.points;
    });
    beam = next.slice(0, BEAM_WIDTH);
  }

  finished.push(...beam);

  const ranked = finished
    .filter((r) => r.legs.length > 0)
    .sort((a, b) => {
      if (b.points !== a.points) return b.points - a.points;
      const ea = a.points / Math.max(a.elapsed, 1);
      const eb = b.points / Math.max(b.elapsed, 1);
      return eb - ea;
    });

  // Deduplicate by station sequence.
  const seen = new Set();
  const unique = [];
  for (const route of ranked) {
    const key = route.legs
      .map((l) => `${l.pickup.station_id}>${l.dropoff.station_id}`)
      .join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(summarize(route, preferEbike));
    if (unique.length >= 3) break;
  }
  return unique;
}

function summarize(route, preferEbike) {
  return {
    points: route.points,
    usdHigh: round2(route.usdHigh),
    usdLow: round2(route.usdLow),
    elapsedMin: round1(route.elapsed),
    walkMin: round1(route.walkMin),
    rideMin: round1(route.rideMin),
    preferEbike,
    legs: route.legs.map((leg, i) => ({
      index: i + 1,
      pickup: {
        id: leg.pickup.station_id,
        name: leg.pickup.name,
        lat: leg.pickup.lat,
        lon: leg.pickup.lon,
        points: leg.pickupPoints,
        bikes: leg.pickup.bikes_available,
      },
      dropoff: {
        id: leg.dropoff.station_id,
        name: leg.dropoff.name,
        lat: leg.dropoff.lat,
        lon: leg.dropoff.lon,
        points: leg.dropoffPoints,
        docks: leg.dropoff.docks_available,
      },
      points: leg.points,
      walkMin: round1(leg.walkMin),
      rideMin: round1(leg.rideMin),
      usdHigh: round2(leg.usdHigh),
    })),
  };
}

function round1(n) {
  return Math.round(n * 10) / 10;
}

function round2(n) {
  return Math.round(n * 100) / 100;
}
