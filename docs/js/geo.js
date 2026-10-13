/** Geospatial helpers for walk/ride time estimates. */

const EARTH_KM = 6371;
const PATH_FACTOR = 1.3;
const WALK_KMH = 4.5;
const RIDE_CLASSIC_KMH = 13;
const RIDE_EBIKE_KMH = 18;

export function haversineKm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.sqrt(a));
}

export function pathKm(lat1, lon1, lat2, lon2) {
  return haversineKm(lat1, lon1, lat2, lon2) * PATH_FACTOR;
}

export function walkMinutes(lat1, lon1, lat2, lon2) {
  return (pathKm(lat1, lon1, lat2, lon2) / WALK_KMH) * 60;
}

export function rideMinutes(lat1, lon1, lat2, lon2, { ebike = false } = {}) {
  const speed = ebike ? RIDE_EBIKE_KMH : RIDE_CLASSIC_KMH;
  return (pathKm(lat1, lon1, lat2, lon2) / speed) * 60;
}

export function formatMinutes(mins) {
  if (!Number.isFinite(mins)) return "—";
  if (mins < 1) return "<1 min";
  if (mins < 60) return `${Math.round(mins)} min`;
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}
