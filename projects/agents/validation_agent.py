"""Validation Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_validation_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Validation Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "validation-agent",
        "description": "basic_quality와 traceability를 룰 기반으로 점검한다.",
        "system_prompt": (
            "너는 Validation Agent다. basic_quality와 traceability 시나리오에서는 "
            "제공된 review tool을 사용해 findings, warnings, score를 정리하라."
        ),
        "tools": toolset["validation"],
        "skills": toolset["skills"]["validation_agent"],
        "response_format": SubagentReport,
    }
