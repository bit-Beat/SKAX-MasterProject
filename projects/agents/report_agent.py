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
            "너는 Report Agent다. 반드시 get_subagent_outputs를 먼저 호출해 저장된 "
            "basic_quality, traceability, ui_match, coverage 서브에이전트 결과를 확인하라. "
            "각 서브에이전트의 score, findings, warnings, recommendations는 원본 근거이므로 "
            "임의로 변경, 축약, 긍정적으로 재작성하지 마라. "
            "전체 점수, 보완 필요 시나리오, 우선순위 액션만 종합하라. "
            "Report Agent는 시나리오별 결과를 persist_subagent_output으로 다시 저장하지 않는다."
        ),
        "tools": toolset["report"],
        "skills": toolset["skills"]["report_agent"],
        "response_format": FinalReviewReport,
    }
