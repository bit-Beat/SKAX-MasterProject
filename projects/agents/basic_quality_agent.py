"""SC-001 basic quality review subagent definition."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class SubagentReport(BaseModel):
    """ basic_quality Agent 반환 구조."""

    scenario_key: str = Field(description="현재 시나리오 키")
    summary: str = Field(description="서브에이전트 요약")
    score: Optional[int] = Field(default=None, description="0~100 점수")
    findings: List[str] = Field(default_factory=list, description="핵심 이슈 목록")
    warnings: List[str] = Field(default_factory=list, description="주의사항 목록")
    recommendations: List[str] = Field(default_factory=list, description="권장 조치 목록")
    artifact_path: Optional[str] = Field(default=None, description="저장 경로")

def build_basic_quality_agent_spec(toolset: Dict[str, Any]) -> Dict[str, Any]:
    """Return the SC-001 basic quality review subagent spec."""
    return {
        "name": "basic-quality-agent",
        "description": "SC-001 산출물 기초 품질 점검 Agent. 형식, 오탈자, 필수값 누락 등 기초 품질을 검증한다.",
        "system_prompt": (
            "너는 산출물 기초 품질 점검 Agent다. SC-001/basic_quality 시나리오만 담당한다. "
            "사전에 정의된 룰과 체크리스트를 기준으로 형식, 오탈자, 필수값 누락을 검증하라. "
            "의미 기반 추론은 최소화하고, 기능/UI 의미 일치성 판단은 수행하지 마라. "
            "반드시 run_basic_quality_review 결과에 근거해 findings, warnings, score, recommendations를 정리하라."
            "반드시 Skill에서 제공하는 run_basic_quality_review 함수를 호출해 점검을 수행하라. "
            "점검이 종료되면 점검 결과를 Json 파일로 저장하라. 저장 시 persist_subagent_output 함수를 사용해 파일 경로를 기록하라."
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