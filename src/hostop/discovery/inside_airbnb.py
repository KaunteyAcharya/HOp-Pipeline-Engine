"""Inside Airbnb open-data loader.

Reads listings.csv / listings.csv.gz files that the user downloaded into data/inside_airbnb/.
Makes NO network calls to Airbnb or anywhere else.

ATTRIBUTION: Data from Inside Airbnb (http://insideairbnb.com), licensed CC BY 4.0.

Expected layout: data/inside_airbnb/<city>/<snapshot>/listings.csv[.gz]
(<snapshot> is typically the scrape date, e.g. 2026-09-15). Files directly under <city>/ are also
accepted; the snapshot then falls back to the max `last_scraped` value or the file name.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

import pandas as pd

from hostop.discovery.base import RawOperator

ATTRIBUTION = (
    "Contains data from Inside Airbnb (http://insideairbnb.com), licensed under CC BY 4.0. "
    "Host-level counts are aggregated from public listing data; no calls are made to Airbnb."
)
USECOLS = ["host_id", "host_name", "host_url", "calculated_host_listings_count", "last_scraped"]


def find_files(root: Path) -> list[Path]:
    return sorted([*root.rglob("listings.csv"), *root.rglob("listings.csv.gz")])


def _city_and_snapshot(path: Path, root: Path) -> tuple[str, str | None]:
    parts = path.relative_to(root).parts[:-1]
    city = parts[0] if parts else path.parent.name
    snapshot = parts[1] if len(parts) > 1 else None
    return city.replace("-", " ").replace("_", " ").title(), snapshot


def load_file(
    path: Path, root: Path, min_listings: int, max_listings: int, synthetic: bool = False
) -> Iterator[RawOperator]:
    df = pd.read_csv(path, usecols=lambda c: c in USECOLS, dtype={"host_id": str}, low_memory=False)
    missing = {"host_id", "calculated_host_listings_count"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing required columns {sorted(missing)}")
    city, snapshot = _city_and_snapshot(path, root)
    if snapshot is None:
        snapshot = str(df["last_scraped"].max()) if "last_scraped" in df.columns else path.name
    df["calculated_host_listings_count"] = pd.to_numeric(df["calculated_host_listings_count"], errors="coerce")
    df = df.dropna(subset=["host_id", "calculated_host_listings_count"])
    grouped = df.groupby("host_id").agg(
        host_name=("host_name", "first") if "host_name" in df.columns else ("host_id", "first"),
        host_url=("host_url", "first") if "host_url" in df.columns else ("host_id", "first"),
        count=("calculated_host_listings_count", "max"),
        rows=("host_id", "size"),
    )
    band = grouped[(grouped["count"] >= min_listings) & (grouped["count"] <= max_listings)]
    for host_id, row in band.iterrows():
        hid = str(host_id)
        name = str(row["host_name"]) if pd.notna(row["host_name"]) else f"Airbnb host {hid}"
        yield RawOperator(
            source="inside_airbnb",
            source_key=f"{city}|{hid}|{snapshot}",
            name=name,
            city=city,
            listing_count=int(row["count"]),
            source_url=str(row["host_url"]) if pd.notna(row["host_url"]) else None,
            snapshot=snapshot,
            is_synthetic=synthetic,
            strong_ids={"airbnb_host": hid},
            raw={"host_id": hid, "calculated_host_listings_count": int(row["count"]),
                 "rows_in_file": int(row["rows"]), "file": str(path), "attribution": ATTRIBUTION},
        )


class InsideAirbnbCollector:
    name = "inside_airbnb"

    def __init__(self, root: Path, min_listings: int, max_listings: int, synthetic: bool = False) -> None:
        self.root, self.min_listings, self.max_listings = root, min_listings, max_listings
        self.synthetic = synthetic

    def collect(self) -> Iterable[RawOperator]:
        for path in find_files(self.root):
            yield from load_file(path, self.root, self.min_listings, self.max_listings, self.synthetic)
