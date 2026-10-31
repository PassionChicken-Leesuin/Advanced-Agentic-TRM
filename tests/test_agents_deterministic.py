from datetime import date

from trmkb.agents.chunker import Chunk, chunk_document, chunk_text, select_sec_sections
from trmkb.agents.linker import layer_ok
from trmkb.agents.reader import locate_quote
from trmkb.agents.timeparse import parse_time
from trmkb.agents import timing
from trmkb.schema import (
    CapabilityClaim, CapabilityNode, CriticStatus, DriverNode, Edge, MilestoneNode, Modality, OpportunityNode,
    RelationType, StatementClaim, TimeExpr, TimeExprKind,
)
from trmkb.store import KBStore


def test_parse_time_forms():
    assert (parse_time("Q2 2025").start, parse_time("Q2 2025").end) == (2025.25, 2025.5)
    assert (parse_time("H2 2025").start, parse_time("H2 2025").end) == (2025.5, 2026.0)
    assert (parse_time("second half of 2025").start) == 2025.5
    assert parse_time("by end of 2028").end >= 2028.9 and parse_time("by 2028").start is None and parse_time("by 2028").end == 2028.99
    assert (parse_time("2025-2030").start, parse_time("2025-2030").end) == (2025.0, 2031.0)
    assert parse_time("mid-2026").start == 2026.4
    assert parse_time("September 2024").start == 2024 + 8 / 12
    assert parse_time("2027").start == 2027.0 and parse_time("2027").kind == TimeExprKind.ABSOLUTE
    rel = parse_time("within 2 years", date(2024, 7, 1))
    assert rel.kind == TimeExprKind.RELATIVE and rel.lag_years == 2 and rel.start == 2024.5
    band = parse_time("long-term", date(2024, 1, 1))
    assert band.kind == TimeExprKind.BAND and band.start == 2029
    assert parse_time("someday").kind == TimeExprKind.UNKNOWN and parse_time(None).kind == TimeExprKind.UNKNOWN


def test_chunk_text_respects_paragraphs_and_offsets():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 120 for i in range(10))
    chunks = chunk_text(text, target_chars=1500)
    assert len(chunks) >= 4
    for c in chunks:
        assert text[c.start:c.end].strip() == c.text
        assert len(c.text) <= 1500 * 1.7
    assert [c.idx for c in chunks] == list(range(len(chunks)))


def test_sec_sections_skip_toc():
    toc = "Item 1. | Business | 5\nItem 1A. | Risk Factors | 16\nItem 7. | Management's Discussion | 40\n"
    body = ("\nItem 1. Business\n" + "We build quantum computers. " * 300 +
            "\nItem 1A. Risk Factors\n" + "Risk text. " * 500 +
            "\nItem 2. Properties\n" + "Office. " * 50 +
            "\nItem 7. Management's Discussion and Analysis\n" + "MD&A text. " * 400 + "\nItem 8. Financial\n")
    secs = select_sec_sections(toc + body)
    names = [s[0] for s in secs]
    assert names == ["business", "risk_factors", "mdna"]
    assert all(e - s > 3000 for _, s, e in secs)
    chunks = chunk_document(toc + body, "sec_filing", target_chars=2000)
    assert {c.section for c in chunks} == {"business", "risk_factors", "mdna"}


def test_locate_quote_exact_normalized_and_fallback():
    ch = Chunk(0, "IonQ targets #AQ 64 by 2025.\nThe Harbor chip reached 23% yield in Q1 2024. Other text here.", 100, 200)
    q, span = locate_quote(ch, "The Harbor chip reached 23% yield in Q1 2024.")
    assert span == (129, 174) and q.startswith("The Harbor")
    q2, _ = locate_quote(ch, "Harbor   chip reached 23% yield")
    assert "Harbor" in q2
    q3, _ = locate_quote(ch, "chip yield reached 23% in Q1 2024 for Harbor")   # 순서 다름 → 문장 대체
    assert q3.startswith("The Harbor")
    q4, span4 = locate_quote(ch, "completely unrelated sentence about bananas")
    assert span4 == (100, 100)


def test_layer_rules():
    why, what, how = DriverNode(label="d"), OpportunityNode(label="o"), CapabilityNode(label="c")
    assert layer_ok(RelationType.DRIVES, why, what)[0]
    assert not layer_ok(RelationType.DRIVES, why, how)[0]
    assert not layer_ok(RelationType.REQUIRES, why, what)[0]
    assert layer_ok(RelationType.REQUIRES, what, how)[0]
    assert layer_ok(RelationType.ENABLES, how, what)[0] and not layer_ok(RelationType.ENABLES, what, how)[0]
    assert layer_ok(RelationType.PRECEDES, how, how)[0] and not layer_ok(RelationType.PRECEDES, what, how)[0]


def test_timing_propagation_and_infeasible(tmp_path):
    kb = KBStore(tmp_path / "r")
    m1 = kb.upsert_node(MilestoneNode(id="m1", label="demo"))
    m2 = kb.upsert_node(MilestoneNode(id="m2", label="first product"))
    prod = kb.upsert_node(OpportunityNode(id="p", label="Tempo"))
    tech = kb.upsert_node(CapabilityNode(id="t", label="electronic control"))
    kb.add_claim(StatementClaim(node_id="m1", text="demo in 2025", modality=Modality.PLANNED, time=TimeExpr.year(2025),
                                doc_id="d", doc_date=date(2024, 1, 1)))
    kb.add_claim(StatementClaim(node_id="p", text="ship 2025.25", modality=Modality.PLANNED,
                                time=TimeExpr(raw="Q2 2025", kind=TimeExprKind.ABSOLUTE, start=2025.25, end=2025.5),
                                doc_id="d", doc_date=date(2024, 1, 1)))
    kb.add_claim(CapabilityClaim(node_id="t", text="ready 2027", measure="x", value="1", modality=Modality.PLANNED,
                                 time=TimeExpr.year(2027), doc_id="d", doc_date=date(2024, 1, 1)))
    kb.add_claim(StatementClaim(node_id="m1", text="vision", modality=Modality.VISION, time=TimeExpr.year(2040),
                                doc_id="d", doc_date=date(2024, 1, 1)))   # vision은 무시
    kb.upsert_edge(Edge(src="m1", dst="m2", type=RelationType.PRECEDES, lag_years=2, critic_status=CriticStatus.ACCEPTED))
    kb.upsert_edge(Edge(src="p", dst="t", type=RelationType.REQUIRES, critic_status=CriticStatus.ACCEPTED))
    kb.upsert_edge(Edge(src="m2", dst="m1", type=RelationType.PRECEDES, critic_status=CriticStatus.PENDING))  # 미수락 무시
    r = timing.recompute(kb)
    assert kb.nodes["m1"].es == 2025.0 and kb.nodes["m1"].ls == 2025.0
    assert kb.nodes["m2"].es == 2027.0            # 2025 + lag 2
    assert "infeasible" in kb.nodes["p"].flags and r["infeasible"][0][:2] == ("p", "t")
    assert kb.time_index["2027"] and r["with_time"] == 4
