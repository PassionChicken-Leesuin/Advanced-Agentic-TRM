"""문장이 하나도 없는 문서도 doc.finished 로 닫혀 진행률이 끝까지 차는가 (LLM 호출 없음)."""
import json
from types import SimpleNamespace

from trmkb.sources.build import build_docs
from trmkb.sources.store import SourceStore


class _Ledger:
    total_usd = 0.0

    def dump(self, path):
        pass


def _docs(st):
    for i, date in enumerate(("2021-01-01", "2022-01-01")):
        st.docs[f"d{i}"] = {"id": f"d{i}", "title": f"doc {i}", "date": date, "source_type": "document", "is_synthetic": False, "read": True}
    return sorted(st.docs.values(), key=lambda d: d["date"])


def _finished(st):
    evs = [json.loads(l) for l in (st.dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return [e["doc_id"] for e in evs if e["type"] == "doc.finished"]


def test_empty_documents_are_closed(tmp_path):
    for batch in (1, 20):
        st = SourceStore(tmp_path / f"b{batch}")
        order = _docs(st)
        seen = []
        build_docs(st, SimpleNamespace(ledger=_Ledger()), order, glossary=False, batch=batch, on_doc=lambda d, r, s: seen.append(d["id"]))
        assert sorted(_finished(st)) == ["d0", "d1"]
        assert seen == ["d0", "d1"]
        # 다시 돌려도 두 번 닫지 않음 (재개)
        build_docs(st, SimpleNamespace(ledger=_Ledger()), order, glossary=False, batch=batch)
        assert sorted(_finished(st)) == ["d0", "d1"]
