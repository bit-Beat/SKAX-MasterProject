"""Review Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_review_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Review Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "review-agent",
        "description": "ui_match와 coverage를 심층 검토한다.",
        "system_prompt": (
            "너는 Review Agent다. ui_match와 coverage 시나리오에서 "
            "문서 간 불일치와 누락 위험을 정리하라."
        ),
        "tools": toolset["review"],
        "skills": toolset["skills"]["deep_review_agent"],
        "response_format": SubagentReport,
    }
