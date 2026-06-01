#!/usr/bin/env python3
"""Convert a place-suggestion issue into a row in data/places.csv."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from event_utils import parse_issue_form_markdown

CSV_COLUMNS = [
    "Name",
    "Category",
    "Neighborhood",
    "Address",
    "Link",
    "Google Maps",
    "From UN HQ",
    "Why it is good",
    "Dietary notes",
    "Tips",
]

FIELD_MAP = {
    "place name": "Name",
    "category": "Category",
    "neighborhood": "Neighborhood",
    "address": "Address",
    "website (optional)": "Link",
    "distance / travel time from un hq": "From UN HQ",
    "why is it good for osw attendees?": "Why it is good",
    "dietary notes (optional)": "Dietary notes",
    "tips (optional)": "Tips",
}


def place_exists(rows: list[dict], name: str) -> bool:
    return any(r.get("Name", "").strip().lower() == name.strip().lower() for r in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a place-suggestion issue into places.csv")
    parser.add_argument("--issue-body-file", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--places-file", required=True)
    args = parser.parse_args()

    issue_body = Path(args.issue_body_file).read_text(encoding="utf-8")
    fields = parse_issue_form_markdown(issue_body)

    if "place name" not in fields:
        raise ValueError("Submission is missing required field: place name")
    if "address" not in fields:
        raise ValueError("Submission is missing required field: address")

    places_path = Path(args.places_file)
    existing_rows: list[dict] = []
    if places_path.exists():
        with places_path.open(newline="", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    name = fields["place name"]
    if place_exists(existing_rows, name):
        print(f"Place '{name}' already exists in {args.places_file}; skipping.")
        return 0

    new_row: dict[str, str] = {col: "" for col in CSV_COLUMNS}
    for issue_field, csv_col in FIELD_MAP.items():
        if issue_field in fields:
            new_row[csv_col] = fields[issue_field]

    # Generate a basic Google Maps link from the address
    address = new_row.get("Address", "")
    if address:
        import urllib.parse
        new_row["Google Maps"] = (
            "https://maps.google.com/maps?q=" + urllib.parse.quote_plus(address)
        )

    existing_rows.append(new_row)

    places_path.parent.mkdir(parents=True, exist_ok=True)
    with places_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing_rows)

    print(f"Added '{name}' (issue #{args.issue_number}) to {args.places_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
