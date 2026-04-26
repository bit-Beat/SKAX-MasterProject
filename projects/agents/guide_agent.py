"""Guide Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_guide_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Guide Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "guide-agent",
        "description": "시나리오 기준, 필수 문서, 사전 체크를 짧게 정리한다.",
        "system_prompt": (
            "너는 Guide Agent다. 시나리오 정의와 현재 문서 현황을 먼저 확인하고, "
            "필수 문서 누락 여부와 체크리스트를 짧게 정리하라."
        ),
        "tools": toolset["guide"],
        "skills": toolset["skills"]["guide_agent"],
        "response_format": SubagentReport,
    }
