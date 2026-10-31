"""
Timing — 결정적 ES/LS 계산 (연산 ⑤).

1. 노드 자체 시간: 주장들의 time.start/end 중 planned/achieved/required/forecast 모달리티에서 min start → es, max end → ls.
2. 전파: 수락된 precedes(src→dst, lag 기본 0.5년) 로 es[dst] ≥ es[src]+lag. DAG 위 위상 순서로 완화(cycles는 무시).
3. 실행가능성: what --requires--> how 에서 es[how] > es[what] 이면 what 노드에 "infeasible" 플래그 (기술이 수요보다 늦음).
"""
from __future__ import annotations

import networkx as nx

from ..schema import CriticStatus, Layer, Modality, NodeType, NODE_LAYER, RelationType
from ..store import KBStore

TIME_MODALITIES = {Modality.PLANNED, Modality.ACHIEVED, Modality.REQUIRED, Modality.FORECAST, Modality.CURRENT}
DEFAULT_LAG = 0.5


def recompute(kb: KBStore) -> dict:
    changed = 0
    own: dict[str, tuple[float | None, float | None]] = {}
    for n in kb.nodes.values():
        starts, ends = [], []
        for c in kb.claims_for(n.id):
            if c.modality not in TIME_MODALITIES:
                continue
            if c.time.start is not None:
                starts.append(c.time.start)
            if c.time.end is not None:
                ends.append(c.time.end)
        es = min(starts) if starts else (min(ends) if ends else None)
        ls = max(ends) if ends else (max(starts) if starts else None)
        own[n.id] = (es, ls)
    es_map = {k: v[0] for k, v in own.items()}
    ls_map = {k: v[1] for k, v in own.items()}

    g = nx.DiGraph()
    g.add_nodes_from(kb.nodes)
    for e in kb.edges.values():
        if e.critic_status == CriticStatus.ACCEPTED and e.type == RelationType.PRECEDES:
            g.add_edge(e.src, e.dst, lag=e.lag_years if e.lag_years is not None else DEFAULT_LAG)
    try:
        order = list(nx.topological_sort(g))
    except nx.NetworkXUnfeasible:
        g.remove_edges_from(nx.find_cycle(g))
        order = list(nx.topological_sort(g))
    for u in order:
        for v in g.successors(u):
            if es_map.get(u) is not None:
                cand = es_map[u] + g.edges[u, v]["lag"]
                if es_map.get(v) is None or cand > es_map[v]:
                    es_map[v] = cand

    infeasible = []
    for e in kb.edges.values():
        if e.critic_status != CriticStatus.ACCEPTED or e.type != RelationType.REQUIRES:
            continue
        s, d = kb.nodes[e.src], kb.nodes[e.dst]
        if NODE_LAYER[NodeType(s.type)] == Layer.WHAT and NODE_LAYER[NodeType(d.type)] == Layer.HOW:
            if es_map.get(s.id) is not None and es_map.get(d.id) is not None and es_map[d.id] > es_map[s.id] + 0.01:
                infeasible.append((s.id, d.id, es_map[s.id], es_map[d.id]))

    inf_ids = {s for s, *_ in infeasible}
    for n in kb.nodes.values():
        new_es, new_ls = es_map.get(n.id), ls_map.get(n.id)
        if new_ls is not None and new_es is not None and new_ls < new_es:
            new_ls = new_es
        flags = [f for f in n.flags if f != "infeasible"] + (["infeasible"] if n.id in inf_ids else [])
        if (n.es, n.ls, n.flags) != (new_es, new_ls, flags):
            n.es, n.ls, n.flags = new_es, new_ls, flags
            kb.upsert_node(n); changed += 1
            if new_es is not None:
                kb.index_time(n.id, new_es)
    return {"changed": changed, "infeasible": infeasible, "with_time": sum(1 for v in es_map.values() if v is not None)}
