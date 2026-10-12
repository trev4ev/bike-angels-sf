#!/usr/bin/env python3
"""Build web/data/stations.json from public Bay Wheels GBFS.

Uses a fill-ratio PredictedSource heuristic (public tool path from the plan).
Does not call authenticated Lyft Bike Angels APIs.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

GBFS_INFO = "https://gbfs.lyft.com/gbfs/2.3/bay/en/station_information.json"
GBFS_STATUS = "https://gbfs.lyft.com/gbfs/2.3/bay/en/station_status.json"
TZ = ZoneInfo("America/Los_Angeles")


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "bike-angels-sf-web/0.1 (github pages router)"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def predict_points(fill: float | None) -> tuple[int, int]:
    if fill is None:
        return 0, 0
    if fill >= 0.95:
        return 4, 0
    if fill >= 0.85:
        return 3, 0
    if fill >= 0.7:
        return 2, 0
    if fill >= 0.55:
        return 1, 0
    if fill <= 0.05:
        return 0, 4
    if fill <= 0.15:
        return 0, 3
    if fill <= 0.3:
        return 0, 2
    if fill <= 0.45:
        return 0, 1
    return 0, 0


def build_payload() -> dict:
    info = {
        s["station_id"]: s for s in fetch_json(GBFS_INFO)["data"]["stations"]
    }
    status = {
        s["station_id"]: s for s in fetch_json(GBFS_STATUS)["data"]["stations"]
    }

    stations = []
    for sid, meta in info.items():
        st = status.get(sid) or {}
        if not st.get("is_installed", True):
            continue
        bikes = int(st.get("num_bikes_available") or 0)
        ebikes = int(st.get("num_ebikes_available") or 0)
        docks = int(st.get("num_docks_available") or 0)
        capacity = meta.get("capacity") or (bikes + docks) or None
        fill = (bikes / capacity) if capacity else None
        pickup, dropoff = predict_points(fill)
        stations.append(
            {
                "station_id": sid,
                "name": meta.get("name") or sid,
                "lat": float(meta["lat"]),
                "lon": float(meta["lon"]),
                "capacity": capacity,
                "bikes_available": bikes,
                "ebikes_available": ebikes,
                "classic_bikes_available": max(bikes - ebikes, 0),
                "docks_available": docks,
                "is_renting": bool(st.get("is_renting", True)),
                "is_returning": bool(st.get("is_returning", True)),
                "pickup_points": pickup,
                "dropoff_points": dropoff,
                "ba_points": dropoff - pickup,
                "fill_ratio": None if fill is None else round(fill, 4),
                "reward_source": "predicted_fill_heuristic",
            }
        )

    now = datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    return {
        "generated_at": now.isoformat(),
        "local_time": local.isoformat(),
        "reward_source": "predicted_fill_heuristic",
        "reward_disclaimer": (
            "Points are predicted from public GBFS fill levels, "
            "not live Bike Angels map values."
        ),
        "station_count": len(stations),
        "rewarded_count": sum(
            1 for s in stations if s["pickup_points"] or s["dropoff_points"]
        ),
        "stations": stations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "web" / "data" / "stations.json",
    )
    args = parser.parse_args()
    payload = build_payload()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(
        f"Wrote {args.out} ({payload['station_count']} stations, "
        f"{payload['rewarded_count']} rewarded)"
    )


if __name__ == "__main__":
    main()
