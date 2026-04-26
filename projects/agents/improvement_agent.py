"""Improvement Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_improvement_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Improvement Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "improvement-agent",
        "description": "이슈를 우선순위 중심 개선 액션으로 바꾼다.",
        "system_prompt": (
            "너는 Improvement Agent다. findings와 warnings를 받아 "
            "실행 가능한 개선 액션만 간단히 정리하라."
        ),
        "tools": toolset["improvement"],
        "skills": toolset["skills"]["improvement_agent"],
        "response_format": SubagentReport,
    }
