from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

from .auth import AuthClient
from .config import BASE_URL, BBOX, MAP_RADIUS_KM, TILE_STEP_KM
from .gbfs import fetch_station_meta


# reward_badge.icon.core_icon_v1 values observed in the Citibike/Lyft app.
ICON_PICKUP = 114
ICON_DROPOFF = 99


@dataclass
class RewardObservation:
    station_id: str
    lat: float
    lon: float
    bikes_available: int | None = None
    docks_available: int | None = None
    ebikes_available: int | None = None
    pickup_points: int | None = None
    dropoff_points: int | None = None
    ba_points: int | None = None
    ba_high_value: bool | None = None
    raw_badges: list[dict[str, Any]] = field(default_factory=list)


class LyftMapClient:
    """Authenticated Lyft last-mile map client for Bike Angels rewards."""

    def __init__(self, auth: AuthClient) -> None:
        self.auth = auth
        self._http = httpx.Client(timeout=45.0)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LyftMapClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _headers(self, lat: float, lon: float) -> dict[str, str]:
        token = self.auth.ensure_access_token()
        headers = self.auth.common_headers(authenticated=True)
        headers.update(
            {
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "accept": "application/json",
                "x-idl-source": "pb.api.endpoints.v1.last_mile.ReadMapItemsRequest",
                "x-location": f"{lat},{lon}",
                "x-lyft-region": "",
            }
        )
        return headers

    def map_items(
        self,
        lat: float,
        lon: float,
        radius_km: float = MAP_RADIUS_KM,
    ) -> dict[str, Any]:
        body = {
            "last_mile_context": {
                "origin_lat": lat,
                "origin_long": lon,
                "radius_km": radius_km,
                "result_filters": [
                    "is_bike",
                    "show_rider_rewards",
                    "bff_fidget_enabled",
                ],
            }
        }
        resp = self._http.post(
            f"{BASE_URL}/v1/last-mile/map-items",
            json=body,
            headers=self._headers(lat, lon),
        )
        if resp.status_code == 401:
            self.auth.refresh()
            resp = self._http.post(
                f"{BASE_URL}/v1/last-mile/map-items",
                json=body,
                headers=self._headers(lat, lon),
            )
        resp.raise_for_status()
        return resp.json()

    def inventory(self, lat: float = 37.7749, lon: float = -122.4194) -> dict[str, Any]:
        """Alternate city-wide inventory endpoint (may/may not include rewards)."""
        token = self.auth.ensure_access_token()
        headers = self.auth.common_headers(authenticated=True)
        headers.update(
            {
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "accept": "application/json",
                "x-location": f"{lat},{lon}",
            }
        )
        resp = self._http.post(
            f"{BASE_URL}/v1/lbsbff/map/inventory",
            json={},
            headers=headers,
        )
        if resp.status_code == 401:
            self.auth.refresh()
            token = self.auth.ensure_access_token()
            headers["authorization"] = f"Bearer {token}"
            resp = self._http.post(
                f"{BASE_URL}/v1/lbsbff/map/inventory",
                json={},
                headers=headers,
            )
        resp.raise_for_status()
        return resp.json()

    def iter_tiles(self) -> Iterator[tuple[float, float]]:
        """Greedy cover of GBFS stations inside BBOX (far fewer calls than a grid)."""
        meta = fetch_station_meta(self._http)
        stations = [
            (m.lat, m.lon)
            for m in meta.values()
            if BBOX["lat_min"] <= m.lat <= BBOX["lat_max"]
            and BBOX["lon_min"] <= m.lon <= BBOX["lon_max"]
        ]
        if not stations:
            # Fallback grid if GBFS is empty/unreachable.
            yield from self._iter_grid_tiles()
            return

        lat_mid = (BBOX["lat_min"] + BBOX["lat_max"]) / 2
        km_per_lat = 111.32
        km_per_lon = 111.32 * math.cos(math.radians(lat_mid))
        # Stay inside map radius with some overlap margin.
        cover_km = max(MAP_RADIUS_KM - 0.4, TILE_STEP_KM / 2)
        uncovered = stations[:]
        centers: list[tuple[float, float]] = []

        while uncovered:
            # Pick an uncovered station as a new query center.
            lat0, lon0 = uncovered[0]
            centers.append((lat0, lon0))
            still = []
            for lat, lon in uncovered:
                dlat_km = (lat - lat0) * km_per_lat
                dlon_km = (lon - lon0) * km_per_lon
                if math.hypot(dlat_km, dlon_km) > cover_km:
                    still.append((lat, lon))
            uncovered = still

        yield from centers

    def _iter_grid_tiles(self) -> Iterator[tuple[float, float]]:
        lat_mid = (BBOX["lat_min"] + BBOX["lat_max"]) / 2
        km_per_lat = 111.32
        km_per_lon = 111.32 * math.cos(math.radians(lat_mid))
        dlat = TILE_STEP_KM / km_per_lat
        dlon = TILE_STEP_KM / km_per_lon

        lat = BBOX["lat_min"]
        while lat <= BBOX["lat_max"] + 1e-9:
            lon = BBOX["lon_min"]
            while lon <= BBOX["lon_max"] + 1e-9:
                yield lat, lon
                lon += dlon
            lat += dlat

    def fetch_all_rewards(self) -> dict[str, RewardObservation]:
        """Fetch Bay Wheels rewards.

        Bay Wheels exposes Bike Angels via `/v1/lbsbff/map/inventory`
        (`ba_points` / `ba_high_value`). NYC-style `map-items` reward badges
        are a fallback.
        """
        by_id = self.fetch_inventory_rewards()
        if any(
            (o.ba_points not in (None, 0))
            or (o.pickup_points not in (None, 0))
            or (o.dropoff_points not in (None, 0))
            for o in by_id.values()
        ):
            return by_id

        for lat, lon in self.iter_tiles():
            payload = self.map_items(lat, lon)
            for item in payload.get("map_items") or []:
                obs = _parse_map_item(item)
                if not obs:
                    continue
                existing = by_id.get(obs.station_id)
                if existing is None:
                    by_id[obs.station_id] = obs
                else:
                    _merge_observation(existing, obs)
        return by_id

    def fetch_inventory_rewards(
        self, lat: float = 37.7749, lon: float = -122.4194
    ) -> dict[str, RewardObservation]:
        """Parse city-wide inventory GeoJSON into reward observations."""
        payload = self.inventory(lat, lon)
        raw = payload.get("map_inventory_json")
        if isinstance(raw, str):
            data = json.loads(raw)
        elif isinstance(payload.get("features"), list):
            data = payload
        else:
            return {}

        by_id: dict[str, RewardObservation] = {}
        for feature in data.get("features") or []:
            obs = _parse_inventory_feature(feature)
            if obs:
                by_id[obs.station_id] = obs
        return by_id


