"""SC-003 feature-to-screen review subagent definition."""

from __future__ import annotations

from typing import Any, Dict

from agents.agent_models import SubagentReport


def build_ui_match_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the SC-003 feature-to-screen review subagent spec."""
    return {
        "name": "ui-match-agent",
        "description": "SC-003 기능-화면 심층 검토 Agent. 기능 정의와 UI 설계 간 연결 및 의미 일치를 검토한다.",
        "system_prompt": (
            "너는 기능-화면 심층 검토 Agent다. SC-003/ui_match 시나리오만 담당한다. "
            "출력 시 scenario_key는 반드시 ui_match로 표기하라. SC-003, sc_003, ui_match_agent로 표기하지 마라."
            "기능 정의와 UI 설계 간 화면 연결, 용어, 사용자 흐름 관점의 불일치를 비교 분석하라. "
            "근거 없는 추측은 금지하고, 실제 문서와 run_ui_match_review 결과에 기반해 판단하라. "
            "findings, warnings, score, recommendations를 재검사 가능한 형태로 정리하라."
            "run_ui_match_review 결과 전체를 응답에 그대로 복사하지 말고, findings/warnings/recommendations는 각각 최대 8개 대표 항목만 포함하라. "
            "도구 결과에 *_count 필드가 있으면 전체 건수는 summary에 요약하라. "
            "점검이 종료되면 점검 결과를 Json 파일로 저장하라. 저장 시 persist_subagent_output 함수를 사용해 파일 경로를 기록하라. "
            "persist_subagent_output 저장 과정에서 기능-화면 일치 점검 결과를 반영한 문서별 보완본 JSON이 자동 생성된다. "
            "보완본은 requirement_definition, feature_definition, ui_design 3개 문서 각각 생성되어야 하며 "
            "응답의 corrected_document_paths에 생성 경로를 포함하라."
        ),
        "tools": toolset["ui_match"],
        "skills": toolset["skills"]["ui_match_agent"],
        "response_format": SubagentReport,
    }
