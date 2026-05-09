"""SC-001 basic quality review subagent definition."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


def _limit_list(value, limit: int):
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    if len(value) <= limit:
        return value
    return [*value[: limit - 1], f"... 외 {len(value) - limit + 1}건 생략"]

class SubagentReport(BaseModel):
    """ basic_quality Agent 반환 구조."""

    scenario_key: str = Field(description="현재 시나리오 키")
    summary: str = Field(description="서브에이전트 요약", max_length=800)
    score: Optional[int] = Field(default=None, description="0~100 점수")
    findings: List[str] = Field(default_factory=list, max_length=8, description="핵심 이슈 목록")
    warnings: List[str] = Field(default_factory=list, max_length=8, description="주의사항 목록")
    recommendations: List[str] = Field(default_factory=list, max_length=8, description="권장 조치 목록")
    artifact_path: Optional[str] = Field(default=None, description="저장 경로")
    corrected_document_paths: List[str] = Field(default_factory=list, max_length=3, description="문서별 보완본 JSON 저장 경로 목록")

    @field_validator("findings", "warnings", "recommendations", mode="before")
    @classmethod
    def trim_issue_lists(cls, value):
        return _limit_list(value, 8)

    @field_validator("corrected_document_paths", mode="before")
    @classmethod
    def trim_corrected_paths(cls, value):
        return _limit_list(value, 3)

def build_basic_quality_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the SC-001 basic quality review subagent spec."""
    return {
        "name": "basic-quality-agent",
            "description": "SC-001 산출물 기초 품질 점검 Agent. 형식, 오탈자, 필수값 누락 등 기초 품질을 검증한다.",
        "system_prompt": (
            "너는 산출물 기초 품질 점검 Agent다. SC-001/basic_quality 시나리오만 담당한다. "
            "출력 시 scenario_key는 반드시 basic_quality로 표기하라. SC-001, sc_001, basic_quality_agent로 표기하지 마라. "
           
            "사전에 정의된 룰과 체크리스트를 기준으로 형식, 오탈자, 필수값 누락을 검증하라. "
            "의미 기반 추론은 최소화하고, 기능/UI 의미 일치성 판단은 수행하지 마라. "
            "반드시 run_basic_quality_review 결과에 근거해 findings, warnings, score, recommendations를 정리하라."
            "run_basic_quality_review 결과 전체를 응답에 그대로 복사하지 말고, findings/warnings/recommendations는 각각 최대 8개 대표 항목만 포함하라. "
            "도구 결과에 *_count 필드가 있으면 전체 건수는 summary에 요약하라. "
            "반드시 Skill에서 제공하는 run_basic_quality_review 함수를 호출해 점검을 수행하라. "
            "점검이 종료되면 점검 결과를 Json 파일로 저장하라. 저장 시 persist_subagent_output 함수를 사용해 파일 경로를 기록하라. "
            "persist_subagent_output 저장 과정에서 점검 결과를 반영한 문서별 보완본 JSON이 자동 생성된다. "
            "보완본은 requirement_definition, feature_definition, ui_design 3개 문서 각각 생성되어야 하며 "
            "응답의 corrected_document_paths에 생성 경로를 포함하라."
        ),
        "tools": toolset["basic_quality"],
        "skills": toolset["skills"]["basic_quality_agent"],
        "response_format": SubagentReport,
    }


"""
    scenario_key: str = Field(description="현재 시나리오 키")
    summary: str = Field(description="서브에이전트 요약")
    score: Optional[int] = Field(default=None, description="0~100 점수")
    findings: List[str] = Field(default_factory=list, description="핵심 이슈 목록")
    warnings: List[str] = Field(default_factory=list, description="주의사항 목록")
    recommendations: List[str] = Field(default_factory=list, description="권장 조치 목록")
    artifact_path: Optional[str] = Field(default=None, description="저장 경로")
"""
