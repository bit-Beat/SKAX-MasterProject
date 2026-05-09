"""Self-quality review subagent definition."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SelfQualityReport


def build_self_quality_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the self-quality review subagent spec."""
    return {
        "name": "self-quality-agent",
        "description": (
            "각 점검 SubAgent가 생성한 문서별 보완본 JSON을 검증하고, "
            "교정 품질이 기준 미달이면 원 SubAgent 재실행 지침을 작성한다."
        ),
        "system_prompt": (
            "너는 자가 교정 품질 점검 Agent다. report-agent는 검증하지 않는다. "
            "입력으로 받은 scenario_key에 대해 해당 SubAgent의 결과 JSON과 "
            "문서별 보완본 requirement_definition, feature_definition, ui_design 3개를 검증한다. "
            "반드시 run_self_quality_review를 호출해 교정 품질 점수, findings, warnings, "
            "correction_guidance, rerun_required를 산출하라. "
            "get_corrected_document_outputs 결과나 문서별 보완본 JSON 전체 내용을 응답에 복사하지 마라. "
            "findings, warnings, correction_guidance는 각각 최대 8개만 작성하라. "
            "점수가 threshold 미만이면 rerun_required=true로 설정하고, 원 SubAgent를 다시 실행할 때 "
            "전달할 구체 지침을 문서명/행/컬럼/수정 방향 중심으로 correction_guidance에 작성하라. "
            "점검 결과는 persist_self_quality_output으로 저장하고 artifact_path를 응답에 포함하라."
        ),
        "tools": toolset["self_quality"],
        "skills": toolset["skills"]["self_quality_agent"],
        "response_format": SelfQualityReport,
    }
