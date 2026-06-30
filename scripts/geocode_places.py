#!/usr/bin/env python3
"""
geocode_places.py — Fill in missing Latitude/Longitude values in data/places_with_coords.csv.

Reads data/places.csv, looks up coordinates for any row that is missing them
using the free Nominatim OpenStreetMap geocoding API, and writes the result to
data/places_with_coords.csv.

Usage:
    pip install requests
    python scripts/geocode_places.py

The Nominatim API is free but rate-limited to 1 request/second and requires a
descriptive User-Agent string. This script respects that limit automatically.
"""

import csv
import os
import time
import requests

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
INPUT_CSV   = os.path.join(REPO_ROOT, "data", "places.csv")
OUTPUT_CSV  = os.path.join(REPO_ROOT, "data", "places_with_coords.csv")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT    = "OSW_plus-places-geocoder/1.0 (https://github.com/mgifford/unosw.plus)"
RATE_LIMIT_S  = 1.1  # seconds between requests (Nominatim policy: max 1 req/s)


def geocode(address: str) -> tuple[float, float] | tuple[None, None]:
    """Return (lat, lon) for *address*, or (None, None) on failure."""
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except requests.RequestException as exc:
        print(f"  ⚠  Network error geocoding '{address}': {exc}")
    except (KeyError, ValueError, IndexError) as exc:
        print(f"  ⚠  Unexpected response geocoding '{address}': {exc}")
    return None, None


def load_existing_coords(path: str) -> dict[str, tuple[float, float]]:
    """Load existing name→(lat,lon) mapping from the output CSV (if it exists)."""
    existing: dict[str, tuple[float, float]] = {}
    if not os.path.exists(path):
        return existing
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lat_str = row.get("Latitude", "").strip()
            lon_str = row.get("Longitude", "").strip()
            if lat_str and lon_str:
                try:
                    existing[row["Name"]] = (float(lat_str), float(lon_str))
                except ValueError:
                    pass
    return existing


def main() -> None:
    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"Input CSV not found: {INPUT_CSV}")

    existing_coords = load_existing_coords(OUTPUT_CSV)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if "Latitude" not in fieldnames:
        fieldnames.append("Latitude")
    if "Longitude" not in fieldnames:
        fieldnames.append("Longitude")

    enriched = []
    for row in rows:
        name    = row.get("Name", "").strip()
        address = row.get("Address", "").strip()

        # Use previously-geocoded coords if available
        if name in existing_coords:
            lat, lon = existing_coords[name]
            print(f"  ✔  {name} — using cached ({lat}, {lon})")
        elif address:
            print(f"  🔍  Geocoding: {name} | {address}")
            lat, lon = geocode(address)
            if lat is not None:
                print(f"      → ({lat}, {lon})")
            else:
                print(f"      → not found")
            time.sleep(RATE_LIMIT_S)
        else:
            lat, lon = None, None
            print(f"  –   No address for '{name}'; skipping.")

        row["Latitude"]  = lat if lat is not None else ""
        row["Longitude"] = lon if lon is not None else ""
        enriched.append(row)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(enriched)

    print(f"\n✅  Written {len(enriched)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
