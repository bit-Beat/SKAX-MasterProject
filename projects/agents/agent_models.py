"""SubAgent와 최종 보고서에서 사용하는 공통 응답 모델."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SubagentReport(BaseModel):
    """서브에이전트가 반환하는 최소 구조."""

    scenario_key: str = Field(description="현재 시나리오 키")
    summary: str = Field(description="서브에이전트 요약")
    score: Optional[int] = Field(default=None, description="0~100 점수")
    findings: List[str] = Field(default_factory=list, description="핵심 이슈 목록")
    warnings: List[str] = Field(default_factory=list, description="주의사항 목록")
    recommendations: List[str] = Field(default_factory=list, description="권장 조치 목록")
    artifact_path: Optional[str] = Field(default=None, description="저장 경로")


class ScenarioReport(BaseModel):
    """최종 보고서의 시나리오 단위 구조."""

    scenario_key: str = Field(description="시나리오 키")
    scenario_label: str = Field(description="표시용 시나리오 이름")
    status: str = Field(description="통과, 검토 권장, 보완 필요 중 하나")
    score: int = Field(description="시나리오 점수", ge=0, le=100)
    summary: str = Field(description="시나리오 요약")
    findings: List[str] = Field(default_factory=list, description="주요 이슈")
    warnings: List[str] = Field(default_factory=list, description="주의사항")
    recommendations: List[str] = Field(default_factory=list, description="권장 조치")


class FinalReviewReport(BaseModel):
    """메인 DeepAgent의 최종 구조화 응답."""

    run_id: str = Field(description="실행 식별자")
    summary: str = Field(description="전체 점검 요약")
    overall_score: int = Field(description="통합 점수", ge=0, le=100)
    blocked_scenarios: List[str] = Field(default_factory=list, description="보완 필요 시나리오")
    scenario_order: List[str] = Field(default_factory=list, description="실행 시나리오 순서")
    scenario_results: List[ScenarioReport] = Field(default_factory=list, description="시나리오별 결과")
    priority_actions: List[str] = Field(default_factory=list, description="우선순위 액션")
