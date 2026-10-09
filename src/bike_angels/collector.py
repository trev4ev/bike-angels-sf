from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .auth import AuthClient
from .client import LyftMapClient, RewardObservation
from .db import Database
from .gbfs import StationMeta, StationStatus, fetch_station_meta, fetch_station_status

TZ = ZoneInfo("America/Los_Angeles")


def collect_once(
    auth: AuthClient | None = None,
    db: Database | None = None,
) -> dict[str, Any]:
    own_auth = auth is None
    own_db = db is None
    auth = auth or AuthClient()
    db = db or Database()
    try:
        meta = fetch_station_meta()
        status = fetch_station_status()
        with LyftMapClient(auth) as client:
            rewards = client.fetch_all_rewards()

        now = datetime.now(timezone.utc)
        local = now.astimezone(TZ)
        rows = _build_rows(now, local, meta, status, rewards)
        rewarded = sum(
            1
            for r in rows
            if (r["pickup_points"] or 0) > 0 or (r["dropoff_points"] or 0) > 0
        )
        snapshot_id = db.insert_snapshot(
            collected_at=now.isoformat(),
            collected_at_unix=now.timestamp(),
            source="map-items+gbfs",
            station_count=len(rows),
            rewarded_count=rewarded,
            rows=rows,
        )
        return {
            "snapshot_id": snapshot_id,
            "station_count": len(rows),
            "rewarded_count": rewarded,
            "reward_api_stations": len(rewards),
            "collected_at": now.isoformat(),
            "local_time": local.isoformat(),
        }
    finally:
        if own_auth:
            auth.close()
        if own_db:
            db.close()


def _build_rows(
    now: datetime,
    local: datetime,
    meta: dict[str, StationMeta],
    status: dict[str, StationStatus],
    rewards: dict[str, RewardObservation],
) -> list[dict[str, Any]]:
    station_ids = set(meta) | set(status) | set(rewards)
    rows: list[dict[str, Any]] = []

    for station_id in sorted(station_ids):
        m = meta.get(station_id)
        s = status.get(station_id)
        r = rewards.get(station_id)

        bikes = (
            r.bikes_available
            if r and r.bikes_available is not None
            else (s.num_bikes_available if s else None)
        )
        docks = (
            r.docks_available
            if r and r.docks_available is not None
            else (s.num_docks_available if s else None)
        )
        ebikes = s.num_ebikes_available if s else None
        classic = None
        if bikes is not None and ebikes is not None:
            classic = max(bikes - ebikes, 0)

        capacity = m.capacity if m else None
        fill_ratio = None
        empty_ratio = None
        if capacity and capacity > 0 and bikes is not None:
            fill_ratio = bikes / capacity
        if capacity and capacity > 0 and docks is not None:
            empty_ratio = docks / capacity

        rows.append(
            {
                "collected_at": now.isoformat(),
                "collected_at_unix": now.timestamp(),
                "local_hour": local.hour,
                "local_minute": local.minute,
                "weekday": local.weekday(),
                "station_id": station_id,
                "name": m.name if m else None,
                "lat": (r.lat if r else (m.lat if m else None)),
                "lon": (r.lon if r else (m.lon if m else None)),
                "capacity": capacity,
                "bikes_available": bikes,
                "ebikes_available": ebikes,
                "classic_bikes_available": classic,
                "docks_available": docks,
                "bikes_disabled": s.num_bikes_disabled if s else None,
                "docks_disabled": s.num_docks_disabled if s else None,
                "is_installed": int(s.is_installed) if s else None,
                "is_renting": int(s.is_renting) if s else None,
                "is_returning": int(s.is_returning) if s else None,
                "pickup_points": r.pickup_points if r else None,
                "dropoff_points": r.dropoff_points if r else None,
                "fill_ratio": fill_ratio,
                "empty_ratio": empty_ratio,
            }
        )
    return rows
