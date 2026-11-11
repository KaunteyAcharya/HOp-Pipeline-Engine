from datetime import UTC, datetime, timedelta
from pathlib import Path

from hostop.analytics.funnel import Rate, funnels, weekly_report, wilson
from hostop.db import init_db, session_scope
from hostop.models import Operator, OutreachEvent


def test_wilson_and_small_sample_flag() -> None:
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.35
    assert "SMALL SAMPLE" in Rate(1, 5).fmt() and "SMALL SAMPLE" not in Rate(10, 100).fmt()
    assert Rate(0, 0).fmt() == "n/a (n=0)"


def test_funnel_dedups_and_windows(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'a.db'}"
    init_db(url)
    now = datetime.now(UTC)
    with session_scope(url) as s:
        for i in range(3):
            op = Operator(name=f"o{i}", normalized_name=f"o{i}")
            s.add(op)
            s.flush()
            when = now - timedelta(days=20 if i == 2 else 1)
            for ev in ("sent", "sent", "replied") if i == 0 else ("sent",):
                s.add(OutreachEvent(operator_id=op.id, channel="email", event=ev, hook_id="hiring-abc12345",
                                    occurred_at=when))
    with session_scope(url) as s:
        allf = funnels(s, "segment")[0]
        assert allf.group == "hiring" and allf.counts["sent"] == 3 and allf.counts["replied"] == 1
        recent = funnels(s, "channel", since=now - timedelta(days=7))[0]
        assert recent.counts["sent"] == 2
        text = weekly_report(s, synthetic=True)
    assert "SYNTHETIC DEMO DATA" in text and "1/3 = 33%" in text and "SMALL SAMPLE" in text
