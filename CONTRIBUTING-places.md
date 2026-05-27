# Contributing Places to OSW+ NYC

OSW+ NYC maintains a community-curated list of coffee spots, food options, parks, and evening venues near the UN for attendees of [UN Open Source Week](https://www.un.org/en/open-source-week).

> **Inspired by** [Food-W3C-Kobe](https://github.com/mgifford/Food-W3C-Kobe) — a similar guide used at W3C TPAC 2025.

---

## What kinds of places belong here?

| Category | Examples |
|----------|---------|
| **Coffee** | Specialty cafés with WiFi & seating for informal chats |
| **Food** | Affordable sit-down spots for a working lunch |
| **Quick Bites** | Street food, food trucks, counter service |
| **Restaurant** | Nicer options for dinners or delegation meals |
| **Bar** | Pubs, beer bars, cocktail spots for evening networking |
| **Park** | Outdoor spaces for walking meetings or decompression |

Please keep suggestions within **~20 minutes walk or one subway stop** of the UN (405 E 42nd St, Midtown East).

---

## Option A — Submit via GitHub Issue (easiest)

Open a new issue using the **[Suggest a Place](https://github.com/mgifford/OSW_plus/issues/new?template=submit-place.yml)** template and fill in the form. A maintainer will add it to the map.

---

## Option B — Submit a Pull Request

1. **Fork** this repository.
2. **Create a Markdown file** in `data/places/` using a short hyphenated name, e.g. `my-favorite-spot.md`.
3. **Copy and fill in the template below:**

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

4. **Add a row** to `data/places.csv` following the existing schema:
   ```
   Name,Category,Neighborhood,Address,Link,Google Maps,From UN HQ,Why it is good,Dietary notes,Tips
   ```

5. **(Optional)** If you know the coordinates, also add a row to `data/places_with_coords.csv` with `Latitude` and `Longitude` appended. If you skip this step, a maintainer or the `scripts/geocode_places.py` script will fill them in.

6. **Open a pull request** with a short description of the place.

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

Open a [GitHub Discussion](https://github.com/mgifford/OSW_plus/discussions) or ping the maintainers in the issue tracker.
