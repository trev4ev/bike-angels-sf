/**
 * Predicted reward source from public GBFS fill levels.
 * Matches the plan's RewardSource interface shape for the public tool path.
 * Not live Bike Angels map values.
 */

export function predictPointsFromFill(fillRatio) {
  if (fillRatio == null || Number.isNaN(fillRatio)) {
    return { pickup_points: 0, dropoff_points: 0 };
  }
  if (fillRatio >= 0.95) return { pickup_points: 4, dropoff_points: 0 };
  if (fillRatio >= 0.85) return { pickup_points: 3, dropoff_points: 0 };
  if (fillRatio >= 0.7) return { pickup_points: 2, dropoff_points: 0 };
  if (fillRatio >= 0.55) return { pickup_points: 1, dropoff_points: 0 };
  if (fillRatio <= 0.05) return { pickup_points: 0, dropoff_points: 4 };
  if (fillRatio <= 0.15) return { pickup_points: 0, dropoff_points: 3 };
  if (fillRatio <= 0.3) return { pickup_points: 0, dropoff_points: 2 };
  if (fillRatio <= 0.45) return { pickup_points: 0, dropoff_points: 1 };
  return { pickup_points: 0, dropoff_points: 0 };
}

export function enrichStation(raw) {
  const bikes = Number(raw.bikes_available ?? 0);
  const docks = Number(raw.docks_available ?? 0);
  const ebikes = Number(raw.ebikes_available ?? 0);
  const capacity = raw.capacity ?? (bikes + docks || null);
  const fill =
    capacity && capacity > 0
      ? bikes / capacity
      : raw.fill_ratio ?? null;

  // Always derive predicted points from live fill (public tool path).
  const predicted = predictPointsFromFill(fill);

  return {
    ...raw,
    capacity,
    bikes_available: bikes,
    docks_available: docks,
    ebikes_available: ebikes,
    classic_bikes_available:
      raw.classic_bikes_available ?? Math.max(bikes - ebikes, 0),
    fill_ratio: fill,
    pickup_points: predicted.pickup_points,
    dropoff_points: predicted.dropoff_points,
    ba_points: predicted.dropoff_points - predicted.pickup_points,
    is_renting: raw.is_renting !== false,
    is_returning: raw.is_returning !== false,
  };
}

export function roleLabel(station) {
  if (station.pickup_points > 0) return "pickup";
  if (station.dropoff_points > 0) return "dropoff";
  return "neutral";
}

export const USD_PER_POINT_HIGH = 0.2;
export const USD_PER_POINT_LOW = 0.15;
export const EBIKE_PER_MIN = 0.17;
