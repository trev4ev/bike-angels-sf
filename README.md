# bike-angels-sf

Collect Bay Wheels (Lyft Bike) Bike Angels station points over time so you can reverse-engineer the scoring algorithm.

## What it stores

Every snapshot writes one row per station to SQLite:

- timestamp (UTC + local hour/minute/weekday in `America/Los_Angeles`)
- station id/name/lat/lon/capacity (from GBFS)
- bikes / ebikes / open docks / disabled counts
- fill/empty ratios
- Bike Angels `ba_points` (signed: negative=pickup, positive=dropoff), plus derived `pickup_points` / `dropoff_points` and `ba_high_value` (from Lyft inventory)

DB path: `data/bike_angels.sqlite`

## Local quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

bike-angels login --phone +1XXXXXXXXXX
bike-angels probe
bike-angels collect
bike-angels status
```

## Free VPS (Google Cloud e2-micro) — recommended for 2 weeks

### 1. Create the free VM

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create/select a project.
2. Enable **Compute Engine API** if prompted.
3. Go to **Compute Engine → VM instances → Create instance**.
4. Use these settings so it stays free:
   - **Name:** `bike-angels`
   - **Region:** `us-west1` (Oregon) — also free: `us-central1`, `us-east1`
   - **Machine type:** `e2-micro`
   - **Boot disk:** Ubuntu 24.04 LTS, **Standard persistent disk**, 20–30 GB
   - **Firewall:** leave defaults (SSH only is fine)
5. Click **Create**, then **SSH** into the VM from the browser button.

### 2. One-shot setup on the VM

```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/trev4ev/bike-angels-sf.git
cd bike-angels-sf
bash scripts/setup-vps.sh
source .venv/bin/activate
bike-angels login --phone +1XXXXXXXXXX
bike-angels probe
bash scripts/install-cron.sh
```

Cron runs `bike-angels collect` every **15 minutes** at `:05/:20/:35/:50` (just after Lyft's points refresh). Tokens live in `tokens.json` (gitignored); data accumulates in `data/bike_angels.sqlite`.

### 3. Check it’s working

```bash
bike-angels status
tail -f data/cron.log
```

After ~2 weeks, copy the DB down:

```bash
gcloud compute scp bike-angels:~/bike-angels-sf/data/bike_angels.sqlite .
# or use the Cloud Console SSH download
```

Remove cron when done: `crontab -e` and delete the `bike-angels-sf` line.

## Auth notes

Bike Angels is not in public GBFS. Auth uses the Bay Wheels app OAuth client + SMS OTP to your Lyft Bike number. Refresh tokens are saved in `tokens.json` for multi-day collection.

## Commands

| Command | Purpose |
|---------|---------|
| `bike-angels login --phone +1...` | SMS OTP login |
| `bike-angels probe` | Sample downtown SF rewards JSON |
| `bike-angels collect` | One snapshot |
| `bike-angels loop --duration-days 14` | Foreground loop |
| `bike-angels status` | Token + DB summary |

## Caveats

- Undocumented Lyft APIs — personal research use; keep request rates modest.
- Keep `tokens.json` private.
- On GCP free tier: stay on `e2-micro` in an eligible US region; prefer standard disk.
