"""공유 대상(Entity) 연결: 다섯 구조가 같은 대상 id 를 쓰도록 이름을 기존 대상에 묶거나 새로 만든다."""
from __future__ import annotations

import re

from ..agents.embed import Index
from .store import Entity, Passage, SourceStore


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9#+ ]", "", re.sub(r"\s+", " ", (name or "").lower())).strip()


class Resolver:
    def __init__(self, store: SourceStore):
        self.st = store
        self.index = Index()
        self.by_name: dict[str, str] = {}
        items = []
        for e in store.entities.values():
            items.append((e.id, " / ".join([e.name] + e.aliases[:4]), {}))
            for n in [e.name] + e.aliases:
                self.by_name.setdefault(norm(n), e.id)
        if items:
            self.index.add_many(items)

    def candidates(self, texts: list[str], k: int = 4, top: int = 30) -> list[str]:
        cands: dict[str, float] = {}
        for t in texts:
            for eid, s in self.index.search(t, k=k):
                cands[eid] = max(cands.get(eid, 0.0), s)
        return [e for e, _ in sorted(cands.items(), key=lambda x: -x[1])[:top] if e in self.st.entities]

    def cand_block(self, eids: list[str], n_last: int = 2) -> str:
        st, lines = self.st, []
        for eid in eids:
            e = st.entities[eid]
            last = [st.passages[i] for i in e.passage_ids[-n_last:] if i in st.passages]
            stm = " || ".join(f"{p.id} ({p.doc_date}): {p.statement[:140]}" for p in last)
            lines.append(f"- {eid} | {e.name} | {e.layer} | {stm}")
        return "\n".join(lines) or "(none yet)"

    def register_alias(self, eid: str, alias: str) -> None:
        """K0 용어집의 별칭을 대상 색인에 등록 (같은 것을 다른 이름으로 불러도 한 대상으로 묶이게)."""
        ent = self.st.entities.get(eid)
        if not ent or not alias:
            return
        if norm(alias) != norm(ent.name) and alias not in ent.aliases and len(ent.aliases) < 16:
            ent.aliases.append(alias)
        self.by_name.setdefault(norm(alias), eid)

    def resolve(self, eid: str | None, name: str | None, p: Passage, *, allowed: set[str] | None = None,
                emit: bool = True, create: bool = True) -> Entity | None:
        """eid 가 유효하면 그 대상, 아니면 같은 이름(또는 K0 별칭)의 대상, 그것도 없으면 새 대상(create=False 면 None).
        소스 문장을 대상에 붙인다."""
        st = self.st
        if eid and eid in st.entities and (allowed is None or eid in allowed or eid in p.entity_ids):
            ent = st.entities[eid]
            if name and norm(name) != norm(ent.name) and name not in ent.aliases and len(ent.aliases) < 12:
                ent.aliases.append(name)
                self.by_name.setdefault(norm(name), ent.id)
            kind = "entity.linked"
        else:
            nm = (name or "").strip().strip(".")
            if not nm or len(nm) > 80:
                return None
            hit = self.by_name.get(norm(nm))
            if hit and hit in st.entities:
                ent = st.entities[hit]
                kind = "entity.linked"
            elif not create:
                return None
            else:
                ent = Entity(name=nm, created_by_doc=p.doc_id)
                st.entities[ent.id] = ent
                self.index.add(ent.id, nm)
                self.by_name[norm(nm)] = ent.id
                kind = "entity.created"
        if ent.id not in p.entity_ids:
            p.entity_ids.append(ent.id)
        if p.id not in ent.passage_ids:
            st.attach(ent, p)
            if emit:
                st.emit(kind, doc_id=p.doc_id, pid=p.id, eid=ent.id, name=ent.name, layers=p.layers)
        return ent
