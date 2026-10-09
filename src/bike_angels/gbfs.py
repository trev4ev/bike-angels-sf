from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import GBFS_STATION_INFO, GBFS_STATION_STATUS


@dataclass
class StationMeta:
    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int | None


@dataclass
class StationStatus:
    station_id: str
    num_bikes_available: int
    num_ebikes_available: int
    num_docks_available: int
    num_bikes_disabled: int
    num_docks_disabled: int
    is_installed: bool
    is_renting: bool
    is_returning: bool
    last_reported: int | None


def fetch_station_meta(client: httpx.Client | None = None) -> dict[str, StationMeta]:
    own = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        resp = client.get(GBFS_STATION_INFO)
        resp.raise_for_status()
        out: dict[str, StationMeta] = {}
        for s in resp.json()["data"]["stations"]:
            out[s["station_id"]] = StationMeta(
                station_id=s["station_id"],
                name=s.get("name") or "",
                lat=float(s["lat"]),
                lon=float(s["lon"]),
                capacity=s.get("capacity"),
            )
        return out
    finally:
        if own:
            client.close()


def fetch_station_status(
    client: httpx.Client | None = None,
) -> dict[str, StationStatus]:
    own = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        resp = client.get(GBFS_STATION_STATUS)
        resp.raise_for_status()
        out: dict[str, StationStatus] = {}
        for s in resp.json()["data"]["stations"]:
            out[s["station_id"]] = StationStatus(
                station_id=s["station_id"],
                num_bikes_available=int(s.get("num_bikes_available") or 0),
                num_ebikes_available=int(s.get("num_ebikes_available") or 0),
                num_docks_available=int(s.get("num_docks_available") or 0),
                num_bikes_disabled=int(s.get("num_bikes_disabled") or 0),
                num_docks_disabled=int(s.get("num_docks_disabled") or 0),
                is_installed=bool(s.get("is_installed")),
                is_renting=bool(s.get("is_renting")),
                is_returning=bool(s.get("is_returning")),
                last_reported=s.get("last_reported"),
            )
        return out
    finally:
        if own:
            client.close()
