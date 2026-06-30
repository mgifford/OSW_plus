# Contributing Places to OSW+ NYC

OSW+ NYC maintains a community-curated list of coffee spots, food options, parks, and evening venues near the UN for attendees of [UN Open Source Week](https://www.unopensource.org/).

> **Inspired by** [Food-W3C-Kobe](https://github.com/mgifford/Food-W3C-Kobe) — a similar guide used at W3C TPAC 2025.

---

## What kinds of places belong here?

| Category | Examples |
| --------- | -------- |
| **Coffee** | Specialty cafés with WiFi & seating for informal chats |
| **Food** | Affordable sit-down spots for a working lunch |
| **Quick Bites** | Street food, food trucks, counter service |
| **Restaurant** | Nicer options for dinners or delegation meals |
| **Bar** | Pubs, beer bars, cocktail spots for evening networking |
| **Park** | Outdoor spaces for walking meetings or decompression |

Please keep suggestions within **~20 minutes walk or one subway stop** of the UN (405 E 42nd St, Midtown East).

---

## Option A — Submit via GitHub Issue (easiest)

Open a new issue using the **[Suggest a Place](https://github.com/mgifford/unosw.plus/issues/new?template=submit-place.yml)** template and fill in the form. A maintainer will add it to the map.

After the issue is opened, a maintainer reviews it and adds the `approved` label when it is ready to ingest. GitHub Actions then creates a pull request that adds the place to `data/places.csv` and regenerates `data/places_with_coords.csv` so the venue can appear on the map. A maintainer approves that pull request by reviewing it and merging it into `main`.

If the issue is still missing the `approved` label, it will stay in the suggestion backlog and will not be ingested yet.

Maintainer checklist:

1. Confirm the place is near the UN and fits one of the supported categories.
1. Add the `approved` label when the suggestion should be ingested.
1. Run the place workflow for the approved backlog if needed.
1. Review and merge the generated PR.

---

## Option B — Submit a Pull Request

1. **Fork** this repository.
1. **Create a Markdown file** in `data/places/` using a short hyphenated name, e.g. `my-favorite-spot.md`.
1. **Copy and fill in the template below:**

```markdown
Category: <Coffee | Food | Quick Bites | Restaurant | Bar | Park>
Neighborhood: <e.g. Turtle Bay, Midtown East, Grand Central>
Address: <street address, New York, NY ZIP>
Link: <official website or leave blank>
Google Maps: [View on Google Maps](https://maps.google.com/maps?q=<url-encoded address>)

From UN HQ: <~X min walk | ~X min subway>

Why it is good:
- One or two plain sentences on what makes it worth a stop for OSW attendees.

Dietary notes:
- vegan | veg-friendly | gluten-free | halal | n/a

Tips:
- Reservations? Best time? Good for groups? Anything else useful?
```

1. **Add a row** to `data/places.csv` following the existing schema:

   ```markdown
   Name,Category,Neighborhood,Address,Link,Google Maps,From UN HQ,Why it is good,Dietary notes,Tips
   ```

1. **(Optional)** If you know the coordinates, also add a row to `data/places_with_coords.csv` with `Latitude` and `Longitude` appended. If you skip this step, a maintainer or the `scripts/geocode_places.py` script will fill them in.

1. **Open a pull request** with a short description of the place.

---

## Geocoding script

If you have Python 3 installed you can auto-fill coordinates for any entries missing them:

```bash
pip install requests
python scripts/geocode_places.py
```

This reads `data/places.csv`, looks up missing coordinates via the [Nominatim OSM API](https://nominatim.org/release-docs/develop/api/Search/), and writes `data/places_with_coords.csv`.

---

## Questions?

Open a [GitHub Issue](https://github.com/mgifford/unosw.plus/issues) to ask a question or ping the maintainers.