def normalize_station_id(device_id: str) -> str:
    # motivate_SFO_<uuid> or motivate_BKN_<uuid>
    parts = device_id.split("_", 2)
    if len(parts) == 3 and parts[0] == "motivate":
        return parts[2]
    return device_id


def _parse_inventory_feature(feature: dict[str, Any]) -> RewardObservation | None:
    props = feature.get("properties") or {}
    # map_item_type=1 are stations; 2 are free-floating bikes/scooters.
    if props.get("map_item_type") != 1:
        return None

    device_id = props.get("map_item_id")
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if not device_id or len(coords) < 2:
        return None

    ba_points = props.get("ba_points")
    try:
        ba_points_i = int(ba_points) if ba_points is not None else 0
    except (TypeError, ValueError):
        ba_points_i = 0

    # Signed convention observed on Bay Wheels:
    #   negative => pickup (take a bike), positive => dropoff (dock a bike)
    pickup = abs(ba_points_i) if ba_points_i < 0 else 0
    dropoff = ba_points_i if ba_points_i > 0 else 0

    return RewardObservation(
        station_id=normalize_station_id(str(device_id)),
        lat=float(coords[1]),
        lon=float(coords[0]),
        bikes_available=_maybe_int(props.get("bikes_available")),
        docks_available=_maybe_int(props.get("docks_available")),
        ebikes_available=_maybe_int(props.get("ebikes_available")),
        pickup_points=pickup,
        dropoff_points=dropoff,
        ba_points=ba_points_i,
        ba_high_value=bool(props.get("ba_high_value"))
        if props.get("ba_high_value") is not None
        else None,
        raw_badges=[
            {
                "ba_points": ba_points_i,
                "ba_high_value": props.get("ba_high_value"),
            }
        ],
    )


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_map_item(item: dict[str, Any]) -> RewardObservation | None:
    device = item.get("device") or {}
    device_id = device.get("id")
    location = item.get("location") or {}
    if not device_id or "lat" not in location or "lng" not in location:
        return None

    pin = (
        (item.get("collapsible_collection_bubble") or {})
        .get("selected_detailed_text_specific_pin")
        or {}
    )
    bikes, docks = _parse_availability(pin.get("text_specific_items") or [])
    pickup, dropoff, badges = _parse_reward_badge(pin.get("reward_badge"))

    return RewardObservation(
        station_id=normalize_station_id(device_id),
        lat=float(location["lat"]),
        lon=float(location["lng"]),
        bikes_available=bikes,
        docks_available=docks,
        pickup_points=pickup,
        dropoff_points=dropoff,
        raw_badges=badges,
    )


def _parse_availability(
    items: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    bikes = None
    docks = None
    for entry in items:
        icon = ((entry.get("icon") or {}).get("core_icon_v1"))
        text = entry.get("text")
        if text is None:
            continue
        try:
            value = int(str(text).strip())
        except ValueError:
            continue
        # Observed: 338 = bikes, 156 = docks
        if icon == 338:
            bikes = value
        elif icon == 156:
            docks = value
        elif bikes is None:
            bikes = value
        elif docks is None:
            docks = value
    return bikes, docks


def _parse_reward_badge(
    badge: dict[str, Any] | None,
) -> tuple[int | None, int | None, list[dict[str, Any]]]:
    if not badge:
        return None, None, []
    points_raw = badge.get("points")
    try:
        points = int(str(points_raw)) if points_raw is not None else None
    except ValueError:
        points = None
    icon = ((badge.get("icon") or {}).get("core_icon_v1"))
    pickup = points if icon == ICON_PICKUP else None
    dropoff = points if icon == ICON_DROPOFF else None
    # Unknown icon: keep points but don't assign direction yet.
    if points is not None and pickup is None and dropoff is None:
        # Leave both None; store raw for later inspection.
        pass
    return pickup, dropoff, [badge]


def _merge_observation(dst: RewardObservation, src: RewardObservation) -> None:
    if src.bikes_available is not None:
        dst.bikes_available = src.bikes_available
    if src.docks_available is not None:
        dst.docks_available = src.docks_available
    if src.ebikes_available is not None:
        dst.ebikes_available = src.ebikes_available
    if src.pickup_points is not None:
        dst.pickup_points = src.pickup_points
    if src.dropoff_points is not None:
        dst.dropoff_points = src.dropoff_points
    if src.ba_points is not None:
        dst.ba_points = src.ba_points
    if src.ba_high_value is not None:
        dst.ba_high_value = src.ba_high_value
    dst.raw_badges.extend(src.raw_badges)
