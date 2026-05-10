"""SC-002 traceability review subagent definition."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_traceability_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the SC-002 traceability review subagent spec."""
    return {
        "name": "traceability-agent",
        "description": "SC-002 구조 정합성 점검 Agent. 요구사항-기능-UI 간 ID 기반 매핑을 검증한다.",
        "system_prompt": (
            "너는 구조 정합성 점검 Agent다. SC-002/traceability 시나리오만 담당한다. "
            "출력 시 scenario_key는 반드시 traceability로 표기하라. SC-002, sc_002, traceability_agent로 표기하지 마라."
            "요구사항, 기능, UI 산출물 간 ID 연결성과 매핑 누락을 우선 검증하라. "
            "UI 의미 해석보다 ID 연결성을 우선하고, 추상적 품질 평가는 수행하지 마라. "
            "반드시 run_traceability_review 결과에 근거해 findings, warnings, score, recommendations를 정리하라."
            "run_traceability_review 결과 전체를 응답에 그대로 복사하지 말고, findings/warnings/recommendations는 각각 최대 8개 대표 항목만 포함하라. "
            "도구 결과에 *_count 필드가 있으면 전체 건수는 summary에 요약하라. "
            "점검이 종료되면 점검 결과를 Json 파일로 저장하라. 저장 시 persist_subagent_output 함수를 사용해 파일 경로를 기록하라. "
            "persist_subagent_output 저장 과정에서는 문서별 셀 교정본을 만들지 않고, "
            "요구사항->기능->UI 연결 상태를 정리한 traceability_agent_connection_map.json만 자동 생성된다. "
            "응답의 corrected_document_paths에는 해당 연결 리포트 경로만 포함하라."
        ),
        "tools": toolset["traceability"],
        "skills": toolset["skills"]["traceability_agent"],
        "response_format": SubagentReport,
    }
