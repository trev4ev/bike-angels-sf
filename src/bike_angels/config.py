from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
TOKEN_PATH = PROJECT_ROOT / "tokens.json"
DB_PATH = DATA_DIR / "bike_angels.sqlite"

# Bay Wheels iOS app OAuth credentials (embedded in the official app;
# also published by the unofficial bay-wheels Python client).
CLIENT_ID = "kN2nqhox8ySO"
CLIENT_SECRET = "K04achF9yqAh1KO6qCihWIARbfdrEJLU"

BASE_URL = "https://api.lyft.com"
USER_AGENT = "com.motivateco.gobike:iOS:26.2:2025.52.3.27469952"
USER_DEVICE = "iPhone14,3"
BRAND_ID = "baywheels"
REGION_CODE = "SFO"

GBFS_STATION_INFO = (
    "https://gbfs.lyft.com/gbfs/2.3/bay/en/station_information.json"
)
GBFS_STATION_STATUS = (
    "https://gbfs.lyft.com/gbfs/2.3/bay/en/station_status.json"
)

# Bay Area bounding box covering Bay Wheels stations.
BBOX = {
    "lat_min": 37.30,
    "lat_max": 37.90,
    "lon_min": -122.52,
    "lon_max": -121.85,
}

# map-items is radius-limited; tile the bay with overlapping circles.
MAP_RADIUS_KM = 3.0
TILE_STEP_KM = 4.0

# Points refresh on :00/:15/:30/:45 — match that cadence for long collection.
DEFAULT_INTERVAL_SECONDS = 900
