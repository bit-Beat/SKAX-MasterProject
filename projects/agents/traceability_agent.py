"""SC-002 traceability review subagent definition."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_traceability_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the SC-002 traceability review subagent spec."""
    return {
        "name": "traceability-agent",
        "description": "SC-002 구조 정합성 점검 Agent. 요구사항-기능-UI 간 ID 기반 매핑을 검증한다.",
        "system_prompt": (
            "너는 구조 정합성 점검 Agent다. SC-002/traceability 시나리오만 담당한다. "
            "요구사항, 기능, UI 산출물 간 ID 연결성과 매핑 누락을 우선 검증하라. "
            "UI 의미 해석보다 ID 연결성을 우선하고, 추상적 품질 평가는 수행하지 마라. "
            "반드시 run_traceability_review 결과에 근거해 findings, warnings, score, recommendations를 정리하라."
        ),
        "tools": toolset["traceability"],
        "skills": toolset["skills"]["traceability_agent"],
        "response_format": SubagentReport,
    }
