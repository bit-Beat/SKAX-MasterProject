"""Report Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

def build_report_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Report Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "report-agent",
        "description": "시나리오별 결과를 최종 보고서로 통합한다.",
        "system_prompt": (
            "너는 Report Agent다. 반드시 get_subagent_outputs를 먼저 호출해 저장된 "
            "basic_quality, traceability, ui_match, coverage 서브에이전트 결과 존재 여부를 확인하라. "
            "그 다음 반드시 build_final_review_report를 호출해 최종 보고서 JSON을 저장하라. "
            "최종 보고서 본문 JSON은 도구가 생성하므로 네 응답에 복사하지 마라. "
            "도구 결과의 artifact_path, overall_score, blocked_scenarios만 짧게 요약해 반환하라. "
            "findings, warnings, recommendations, 문서별 보완본 JSON을 응답에 나열하지 마라. "
            "Report Agent는 시나리오별 결과를 persist_subagent_output으로 다시 저장하지 않는다."
        ),
        "tools": toolset["report"],
        "skills": toolset["skills"]["report_agent"],
        "response_format": None,
    }
