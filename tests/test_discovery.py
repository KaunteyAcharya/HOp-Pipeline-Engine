import csv
import gzip
from pathlib import Path

import pytest
from sqlalchemy import select

from hostop.db import init_db, session_scope
from hostop.discovery.base import RawOperator
from hostop.discovery.growth import compute_growth
from hostop.discovery.inside_airbnb import InsideAirbnbCollector
from hostop.discovery.permits import PermitCollector, PermitMapping
from hostop.models import FieldProvenance, Operator, OperatorSource, Signal
from hostop.resolve.entity_resolution import resolve
from hostop.resolve.normalize import is_distinctive, normalize_domain, normalize_name

HEADER = ["id", "host_id", "host_name", "host_url", "calculated_host_listings_count", "last_scraped"]


def _write_listings(path: Path, rows: list[list[object]], gz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if gz else open
    with opener(path, "wt", newline="", encoding="utf-8") as fh:  # type: ignore[operator]
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)


@pytest.fixture()
def db(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'd.db'}"
    init_db(url)
    return url


# --- normalize -------------------------------------------------------------------------------

def test_normalize_name_strips_legal_suffixes() -> None:
    assert normalize_name("Harbor Stays, LLC") == normalize_name("harbor stays inc.") == "harbor stays"
    assert normalize_name("Sun & Sand Co") == "sun and sand"


def test_normalize_domain() -> None:
    assert normalize_domain("https://www.HarborStays.com/about") == "harborstays.com"
    assert normalize_domain("harborstays.com") == "harborstays.com"
    assert normalize_domain("") is None


def test_is_distinctive() -> None:
    assert not is_distinctive("john")
    assert is_distinctive("harbor stays")


# --- Inside Airbnb loader ----------------------------------------------------------------------

def test_inside_airbnb_groups_by_host_and_filters_band(tmp_path: Path) -> None:
    root = tmp_path / "iab"
    _write_listings(root / "nashville" / "2026-09-15" / "listings.csv.gz", [
        [1, "10", "Harbor Stays", "u10", 25, "2026-09-15"],
        [2, "10", "Harbor Stays", "u10", 25, "2026-09-15"],
        [3, "11", "Solo Host", "u11", 2, "2026-09-15"],      # below band
        [4, "12", "Mega Corp", "u12", 900, "2026-09-15"],    # above band
        [5, "13", "Edge Ten", "u13", 10, "2026-09-15"],      # band edge inclusive
    ], gz=True)
    out = list(InsideAirbnbCollector(root, 10, 500).collect())
    assert {r.raw["host_id"]: r.listing_count for r in out} == {"10": 25, "13": 10}
    r = next(x for x in out if x.raw["host_id"] == "10")
    assert r.city == "Nashville" and r.snapshot == "2026-09-15"
    assert r.strong_ids == {"airbnb_host": "10"} and "CC BY 4.0" in r.raw["attribution"]


def test_inside_airbnb_missing_columns_raises(tmp_path: Path) -> None:
    p = tmp_path / "iab" / "x" / "listings.csv"
    p.parent.mkdir(parents=True)
    p.write_text("id,host_name\n1,a\n")
    with pytest.raises(ValueError):
        list(InsideAirbnbCollector(tmp_path / "iab", 10, 500).collect())


# --- permits -----------------------------------------------------------------------------------

def test_permit_importer_groups_and_filters_status(tmp_path: Path) -> None:
    f = tmp_path / "p.csv"
    rows = [["P1", "Harbor Stays LLC", "harborstays.com", "ISSUED"]] * 12
    rows += [["P2", "Harbor Stays LLC", "", "EXPIRED"]] * 5
    rows += [["P3", "Tiny Host", "", "ISSUED"]] * 2
    with open(f, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "Holder", "Web", "Status"])
        w.writerows(rows)
    m = PermitMapping(file="p.csv", columns={"operator_name": "Holder", "website": "Web", "permit_id": "id",
                                             "status": "Status"},
                      active_statuses=["ISSUED"], defaults={"city": "Nashville", "country": "US"})
    out = list(PermitCollector(m, 10, 500, base_dir=tmp_path).collect())
    assert len(out) == 1
    assert out[0].listing_count == 12 and out[0].domain == "harborstays.com" and out[0].country == "US"


