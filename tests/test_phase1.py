from pathlib import Path

import pytest
from sqlalchemy import inspect

from hostop.config import ICP, load_config
from hostop.db import init_db, session_scope
from hostop.models import Operator

ROOT = Path(__file__).resolve().parents[1]


def test_config_loads() -> None:
    cfg = load_config(ROOT / "config" / "hostop.yaml")
    assert cfg.icp.min_listings == 10 and cfg.icp.max_listings == 500
    assert "Guesty" in cfg.pms_tech and "Escapia" in cfg.pms_tech
    assert "airbnb.com" in cfg.fetch.blocked_domains


def test_icp_band_validation() -> None:
    with pytest.raises(ValueError):
        ICP(min_listings=10, max_listings=500, ideal_min=200, ideal_max=100)


def test_db_roundtrip(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 't.db'}"
    engine = init_db(url)
    assert "operators" in inspect(engine).get_table_names()
    with session_scope(url) as s:
        s.add(Operator(name="Test Co", normalized_name="test", is_synthetic=True))
    with session_scope(url) as s:
        assert s.query(Operator).one().is_synthetic is True
