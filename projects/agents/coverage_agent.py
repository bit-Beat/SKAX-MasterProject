"""SC-004 requirement coverage review subagent definition."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_coverage_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the SC-004 requirement coverage review subagent spec."""
    return {
        "name": "coverage-agent",
        "description": "SC-004 요구사항 커버리지 검토 Agent. 요구사항 대비 기능 정의 누락과 분해 부족을 분석한다.",
        "system_prompt": (
            "너는 요구사항 커버리지 검토 Agent다. SC-004/coverage 시나리오만 담당한다. "
            "요구사항 대비 기능 정의 누락, 범위 과소/과대, 기능 분해 부족 영역을 분석하라. "
            "구현 상세 추정은 금지하고, 요구사항-기능 매핑 범위 안에서만 판단하라. "
            "반드시 run_coverage_review 결과에 근거해 findings, warnings, score, recommendations를 정리하라."
        ),
        "tools": toolset["coverage"],
        "skills": toolset["skills"]["coverage_agent"],
        "response_format": SubagentReport,
    }
