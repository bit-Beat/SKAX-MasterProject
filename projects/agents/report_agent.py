"""Report Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import FinalReviewReport


def build_report_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Report Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "report-agent",
        "description": "시나리오별 결과를 최종 보고서로 통합한다.",
        "system_prompt": (
            "너는 Report Agent다. 시나리오별 결과를 통합해 전체 점수, "
            "보완 필요 시나리오, 우선순위 액션이 보이는 최종 보고서를 작성하라."
        ),
        "tools": toolset["shared"],
        "skills": toolset["skills"]["report_agent"],
        "response_format": FinalReviewReport,
    }
