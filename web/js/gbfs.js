/**
 * Live Bay Wheels GBFS client (public, no auth).
 * CORS allows simple browser GETs with Access-Control-Allow-Origin: *.
 */

import { enrichStation } from "./rewards.js";

const GBFS_INFO =
  "https://gbfs.lyft.com/gbfs/2.3/bay/en/station_information.json";
const GBFS_STATUS =
  "https://gbfs.lyft.com/gbfs/2.3/bay/en/station_status.json";

async function fetchJson(url) {
  // Keep the request "simple" so the browser skips OPTIONS preflight
  // (Lyft's GBFS OPTIONS currently returns 403).
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`GBFS ${res.status} for ${url}`);
  return res.json();
}

/**
 * @returns {Promise<{stations: object[], fetchedAt: string, rewardedCount: number}>}
 */
export async function loadLiveStations() {
  const [infoPayload, statusPayload] = await Promise.all([
    fetchJson(GBFS_INFO),
    fetchJson(GBFS_STATUS),
  ]);

  const infoById = new Map(
    (infoPayload.data?.stations || []).map((s) => [s.station_id, s])
  );
  const statusById = new Map(
    (statusPayload.data?.stations || []).map((s) => [s.station_id, s])
  );

  const stations = [];
  for (const [stationId, meta] of infoById) {
    const st = statusById.get(stationId) || {};
    if (st.is_installed === false) continue;

    const bikes = Number(st.num_bikes_available || 0);
    const ebikes = Number(st.num_ebikes_available || 0);
    const docks = Number(st.num_docks_available || 0);
    const capacity = meta.capacity ?? (bikes + docks || null);

    stations.push(
      enrichStation({
        station_id: stationId,
        name: meta.name || stationId,
        lat: Number(meta.lat),
        lon: Number(meta.lon),
        capacity,
        bikes_available: bikes,
        ebikes_available: ebikes,
        classic_bikes_available: Math.max(bikes - ebikes, 0),
        docks_available: docks,
        is_renting: st.is_renting !== false,
        is_returning: st.is_returning !== false,
        reward_source: "predicted_fill_heuristic",
      })
    );
  }

  const rewardedCount = stations.filter(
    (s) => s.pickup_points > 0 || s.dropoff_points > 0
  ).length;

  return {
    stations,
    fetchedAt: new Date().toISOString(),
    rewardedCount,
    stationCount: stations.length,
  };
}
