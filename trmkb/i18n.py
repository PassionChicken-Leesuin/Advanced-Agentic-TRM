"""
trmkb.i18n — 화면 라벨 사전. 지금은 한국어, 추후 영어 전환 예정이라 처음부터 분리.
사용: from trmkb.i18n import t;  t("layer.why")  ->  "Why (시장·동인)"
"""
from __future__ import annotations

LANG = "ko"

_LABELS: dict[str, dict[str, str]] = {
    "ko": {
        # 층
        "layer.why": "Why (시장·동인)",
        "layer.what": "What (제품·기능)",
        "layer.how": "How (기술)",
        "layer.resource": "자원 (자금·표준·시설)",
        "layer.cross": "횡단 (행위자·이슈)",
        # 노드 유형
        "node.driver": "외부 드라이버",
        "node.need": "이해관계자 니즈",
        "node.vision": "비전",
        "node.opportunity": "응용 기회·제품",
        "node.milestone": "마일스톤",
        "node.capability": "역량·기술",
        "node.component": "구성요소",
        "node.enabler": "인에이블러",
        "node.actor": "행위자",
        "node.issue": "이슈",
        # 주장 유형
        "claim.spec": "목표 사양",
        "claim.capability_claim": "역량 주장",
        "claim.market_size": "시장 규모",
        "claim.maturity": "성숙도",
        "claim.priority": "우선순위",
        "claim.comparison": "경쟁 비교",
        "claim.action": "조치",
        # 관계
        "rel.drives": "유발",
        "rel.requires": "요구",
        "rel.enables": "가능하게 함",
        "rel.precedes": "선행",
        "rel.part_of": "부분",
        "rel.competes_with": "경쟁",
        "rel.threatens": "위협",
        "rel.addressed_by": "대응",
        "rel.provides": "제공",
        "rel.endorsed_by": "지지",
        "rel.decided_over": "선택",
        # 에이전트
        "agent.reader": "Reader",
        "agent.router": "Router",
        "agent.linker": "Linker",
        "agent.critic": "Critic",
        "agent.timing": "Timing",
        "agent.summarizer": "Summarizer",
        "agent.generator": "Generator",
        "agent.system": "System",
        "agent.reader.desc": "근거 문장 추출",
        "agent.router.desc": "병합·신규·구조 선택",
        "agent.linker.desc": "층간 링크 제안",
        "agent.critic.desc": "근거·모순·층 위반 판정",
        "agent.timing.desc": "ES/LS 재계산",
        "agent.summarizer.desc": "행 요약 갱신",
        # 이벤트 메시지 템플릿
        "ev.doc.started": "문서 처리 시작: {title}",
        "ev.doc.finished": "문서 처리 완료: {title} ({n_nodes}노드 {n_edges}엣지)",
        "ev.node.proposed": "후보 노드 제안: {label}",
        "ev.node.created": "노드 생성: {label}",
        "ev.node.merged": "기존 노드에 병합: {label} → {target}",
        "ev.node.updated": "노드 갱신: {label}",
        "ev.claim.added": "주장 추가: {text}",
        "ev.evidence.added": "근거 부착: {n}건",
        "ev.edge.proposed": "링크 제안: {src} → {dst} ({rel})",
        "ev.edge.accepted": "링크 수락: {src} → {dst}",
        "ev.edge.rejected": "링크 반려: {src} → {dst} ({reason})",
        "ev.conflict.flagged": "모순 플래그: {a} vs {b}",
        "ev.summary.updated": "{layer} 레이어 요약 갱신 ({n_before} → {n_after} 노드)",
        "ev.time.indexed": "시간 인덱스 등록: {label} @ {year}",
        "ev.time.recomputed": "ES/LS 재계산: {n}노드",
        "ev.router.decision": "Router 판단: {decision} ({label})",
        "ev.candidate.added": "결측 링크 후보: {src} → {dst}",
        "ev.error": "오류: {msg}",
        # 화면
        "ui.progress": "문서 {done} / {total} 처리 중",
        "ui.roadmap.initial": "Initial Roadmap (KB 없음)",
        "ui.roadmap.advanced": "Advanced Roadmap (KB 사용)",
        "ui.critic.insufficient": "Critic: 근거 불충분",
        "ui.infeasible": "Infeasible: 기술이 수요보다 늦음",
    },
    "en": {
        "layer.why": "Why (market & drivers)",
        "layer.what": "What (products & features)",
        "layer.how": "How (technology)",
        "layer.resource": "Resources (funding · standards · facilities)",
        "layer.cross": "Cross-cutting (actors · issues)",
        "node.driver": "External driver", "node.need": "Stakeholder need", "node.vision": "Vision",
        "node.opportunity": "Opportunity / product", "node.milestone": "Milestone", "node.capability": "Capability / technology",
        "node.component": "Component", "node.enabler": "Enabler", "node.actor": "Actor", "node.issue": "Issue",
        "claim.spec": "Target spec", "claim.capability_claim": "Capability claim", "claim.market_size": "Market size",
        "claim.maturity": "Maturity", "claim.priority": "Priority", "claim.comparison": "Comparison", "claim.action": "Action",
        "rel.drives": "drives", "rel.requires": "requires", "rel.enables": "enables", "rel.precedes": "precedes",
        "rel.part_of": "part of", "rel.competes_with": "competes with", "rel.threatens": "threatens",
        "rel.addressed_by": "addressed by", "rel.provides": "provides", "rel.endorsed_by": "endorsed by", "rel.decided_over": "decided over",
        "agent.reader.desc": "extracts evidence sentences", "agent.router.desc": "merge / create / choose structure",
        "agent.linker.desc": "proposes cross-layer links", "agent.critic.desc": "judges evidence, conflicts, layer rules",
        "agent.timing.desc": "recomputes ES/LS", "agent.summarizer.desc": "refreshes row summaries",
        "ev.doc.started": "Processing document: {title}",
        "ev.doc.finished": "Finished: {title} ({n_nodes} nodes, {n_edges} links)",
        "ev.node.proposed": "Candidate node: {label}",
        "ev.node.created": "Node created: {label}",
        "ev.node.merged": "Merged into existing node: {label} → {target}",
        "ev.node.updated": "Node updated: {label}",
        "ev.claim.added": "Claim added: {text}",
        "ev.evidence.added": "Evidence attached: {n}",
        "ev.edge.proposed": "Link proposed: {src} → {dst} ({rel})",
        "ev.edge.accepted": "Link accepted: {src} → {dst}",
        "ev.edge.rejected": "Link rejected: {src} → {dst} ({reason})",
        "ev.conflict.flagged": "Conflict flagged: {a} vs {b}",
        "ev.summary.updated": "Summary refreshed for {layer} ({n_before} → {n_after} nodes)",
        "ev.time.indexed": "Time index: {label} @ {year}",
        "ev.time.recomputed": "ES/LS recomputed: {n} nodes",
        "ev.router.decision": "Router: {decision} ({label})",
        "ev.candidate.added": "Missing-link candidate: {src} → {dst}",
        "ev.error": "Error: {msg}",
        "ui.progress": "Documents {done} / {total}",
        "ui.roadmap.initial": "Initial Roadmap (no KB)",
        "ui.roadmap.advanced": "Advanced Roadmap (with KB)",
        "ui.critic.insufficient": "Critic: insufficient evidence",
        "ui.infeasible": "Infeasible: technology later than demand",
    },
}


def t(key: str, lang: str | None = None, **kwargs) -> str:
    lang = lang or LANG
    table = _LABELS.get(lang, {})
    text = table.get(key) or _LABELS["ko"].get(key) or key
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text
