from pathlib import Path

from hostop.db import init_db, session_scope
from hostop.demo.transcripts import write_transcripts
from hostop.insights.calls import analyze_dir, extract, to_markdown
from hostop.models import CallInsight


def test_rep_lines_ignored_and_tags_found() -> None:
    text = "Rep: we have damage waivers and a great price\nProspect: chasing deposits is painful\n"
    tags = extract("t", text)
    assert [(t.kind, t.tag) for t in tags] == [("pain", "deposits_damage")]


def test_analyze_dir_counts_and_labels(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'i.db'}"
    init_db(url)
    folder = write_transcripts(tmp_path / "t")
    with session_scope(url) as s:
        n, tags = analyze_dir(s, folder, synthetic=True)
        assert n == 3 and s.query(CallInsight).count() == len(tags) > 0
        analyze_dir(s, folder, synthetic=True)  # re-run replaces, does not duplicate
        assert s.query(CallInsight).count() == len(tags)
    md = to_markdown(n, tags, synthetic=True)
    assert "SYNTHETIC" in md and "SMALL SAMPLE" in md and "/3 |" in md
