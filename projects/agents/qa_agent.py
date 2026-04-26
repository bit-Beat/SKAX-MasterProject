"""QA Agent 구성."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_qa_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """QA Agent의 DeepAgents subagent 설정을 반환합니다."""
    return {
        "name": "qa-agent",
        "description": "문서가 애매할 때 추가 확인 질문을 짧게 정리한다.",
        "system_prompt": (
            "너는 QA Agent다. 문서 행 수, 파싱 상태, 샘플 행을 보고 "
            "추가로 확인해야 할 질문만 간단히 정리하라."
        ),
        "tools": toolset["shared"],
        "skills": toolset["skills"]["qa_agent"],
        "response_format": SubagentReport,
    }
