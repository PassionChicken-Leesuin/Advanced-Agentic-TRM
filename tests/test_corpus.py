from collections import Counter
from datetime import date
from pathlib import Path

from trmkb.corpus.common import CorpusDoc, read_doc, rebuild_index
from trmkb.corpus.edgar import _strip_exhibit_header, html_to_text
from trmkb.corpus.ionq_web import parse_post
from trmkb.corpus.synth import DOC_TYPES, load_ledger, plan
from trmkb.schema import SourceType


def test_frontmatter_roundtrip(tmp_path: Path):
    root = tmp_path / "corpus"
    d = CorpusDoc(id="syn_meeting_2024-05-01_01", title="Weekly: hardware", source_type=SourceType.SYN_MEETING,
                  date=date(2024, 5, 1), url=None, body="Line 1\n\nLine 2 with 한글", is_synthetic=True,
                  planted_fact_ids=["pf01"], extra={"doc_type": "syn_meeting"})
    p = d.write(root)
    assert p == root / "synthetic" / "syn_meeting_2024-05-01_01.md"
    fm, body = read_doc(p)
    assert fm["planted_fact_ids"] == ["pf01"] and fm["is_synthetic"] is True and body.strip().endswith("한글")
    idx = rebuild_index(root)
    lines = idx.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and '"source_type":"syn_meeting"' in lines[0]


def test_edgar_html_to_text_tables_and_header():
    html = """<html><head><style>x{}</style></head><body>
    <p>EX-99.1</p><p>2</p><p>d1234dex991.htm</p>
    <p>IonQ Announces Something <b>Big</b></p>
    <table><tr><th>Metric</th><th>2023</th></tr><tr><td>Revenue</td><td>$22.0M</td></tr></table>
    <div style="display:none">hidden xbrl</div></body></html>"""
    text = _strip_exhibit_header(html_to_text(html))
    assert text.startswith("IonQ Announces Something Big")
    assert "Metric | 2023" in text and "Revenue | $22.0M" in text
    assert "hidden xbrl" not in text


def test_ionq_web_parse_post():
    html = """<html><head><title>IonQ | Test</title></head><body>
    <header>nav</header>
    <div class="main-wrapper"><h1>Scaling Roadmap</h1><p>December 9, 2020</p>
    <p>First paragraph of body.</p><h2>Section</h2><ul><li>bullet one</li></ul>
    <h2>Related blogs</h2><p>February 23, 2022</p><p>should be dropped</p></div></body></html>"""
    title, d, body = parse_post(html)
    assert title == "Scaling Roadmap" and d == date(2020, 12, 9)
    assert "First paragraph" in body and "## Section" in body and "- bullet one" in body
    assert "should be dropped" not in body


def test_synth_plan_constraints():
    ledger = load_ledger()
    facts = {f["id"]: f for f in ledger["facts"]}
    specs = plan(ledger)
    assert len(specs) == sum(v["count"] for v in DOC_TYPES.values())
    c = Counter(fid for s in specs for fid in s.fact_ids)
    assert set(c) == set(facts), "every fact planted"
    assert max(c.values()) <= 4
    for s in specs:
        for fid in s.fact_ids:
            f = facts[fid]
            assert s.date >= date.fromisoformat(f["not_before"]), (s.doc_id, fid)
            if "not_after" in f:
                assert s.date <= date.fromisoformat(f["not_after"]), (s.doc_id, fid)
            assert f["expected_node_type"] in DOC_TYPES[s.doc_type]["affinity"]
            if f.get("contradicts"):
                assert f["contradicts"] not in s.fact_ids
    first = {}
    for s in specs:
        for fid in s.fact_ids:
            first[fid] = min(first.get(fid, s.date), s.date)
    for a, b in (("pf07", "pf08"), ("pf20", "pf21"), ("pf02", "pf41")):
        assert first[a] < first[b], f"contradiction order {a}<{b}"
    # 결정적
    assert [s.doc_id for s in plan(ledger)] == [s.doc_id for s in specs]
