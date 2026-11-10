"""City STR permit / registry open-data CSV importer with configurable column mapping.

Mapping file (config/permit_mappings/<name>.yaml):
    file: data/permits/nashville_str_permits.csv
    source_url: https://data.example.gov/...      # the dataset landing page, for provenance
    snapshot: "2026-10-01"
    columns:
      operator_name: "Permit Holder"              # required
      city: "City"                                # optional
      website: "Website"                          # optional
      permit_id: "Permit #"                       # optional
      status: "Status"                            # optional
    active_statuses: ["ISSUED", "ACTIVE"]         # optional filter on status column
    defaults: { city: Nashville, country: US }
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, Field

from hostop.discovery.base import RawOperator
from hostop.resolve.normalize import normalize_domain, normalize_name


class PermitMapping(BaseModel):
    file: str
    source_url: str | None = None
    snapshot: str | None = None
    columns: dict[str, str]
    active_statuses: list[str] = Field(default_factory=list)
    defaults: dict[str, str] = Field(default_factory=dict)


def load_mapping(path: Path) -> PermitMapping:
    with open(path, encoding="utf-8") as fh:
        return PermitMapping.model_validate(yaml.safe_load(fh))


class PermitCollector:
    name = "permit"

    def __init__(
        self, mapping: PermitMapping, min_listings: int, max_listings: int,
        base_dir: Path = Path("."), synthetic: bool = False,
    ) -> None:
        self.synthetic = synthetic
        if "operator_name" not in mapping.columns:
            raise ValueError("permit mapping must define columns.operator_name")
        self.m, self.min_listings, self.max_listings, self.base_dir = mapping, min_listings, max_listings, base_dir

    def collect(self) -> Iterable[RawOperator]:
        cols = self.m.columns
        df = pd.read_csv(self.base_dir / self.m.file, dtype=str).fillna("")
        if self.m.active_statuses and "status" in cols:
            ok = {s.upper() for s in self.m.active_statuses}
            df = df[df[cols["status"]].str.upper().isin(ok)]
        df["_name"] = df[cols["operator_name"]].str.strip()
        df = df[df["_name"] != ""]
        df["_norm"] = df["_name"].map(normalize_name)
        for norm, grp in df.groupby("_norm"):
            count = len(grp)
            if not (self.min_listings <= count <= self.max_listings):
                continue
            first: dict[str, Any] = {str(k): v for k, v in grp.iloc[0].to_dict().items()}
            city = first.get(cols.get("city", ""), "") or self.m.defaults.get("city")
            permit_ids = [str(x) for x in grp[cols["permit_id"]].tolist()][:50] if "permit_id" in cols else []
            website = first.get(cols.get("website", ""), "") or None
            yield RawOperator(
                source="permit",
                source_key=f"{self.m.file}|{norm}",
                name=str(first["_name"]),
                domain=normalize_domain(website),
                city=city or None,
                country=self.m.defaults.get("country"),
                listing_count=count,
                source_url=self.m.source_url,
                snapshot=self.m.snapshot,
                is_synthetic=self.synthetic,
                raw={"permit_count": count, "file": self.m.file, "permit_ids": permit_ids},
            )
