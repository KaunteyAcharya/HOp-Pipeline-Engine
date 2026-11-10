from pathlib import Path

import pytest

from hostop.config import HostOpConfig, load_config
from hostop.db import init_db, session_scope
from hostop.models import Evidence, Operator, Signal
from hostop.scoring.icp import explain, score_all, score_operator

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> HostOpConfig:
    return load_config(ROOT / "config" / "hostop.yaml")


def _op(**kw: object) -> Operator:
    op = Operator(name="X", normalized_name="x", **kw)  # type: ignore[arg-type]
    op.evidence, op.signals = [], []
    return op


def test_ideal_band_beats_icp_band(cfg: HostOpConfig) -> None:
    ideal, _, _ = score_operator(_op(listing_count=40, cities=["A"]), cfg)
    edge, _, _ = score_operator(_op(listing_count=400, cities=["A"]), cfg)
    assert ideal == 30 and edge == 20


def test_out_of_icp_forced_to_c(cfg: HostOpConfig) -> None:
    op = _op(listing_count=900, cities=["A", "B"], direct_booking=True, pms=["Guesty"], domain="x.com")
    total, tier, factors = score_operator(op, cfg)
    assert tier == "C" and "OUTSIDE ICP" in factors[0].reason


def test_unknown_count_scores_zero_band(cfg: HostOpConfig) -> None:
    _, _, factors = score_operator(_op(listing_count=None), cfg)
    assert factors[0].points == 0 and "unknown" in factors[0].reason


def test_tier_a_with_all_signals(cfg: HostOpConfig) -> None:
    op = _op(listing_count=40, cities=["Austin", "Nashville"], direct_booking=True, pms=["Hostaway"],
             domain="op.com")
    op.signals = [Signal(kind="hiring", detail="Guest Experience Coordinator"),
                  Signal(kind="listing_growth", detail="+5")]
    total, tier, factors = score_operator(op, cfg)
    assert tier == "A" and total == 100
    assert {f.factor for f in factors} == {"listing_band", "multi_market", "direct_booking", "pms_detected",
                                           "hiring", "listing_growth", "has_website"}


def test_tier_b_and_c_thresholds(cfg: HostOpConfig) -> None:
    assert score_operator(_op(listing_count=40, domain="a.com"), cfg)[1] == "B"   # 35
    assert score_operator(_op(listing_count=40), cfg)[1] == "C"                   # 30


def test_score_all_and_explain_cite_evidence(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = f"sqlite:///{tmp_path / 's.db'}"
    init_db(url)
    with session_scope(url) as s:
        op = Operator(name="Harbor", normalized_name="harbor", listing_count=40, cities=["A"], direct_booking=True)
        s.add(op)
        s.flush()
        s.add_all([Evidence(operator_id=op.id, kind="listing_count", claim="40 listings", url="u1"),
                   Evidence(operator_id=op.id, kind="direct_booking", claim="booking", url="u2")])
        s.flush()
        oid = op.id
    with session_scope(url) as s:
        assert score_all(s, cfg) == {"A": 0, "B": 1, "C": 0}
        info = explain(s, oid)
    assert info is not None and info["total"] == 45
    band = next(f for f in info["factors"] if f["factor"] == "listing_band")
    assert band["evidence"][0]["url"] == "u1"
