"""SubAgent와 최종 보고서에서 사용하는 공통 응답 모델."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def _limit_list(value, limit: int):
    """Trim model-produced lists before Pydantic max_length validation."""
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    if len(value) <= limit:
        return value
    return [*value[: limit - 1], f"... 외 {len(value) - limit + 1}건 생략"]


class SubagentReport(BaseModel):
    """서브에이전트가 반환하는 최소 구조."""

    scenario_key: str = Field(description="현재 시나리오 키")
    summary: str = Field(description="서브에이전트 요약", max_length=800)
    score: Optional[int] = Field(default=None, description="0~100 점수")
    findings: List[str] = Field(default_factory=list, max_length=8, description="핵심 이슈 목록")
    warnings: List[str] = Field(default_factory=list, max_length=8, description="주의사항 목록")
    recommendations: List[str] = Field(default_factory=list, max_length=8, description="권장 조치 목록")
    artifact_path: Optional[str] = Field(default=None, description="저장 경로")
    corrected_document_paths: List[str] = Field(default_factory=list, description="문서별 보완본 JSON 저장 경로 목록")


    @field_validator("findings", "warnings", "recommendations", mode="before")
    @classmethod
    def trim_issue_lists(cls, value):
        return _limit_list(value, 8)

    @field_validator("corrected_document_paths", mode="before")
    @classmethod
    def trim_corrected_paths(cls, value):
        return _limit_list(value, 3)


class SelfQualityReport(BaseModel):
    """자가 교정 점검 Agent가 반환하는 구조."""

    scenario_key: str = Field(description="검증 대상 시나리오 키")
    target_agent_name: str = Field(description="검증 대상 원본 서브에이전트 이름")
    summary: str = Field(description="자가 교정 점검 요약", max_length=800)
    score: int = Field(description="교정 품질 점수", ge=0, le=100)
    threshold: int = Field(default=85, description="보완 권고 판단 기준 점수")
    rerun_required: bool = Field(description="기준 미달로 보완 권고가 필요한지 여부")
    findings: List[str] = Field(default_factory=list, max_length=8, description="교정 미흡 또는 실패 항목")
    warnings: List[str] = Field(default_factory=list, max_length=8, description="주의가 필요한 항목")
    correction_guidance: List[str] = Field(default_factory=list, max_length=8, description="최종 보고서에 반영할 구체 보완 지침")
    checked_document_paths: List[str] = Field(default_factory=list, max_length=3, description="검증한 문서별 보완본 JSON 경로")
    document_scores: Dict[str, int] = Field(default_factory=dict, description="문서별 교정 품질 점수")
    artifact_path: Optional[str] = Field(default=None, description="자가 교정 점검 결과 저장 경로")


    @field_validator("findings", "warnings", "correction_guidance", mode="before")
    @classmethod
    def trim_issue_lists(cls, value):
        return _limit_list(value, 8)

    @field_validator("checked_document_paths", mode="before")
    @classmethod
    def trim_checked_paths(cls, value):
        return _limit_list(value, 3)

    @field_validator("document_scores", mode="before")
    @classmethod
    def normalize_document_scores(cls, value):
        """Allow model/tool outputs that wrap each document score in an object."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value

        normalized: Dict[str, int] = {}
        for key, score_value in value.items():
            normalized[str(key)] = _coerce_score_int(score_value)
        return normalized


def _coerce_score_int(value: Any) -> int:
    """Extract an integer score from primitive or dict-like values."""
    if isinstance(value, dict):
        for key in ("score", "value", "document_score"):
            if key in value:
                return _coerce_score_int(value.get(key))
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, min(100, int(round(value))))
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.endswith("%"):
            stripped = stripped[:-1].strip()
        try:
            return max(0, min(100, int(round(float(stripped)))))
        except ValueError:
            return 0
    return 0


class ScenarioReport(BaseModel):
    """최종 보고서의 시나리오 단위 구조."""

    scenario_key: str = Field(description="시나리오 키")
    scenario_label: str = Field(description="표시용 시나리오 이름")
    status: str = Field(description="통과, 검토 권장, 보완 필요 중 하나")
    score: int = Field(description="시나리오 점수", ge=0, le=100)
    summary: str = Field(description="시나리오 요약", max_length=800)
    findings: List[str] = Field(default_factory=list, max_length=8, description="주요 이슈")
    warnings: List[str] = Field(default_factory=list, max_length=8, description="주의사항")
    recommendations: List[str] = Field(default_factory=list, max_length=8, description="권장 조치")


    @field_validator("findings", "warnings", "recommendations", mode="before")
    @classmethod
    def trim_issue_lists(cls, value):
        return _limit_list(value, 8)


class FinalReviewReport(BaseModel):
    """메인 DeepAgent의 최종 구조화 응답."""

    run_id: str = Field(description="실행 식별자")
    summary: str = Field(description="전체 점검 요약", max_length=1000)
    overall_score: int = Field(description="통합 점수", ge=0, le=100)
    blocked_scenarios: List[str] = Field(default_factory=list, description="보완 필요 시나리오")
    scenario_order: List[str] = Field(default_factory=list, description="실행 시나리오 순서")
    scenario_results: List[ScenarioReport] = Field(default_factory=list, max_length=4, description="시나리오별 결과")
    priority_actions: List[str] = Field(default_factory=list, max_length=8, description="우선순위 액션")
    verdict_cards: List[Dict[str, Any]] = Field(default_factory=list, max_length=4, description="전체 판정 카드")
    top_risks: List[str] = Field(default_factory=list, max_length=3, description="핵심 리스크 TOP 3")
    traceability_overview: Dict[str, Any] = Field(default_factory=dict, description="연결성 현황")
    document_fix_points: List[Dict[str, Any]] = Field(default_factory=list, max_length=3, description="문서별 수정 포인트")
    business_impact_features: List[str] = Field(default_factory=list, max_length=5, description="업무 영향 기능")

    @field_validator("scenario_results", mode="before")
    @classmethod
    def trim_scenario_results(cls, value):
        return _limit_list(value, 4)

    @field_validator("priority_actions", mode="before")
    @classmethod
    def trim_priority_actions(cls, value):
        return _limit_list(value, 8)

    @field_validator("verdict_cards", mode="before")
    @classmethod
    def trim_verdict_cards(cls, value):
        return _limit_list(value, 4)

    @field_validator("top_risks", mode="before")
    @classmethod
    def trim_top_risks(cls, value):
        return _limit_list(value, 3)

    @field_validator("document_fix_points", mode="before")
    @classmethod
    def trim_document_fix_points(cls, value):
        return _limit_list(value, 3)

    @field_validator("business_impact_features", mode="before")
    @classmethod
    def trim_business_impact_features(cls, value):
        return _limit_list(value, 5)
