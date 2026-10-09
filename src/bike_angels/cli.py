from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rich.console import Console

from .auth import AuthClient
from .collector import collect_once
from .config import DEFAULT_INTERVAL_SECONDS, TOKEN_PATH
from .db import Database

console = Console()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bike-angels",
        description="Collect Bay Wheels Bike Angels station data",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    login_p = sub.add_parser("login", help="Authenticate via SMS OTP")
    login_p.add_argument(
        "--phone",
        required=True,
        help="Phone in E.164 format, e.g. +14155551234",
    )
    login_p.add_argument("--code", help="OTP code (if already received)")
    login_p.add_argument("--email", help="Email if Lyft asks for email_match")

    sub.add_parser("collect", help="Run one collection snapshot")

    loop_p = sub.add_parser("loop", help="Collect repeatedly until stopped")
    loop_p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between snapshots (default {DEFAULT_INTERVAL_SECONDS})",
    )
    loop_p.add_argument(
        "--duration-days",
        type=float,
        default=14.0,
        help="Stop after this many days (default 14)",
    )

    sub.add_parser("status", help="Show DB / token status")

    probe_p = sub.add_parser(
        "probe",
        help="Fetch one map tile and print reward sample JSON",
    )
    probe_p.add_argument("--lat", type=float, default=37.7749)
    probe_p.add_argument("--lon", type=float, default=-122.4194)

    args = parser.parse_args(argv)

    if args.command == "login":
        return cmd_login(args.phone, args.code, args.email)
    if args.command == "collect":
        return cmd_collect()
    if args.command == "loop":
        return cmd_loop(args.interval, args.duration_days)
    if args.command == "status":
        return cmd_status()
    if args.command == "probe":
        return cmd_probe(args.lat, args.lon)
    return 1


def cmd_login(phone: str, code: str | None, email: str | None) -> int:
    with AuthClient() as auth:
        if not code:
            console.print(f"Requesting OTP for [bold]{phone}[/bold]...")
            auth.request_code(phone)
            code = console.input("Enter SMS code: ").strip()
        console.print("Verifying...")
        try:
            tokens = auth.login(phone, code, email=email)
        except RuntimeError as exc:
            msg = str(exc)
            if "Email verification required" in msg and not email:
                email = console.input("Enter account email: ").strip()
                tokens = auth.login(phone, code, email=email)
            else:
                console.print(f"[red]{msg}[/red]")
                return 1
        console.print(
            f"[green]Logged in.[/green] Token saved to {TOKEN_PATH}\n"
            f"expires_at={tokens.expires_at} "
            f"has_refresh={bool(tokens.refresh_token)}"
        )
    return 0


def cmd_collect() -> int:
    console.print("Collecting Bay Wheels Bike Angels snapshot...")
    try:
        result = collect_once()
    except Exception as exc:
        console.print(f"[red]Collect failed:[/red] {exc}")
        return 1
    console.print_json(data=result)
    return 0


def cmd_loop(interval: int, duration_days: float) -> int:
    end_at = time.time() + duration_days * 86400
    console.print(
        f"Looping every {interval}s for up to {duration_days} days "
        f"(Ctrl+C to stop)"
    )
    with AuthClient() as auth, Database() as db:
        while time.time() < end_at:
            started = time.time()
            try:
                result = collect_once(auth=auth, db=db)
                console.print(
                    f"[green]ok[/green] snapshot={result['snapshot_id']} "
                    f"stations={result['station_count']} "
                    f"rewarded={result['rewarded_count']} "
                    f"local={result['local_time']}"
                )
            except Exception as exc:
                console.print(f"[red]error[/red] {exc}")
            elapsed = time.time() - started
            sleep_for = max(0.0, interval - elapsed)
            try:
                time.sleep(sleep_for)
            except KeyboardInterrupt:
                console.print("\nStopped.")
                return 0
    console.print("Duration complete.")
    return 0


def cmd_status() -> int:
    token_ok = Path(TOKEN_PATH).exists()
    console.print(f"token_file: {TOKEN_PATH} exists={token_ok}")
    if token_ok:
        with AuthClient() as auth:
            t = auth.tokens
            if t:
                console.print(
                    f"access_token: present expired={t.is_expired} "
                    f"refresh={bool(t.refresh_token)}"
                )
    with Database() as db:
        console.print_json(data=db.summary())
    return 0


def cmd_probe(lat: float, lon: float) -> int:
    from .client import LyftMapClient

    with AuthClient() as auth, LyftMapClient(auth) as client:
        payload = client.map_items(lat, lon)
        items = payload.get("map_items") or []
        rewarded = []
        for item in items:
            pin = (
                (item.get("collapsible_collection_bubble") or {})
                .get("selected_detailed_text_specific_pin")
                or {}
            )
            badge = pin.get("reward_badge")
            if badge:
                rewarded.append(
                    {
                        "device_id": (item.get("device") or {}).get("id"),
                        "location": item.get("location"),
                        "reward_badge": badge,
                        "availability": pin.get("text_specific_items"),
                    }
                )
        console.print(
            f"map_items={len(items)} rewarded={len(rewarded)} "
            f"at ({lat}, {lon})"
        )
        console.print(json.dumps(rewarded[:5], indent=2))
        # Also dump inventory keys for inspection.
        try:
            inv = client.inventory(lat, lon)
            console.print(f"inventory top-level keys: {list(inv.keys())}")
            raw = inv.get("map_inventory_json")
            if isinstance(raw, str):
                import json as _json

                data = _json.loads(raw)
                feats = data.get("features") or []
                console.print(f"inventory features={len(feats)}")
                if feats:
                    console.print(
                        "sample props keys:",
                        sorted((feats[0].get("properties") or {}).keys()),
                    )
                    sample = json.dumps(feats[0].get("properties") or {}, indent=2)
                    console.print(sample[:2000])
        except Exception as exc:
            console.print(f"inventory probe failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
