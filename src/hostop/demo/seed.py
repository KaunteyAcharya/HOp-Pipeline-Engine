"""SYNTHETIC demo data generator.

Writes fake Inside Airbnb-shaped files and a fake permit CSV so `--demo` exercises the real loaders.
Every name is invented, every domain uses the reserved `.example` TLD, and every URL points at
synthetic.example. Nothing here describes a real operator.
"""

from __future__ import annotations

import csv
import gzip
import random
from pathlib import Path
from typing import Any

DEMO_DIR = Path(".demo_data")
SYN_URL = "https://synthetic.example"

_A = ["Harbor", "Summit", "Pine", "Coastal", "Lakeside", "Juniper", "Copper", "Maple", "Ridge", "Bluebird",
      "Sandpiper", "Cedar", "Willow", "Granite", "Riverbend", "Oak", "Driftwood", "Sage", "Aspen",
      "Magnolia", "Canyon", "Lantern", "Meadow", "Northstar", "Saltwater", "Foxglove", "Ironwood", "Starling",
      "Tidewater", "Kestrel"]
_B = ["Stays", "Vacation Rentals", "Hospitality", "Property Management", "Getaways", "Retreats", "Homes",
      "Rentals Co", "Hosting", "Escapes", "Lodging", "Collective"]
CITIES = {"nashville": "US", "austin": "US", "denver": "US", "broward-county": "US", "toronto": "CA"}
SNAPSHOTS = ["2026-03-15", "2026-09-15"]


def _count(rng: random.Random) -> int:
    """Long-tail listing counts: most hosts are tiny, a minority are in the 10-500 band."""
    return max(1, min(700, int(rng.lognormvariate(1.6, 1.25))))


def generate(root: Path = DEMO_DIR, n_hosts: int = 5200, seed: int = 42) -> Path:
    rng = random.Random(seed)
    names = [f"{a} {b}" for a in _A for b in _B]
    rng.shuffle(names)
    hosts: list[dict[str, Any]] = []
    for i in range(n_hosts):
        named = i < len(names)
        hosts.append({
            "host_id": str(900000 + i),
            "host_name": names[i] if named else rng.choice(["Alex", "Sam", "Jordan", "Casey", "Riley", "Taylor"]),
            "count": _count(rng),
            "cities": rng.sample(list(CITIES), 2 if rng.random() < 0.12 else 1),
        })
    iab = root / "inside_airbnb"
    for city in CITIES:
        for snap in SNAPSHOTS if city in ("nashville", "austin") else SNAPSHOTS[-1:]:
            out = iab / city / snap
            out.mkdir(parents=True, exist_ok=True)
            with gzip.open(out / "listings.csv.gz", "wt", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["id", "host_id", "host_name", "host_url", "calculated_host_listings_count", "last_scraped"])
                lid = 0
                for h in hosts:
                    if city not in h["cities"]:
                        continue
                    count = h["count"]
                    if snap == SNAPSHOTS[0]:
                        count = max(1, int(count * rng.uniform(0.7, 1.0)))
                    for _ in range(min(count, 3)):  # a few rows per host is enough; count column carries total
                        lid += 1
                        w.writerow([lid, h["host_id"], h["host_name"], f"{SYN_URL}/host/{h['host_id']}", count, snap])

    # Permit registry: overlaps partly with named Airbnb hosts (with legal suffixes) plus permit-only operators.
    pdir = root / "permits"
    pdir.mkdir(parents=True, exist_ok=True)
    named_hosts = [h for h in hosts if " " in h["host_name"]]
    overlap = rng.sample(named_hosts, 120)
    permit_only = [f"{a} {b}" for a in _A for b in ("Suites", "Cottages", "Lofts")][:80]
    with open(pdir / "synthetic_permits.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Permit #", "Permit Holder", "City", "Website", "Status"])
        pid = 0
        for h in overlap:
            holder = h["host_name"] + rng.choice([" LLC", ", Inc.", "", " Ltd"])
            site = h["host_name"].lower().replace(" ", "") + ".example"
            for _ in range(max(10, min(h["count"], 60))):
                pid += 1
                w.writerow([f"SYN-{pid}", holder, "Nashville", site if rng.random() < 0.8 else "", "ISSUED"])
        for name in permit_only:
            for _ in range(rng.randint(5, 40)):
                pid += 1
                w.writerow([f"SYN-{pid}", name, "Nashville", name.lower().replace(" ", "") + ".example",
                            rng.choice(["ISSUED", "ISSUED", "EXPIRED"])])
    (root / "permit_mapping.yaml").write_text(
        "file: permits/synthetic_permits.csv\n"
        f"source_url: {SYN_URL}/permits\n"
        'snapshot: "2026-10-01"\n'
        "columns: {operator_name: 'Permit Holder', city: City, website: Website,"
        " permit_id: 'Permit #', status: Status}\n"
        "active_statuses: [ISSUED]\n"
        "defaults: {city: Nashville, country: US}\n",
        encoding="utf-8",
    )
    return root
