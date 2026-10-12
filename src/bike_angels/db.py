from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR, DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    collected_at_unix REAL NOT NULL,
    source TEXT NOT NULL,
    station_count INTEGER NOT NULL,
    rewarded_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS station_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    collected_at TEXT NOT NULL,
    collected_at_unix REAL NOT NULL,
    local_hour INTEGER NOT NULL,
    local_minute INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    station_id TEXT NOT NULL,
    name TEXT,
    lat REAL,
    lon REAL,
    capacity INTEGER,
    bikes_available INTEGER,
    ebikes_available INTEGER,
    classic_bikes_available INTEGER,
    docks_available INTEGER,
    bikes_disabled INTEGER,
    docks_disabled INTEGER,
    is_installed INTEGER,
    is_renting INTEGER,
    is_returning INTEGER,
    pickup_points INTEGER,
    dropoff_points INTEGER,
    ba_points INTEGER,
    ba_high_value INTEGER,
    fill_ratio REAL,
    empty_ratio REAL
);

CREATE INDEX IF NOT EXISTS idx_obs_station_time
    ON station_observations(station_id, collected_at_unix);
CREATE INDEX IF NOT EXISTS idx_obs_time
    ON station_observations(collected_at_unix);
CREATE INDEX IF NOT EXISTS idx_obs_points
    ON station_observations(pickup_points, dropoff_points);
"""


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(station_observations)")
        }
        if "ba_points" not in cols:
            self.conn.execute(
                "ALTER TABLE station_observations ADD COLUMN ba_points INTEGER"
            )
        if "ba_high_value" not in cols:
            self.conn.execute(
                "ALTER TABLE station_observations ADD COLUMN ba_high_value INTEGER"
            )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_obs_ba_points
                ON station_observations(ba_points)
            """
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def insert_snapshot(
        self,
        *,
        collected_at: str,
        collected_at_unix: float,
        source: str,
        station_count: int,
        rewarded_count: int,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO snapshots (
                collected_at, collected_at_unix, source,
                station_count, rewarded_count
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                collected_at,
                collected_at_unix,
                source,
                station_count,
                rewarded_count,
            ),
        )
        snapshot_id = int(cur.lastrowid)
        cur.executemany(
            """
            INSERT INTO station_observations (
                snapshot_id, collected_at, collected_at_unix,
                local_hour, local_minute, weekday,
                station_id, name, lat, lon, capacity,
                bikes_available, ebikes_available, classic_bikes_available,
                docks_available, bikes_disabled, docks_disabled,
                is_installed, is_renting, is_returning,
                pickup_points, dropoff_points, ba_points, ba_high_value,
                fill_ratio, empty_ratio
            ) VALUES (
                :snapshot_id, :collected_at, :collected_at_unix,
                :local_hour, :local_minute, :weekday,
                :station_id, :name, :lat, :lon, :capacity,
                :bikes_available, :ebikes_available, :classic_bikes_available,
                :docks_available, :bikes_disabled, :docks_disabled,
                :is_installed, :is_renting, :is_returning,
                :pickup_points, :dropoff_points, :ba_points, :ba_high_value,
                :fill_ratio, :empty_ratio
            )
            """,
            [{**row, "snapshot_id": snapshot_id} for row in rows],
        )
        self.conn.commit()
        return snapshot_id

    def summary(self) -> dict[str, Any]:
        cur = self.conn.cursor()
        snaps = cur.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        obs = cur.execute("SELECT COUNT(*) FROM station_observations").fetchone()[0]
        first = cur.execute(
            "SELECT MIN(collected_at), MAX(collected_at) FROM snapshots"
        ).fetchone()
        return {
            "snapshots": snaps,
            "observations": obs,
            "first_collected_at": first[0],
            "last_collected_at": first[1],
            "db_path": str(self.path),
        }