# --- entity resolution -------------------------------------------------------------------------

def _raw(source: str, key: str, name: str, **kw: object) -> RawOperator:
    return RawOperator(source=source, source_key=key, name=name, **kw)  # type: ignore[arg-type]


def test_resolution_merges_by_domain_fuzzy_and_strong_id(db: str) -> None:
    with session_scope(db) as s:
        stats = resolve(s, [
            _raw("inside_airbnb", "Nashville|1|a", "Harbor Stays", city="Nashville", listing_count=20,
                 strong_ids={"airbnb_host": "1"}),
            _raw("inside_airbnb", "Austin|1|a", "Harbor Stays", city="Austin", listing_count=15,
                 strong_ids={"airbnb_host": "1"}),                       # same host, other city
            _raw("permit", "p|harbor", "Harbor Stays, LLC", domain="harborstays.com", country="US",
                 listing_count=30),                                       # fuzzy name
            _raw("web_search", "w|1", "HS Rentals", domain="https://www.harborstays.com"),  # domain
            _raw("inside_airbnb", "Denver|2|a", "John", listing_count=12, strong_ids={"airbnb_host": "2"}),
            _raw("inside_airbnb", "Denver|3|a", "John", listing_count=14, strong_ids={"airbnb_host": "3"}),
        ])
        assert stats.created == 3 and stats.merged == 3
        harbor = s.scalars(select(Operator).where(Operator.domain == "harborstays.com")).one()
        assert sorted(harbor.cities) == ["Austin", "Nashville"]
        assert harbor.listing_count == 30
        assert {src.source for src in harbor.sources} == {"inside_airbnb", "permit", "web_search"}
        prov = s.scalars(select(FieldProvenance).where(FieldProvenance.operator_id == harbor.id,
                                                       FieldProvenance.field == "domain")).all()
        assert {p.source for p in prov} == {"permit", "web_search"}
        assert s.query(Operator).filter(Operator.normalized_name == "john").count() == 2  # not fuzzy-merged


def test_resolution_respects_country_conflict(db: str) -> None:
    with session_scope(db) as s:
        stats = resolve(s, [_raw("permit", "a", "Harbor Stays Group", country="US"),
                            _raw("permit", "b", "Harbor Stays Group", country="CA")])
        assert stats.created == 2


def test_resolution_is_idempotent(db: str) -> None:
    r = _raw("permit", "a", "Harbor Stays Group", country="US")
    with session_scope(db) as s:
        resolve(s, [r])
    with session_scope(db) as s:
        stats = resolve(s, [r])
        assert stats.skipped_existing == 1 and s.query(OperatorSource).count() == 1


def test_synthetic_flag_cleared_when_real_source_merges(db: str) -> None:
    with session_scope(db) as s:
        resolve(s, [_raw("permit", "a", "Harbor Stays Group", is_synthetic=True),
                    _raw("permit", "b", "Harbor Stays Group")])
        assert s.query(Operator).one().is_synthetic is False


def test_growth_signal_between_snapshots(tmp_path: Path, db: str) -> None:
    root = tmp_path / "iab"
    _write_listings(root / "austin" / "2026-03-15" / "listings.csv", [[1, "7", "Juniper Homes", "u", 12, "x"]])
    _write_listings(root / "austin" / "2026-09-15" / "listings.csv", [[1, "7", "Juniper Homes", "u", 19, "x"]])
    with session_scope(db) as s:
        resolve(s, InsideAirbnbCollector(root, 10, 500).collect())
        assert compute_growth(s) == 1
        sig = s.scalars(select(Signal)).one()
        assert sig.value == 7 and "2026-03-15" in (sig.detail or "")
        assert compute_growth(s) == 1  # rerun does not duplicate
