"""LangChain DeepAgents 기준의 최소 Orchestrator 구성."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from deepagents import create_deep_agent
from langchain_openai import AzureChatOpenAI

from agents.agent_models import FinalReviewReport
from agents.basic_quality_agent import build_basic_quality_agent_spec
from agents.coverage_agent import build_coverage_agent_spec
from agents.qa_agent import build_qa_agent_spec
from agents.report_agent import build_report_agent_spec
from agents.traceability_agent import build_traceability_agent_spec
from agents.ui_match_agent import build_ui_match_agent_spec
from tools.review_tools import build_toolset, get_document_catalog_data
from utils.common_method import save_json, log, pretty_trace
from utils.config_loader import load_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data" / "subagents"
DEFAULT_MODEL = os.getenv("DEEPAGENT_MODEL", "google_genai:gemini-3.1-pro-preview")

# ---[ LLM 설정 ]---
LLM_KEY = load_config("LLM", "KEY")
LLM_MODEL = load_config("LLM", "MODEL")
LLM_ENDPOINT = load_config("LLM", "ENDPOINT")
LLM_VERSION = load_config("LLM", "VERSION")
LLM = AzureChatOpenAI(
    deployment_name=LLM_MODEL,
    azure_endpoint=LLM_ENDPOINT,
    api_key=LLM_KEY,
    api_version=LLM_VERSION,
    temperature=0.2,
)
# ---[ LLM 설정 ]---

SUBAGENT_BUILDERS = [
    build_basic_quality_agent_spec,
    build_traceability_agent_spec,
    build_ui_match_agent_spec,
    build_coverage_agent_spec,
    build_qa_agent_spec,
    build_report_agent_spec,
]  # 역할별 SubAgent 구성을 개별 파일에서 읽어오는 빌더 목록


def create_orchestrator_agent(agent_request: Dict[str, Any]):
    """공식 DeepAgents 형태로 Orchestrator를 생성합니다."""
    toolset = build_toolset(agent_request)
    subagents = build_subagent_specs(toolset)
    #log(build_system_prompt(agent_request), "info")
    return create_deep_agent(
        model=LLM,
        tools=toolset["shared"],
        system_prompt=build_system_prompt(agent_request),
        subagents=subagents,
        skills=toolset["skills"]["orchestrator_agent"],
        response_format=FinalReviewReport,
        name="orchestrator",
    )


def run_orchestrator(agent_request: Dict[str, Any]) -> Dict[str, Any]:
    """DeepAgents 실행 후 결과를 반환합니다."""
    run_id = agent_request.get("run_id", "manual_run")
    agent = create_orchestrator_agent(agent_request)
    task = build_task_prompt(agent_request)

    raw_result = agent.invoke({"messages": [{"role": "user", "content": task}]}) ### DeepAgents 실행
    pretty_trace(raw_result)
    #log(f"Orchestrator raw_result : {raw_result}", "info")

    final_report = normalize_report(
        run_id=run_id,
        scenario_order=agent_request.get("scenario_order", []),
        structured_response=raw_result.get("structured_response"),
        fallback_text=extract_last_message(raw_result),
    )
    save_json(DATA_ROOT / run_id / "final_report.json", final_report)
 
    result = {
        "status": "completed",
        "mode": "langchain_deepagents",
        "message": "LangChain DeepAgents Orchestrator 실행이 완료되었습니다.",
        "run_id": run_id,
        "model": LLM.profile["name"],
        "document_catalog": get_document_catalog_data(agent_request.get("documents", [])),
        "final_report": final_report,
        "raw_last_message": extract_last_message(raw_result),
    }
    return save_orchestrator_result(run_id, result)


def build_subagent_specs(toolset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """개별 파일에 정의된 SubAgent 설정을 한 번에 조립합니다."""
    return [builder(toolset) for builder in SUBAGENT_BUILDERS]


def build_system_prompt(agent_request: Dict[str, Any]) -> str:
    """메인 Orchestrator Agent용 시스템 프롬프트."""
    scenario_order = ", ".join(agent_request.get("scenario_order", [])) or "basic_quality"
    lines = []
    for document in get_document_catalog_data(agent_request.get("documents", [])):
        lines.append(
            f"- {document['document_label']} / rows={document['row_count']} / saved_path={document['saved_path']}"
        )
    document_summary = "\n".join(lines) if lines else "- 업로드 문서 없음"

    return f"""너는 프로젝트 산출물 점검을 총괄하는 Orchestrator Agent다.

반드시 LangChain DeepAgents 방식으로 동작하고, 세부 분석은 직접 오래 하지 말고 subagent에 위임하라.

현재 시나리오 순서:
{scenario_order}

현재 문서 현황:
{document_summary}

운영 규칙:
1. 시작 시 문서 상태를 확인한다.
2. 시나리오는 순차 실행한다.
3. 직접 세부 분석을 오래 수행하지 말고 반드시 시나리오별 SubAgent에 위임한다.
4. SC-001/basic_quality는 basic-quality-agent에 위임한다.
5. SC-002/traceability는 traceability-agent에 위임한다.
6. SC-003/ui_match는 ui-match-agent에 위임한다.
7. SC-004/coverage는 coverage-agent에 위임한다.
8. 문서가 애매하거나 판단 근거가 부족하면 qa-agent로 확인 질문을 생성한다.
9. 동일 Tool 반복 호출은 피하고, 불확실한 내용은 확정 판단으로 공유하지 않는다.
10. 모든 시나리오 결과가 모이면 report-agent로 최종 보고서를 통합한다.
11. report-agent는 반드시 get_subagent_outputs로 저장된 서브에이전트 결과를 읽고, score/findings/warnings/recommendations를 변경하지 않고 사용해야 한다.
12. 최종 응답은 반드시 구조화된 보고서로 반환한다.
"""


def build_task_prompt(agent_request: Dict[str, Any]) -> str:
    """실행 시 user message로 넘길 태스크 프롬프트."""
    ordered = "\n".join(
        f"{index}. {scenario_key}"
        for index, scenario_key in enumerate(agent_request.get("scenario_order", []), start=1)
    ) or "1. basic_quality"

    return f"""run_id `{agent_request.get('run_id', 'manual_run')}` 에 대한 산출물 점검을 수행하라.

추가 요청:
{agent_request.get('user_request') or '추가 요청 없음'}

실행 시나리오 순서:
{ordered}

반드시 저장된 서브에이전트 결과의 시나리오별 요약, 점수, findings, warnings, recommendations 를 그대로 반영하고,
마지막에는 전체 점수와 우선순위 액션을 포함한 최종 보고서를 반환하라.
"""


def normalize_report(
    run_id: str,
    scenario_order: List[str],
    structured_response: Any,
    fallback_text: str,
) -> Dict[str, Any]:
    """structured_response를 저장 가능한 dict로 바꿉니다."""
    if structured_response is None:
        fallback_report = {
            "run_id": run_id,
            "summary": fallback_text or "구조화 응답이 비어 있습니다.",
            "overall_score": 0,
            "blocked_scenarios": [],
            "scenario_order": list(scenario_order),
            "scenario_results": [],
            "priority_actions": [],
        }
        return merge_saved_subagent_reports(fallback_report, run_id, scenario_order)

    if hasattr(structured_response, "model_dump"):
        report = structured_response.model_dump()
    elif isinstance(structured_response, dict):
        report = dict(structured_response)
    else:
        report = json.loads(json.dumps(structured_response, ensure_ascii=False, default=str))

    report.setdefault("run_id", run_id)
    report.setdefault("summary", fallback_text or "점검 보고서가 생성되었습니다.")
    report.setdefault("overall_score", 0)
    report.setdefault("blocked_scenarios", [])
    report.setdefault("scenario_order", list(scenario_order))
    report.setdefault("scenario_results", [])
    report.setdefault("priority_actions", [])
    return merge_saved_subagent_reports(report, run_id, scenario_order)


def merge_saved_subagent_reports(
    report: Dict[str, Any],
    run_id: str,
    scenario_order: List[str],
) -> Dict[str, Any]:
    """저장된 서브에이전트 결과를 최종 보고서의 원본 근거로 병합합니다."""
    subagent_reports = load_subagent_reports(run_id)
    if not subagent_reports:
        return report

    existing_results = {
        normalize_scenario_key(item.get("scenario_key", "")): item
        for item in report.get("scenario_results", [])
        if isinstance(item, dict)
    }
    merged_results: List[Dict[str, Any]] = []
    normalized_order = [normalize_scenario_key(key) for key in scenario_order] or [
        "basic_quality", "traceability", "ui_match", "coverage"
    ]

    for scenario_key in normalized_order:
        source = subagent_reports.get(scenario_key) or existing_results.get(scenario_key)
        if not source:
            continue
        merged_results.append(to_scenario_report(scenario_key, source))

    for scenario_key, source in subagent_reports.items():
        if scenario_key not in normalized_order:
            merged_results.append(to_scenario_report(scenario_key, source))

    if not merged_results:
        return report

    scores = [
        item["score"]
        for item in merged_results
        if isinstance(item.get("score"), int)
    ]
    report["scenario_results"] = merged_results
    report["scenario_order"] = normalized_order
    report["overall_score"] = round(sum(scores) / len(scores)) if scores else 0
    report["blocked_scenarios"] = [
        item["scenario_key"]
        for item in merged_results
        if item.get("status") == "보완 필요"
    ]
    report["priority_actions"] = build_priority_actions_from_scenarios(merged_results)
    report["summary"] = build_final_summary(merged_results, report["overall_score"])
    return report


def load_subagent_reports(run_id: str) -> Dict[str, Dict[str, Any]]:
    """data/subagents/{run_id}에 저장된 *_agent.json 결과를 읽습니다."""
    run_dir = DATA_ROOT / run_id
    reports: Dict[str, Dict[str, Any]] = {}
    if not run_dir.exists():
        return reports

    for file_path in sorted(run_dir.glob("*_agent.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        scenario_key = normalize_scenario_key(payload.get("scenario_key") or file_path.stem)
        if not scenario_key:
            continue
        payload.setdefault("artifact_path", str(file_path))
        reports[scenario_key] = payload
    return reports


def normalize_scenario_key(value: str) -> str:
    """SC-001/basic_quality 같은 키를 최종 보고서 표준 키로 정규화합니다."""
    raw_value = str(value or "").strip()
    if "/" in raw_value:
        raw_value = raw_value.split("/")[-1]
    raw_value = raw_value.replace("-", "_").lower()
    aliases = {
        "basic_quality_agent": "basic_quality",
        "traceability_agent": "traceability",
        "ui_match_agent": "ui_match",
        "coverage_agent": "coverage",
        "coverage_review_agent": "coverage",
    }
    return aliases.get(raw_value, raw_value)


def to_scenario_report(scenario_key: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """서브에이전트 결과를 FinalReviewReport의 ScenarioReport 형태로 변환합니다."""
    score = source.get("score")
    score = score if isinstance(score, int) else 0
    findings = list(source.get("findings") or [])
    warnings = list(source.get("warnings") or [])
    recommendations = list(source.get("recommendations") or [])
    status = source.get("status") or infer_status(score, findings)
    return {
        "scenario_key": scenario_key,
        "scenario_label": scenario_label(scenario_key),
        "status": status,
        "score": score,
        "summary": source.get("summary") or f"{scenario_label(scenario_key)} 결과입니다.",
        "findings": findings,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def infer_status(score: int, findings: List[str]) -> str:
    """점수와 findings 기준으로 최종 상태를 산정합니다."""
    if score >= 85 and not findings:
        return "통과"
    if score >= 70 and not findings:
        return "검토 권장"
    return "보완 필요"


def scenario_label(scenario_key: str) -> str:
    labels = {
        "basic_quality": "기초 품질 점검",
        "traceability": "요구사항-기능-UI 구조 정합성",
        "ui_match": "기능-UI 내용 일치성",
        "coverage": "요구사항 기반 기능 완전성",
    }
    return labels.get(scenario_key, scenario_key)


def build_priority_actions_from_scenarios(scenario_results: List[Dict[str, Any]]) -> List[str]:
    """저점/보완 필요 시나리오의 권고사항을 우선순위 액션으로 정리합니다."""
    actions: List[str] = []
    sorted_results = sorted(scenario_results, key=lambda item: item.get("score", 0))
    for result in sorted_results:
        recommendations = result.get("recommendations") or []
        for recommendation in recommendations:
            text = str(recommendation).strip()
            if not text or "개선 필요 사항이 없습니다" in text or "정기 점검" in text:
                continue
            if text not in actions:
                actions.append(text)
            if len(actions) >= 8:
                return actions
    return actions


def build_final_summary(scenario_results: List[Dict[str, Any]], overall_score: int) -> str:
    blocked = [item["scenario_label"] for item in scenario_results if item.get("status") == "보완 필요"]
    if blocked:
        return (
            f"저장된 서브에이전트 결과를 기준으로 최종 품질 점검을 종합했습니다. "
            f"전체 점수는 {overall_score}점이며, 보완 필요 시나리오는 {', '.join(blocked)}입니다."
        )
    return (
        f"저장된 서브에이전트 결과를 기준으로 최종 품질 점검을 종합했습니다. "
        f"전체 점수는 {overall_score}점이며, 모든 시나리오가 통과 또는 검토 권장 수준입니다."
    )


def extract_last_message(raw_result: Dict[str, Any]) -> str:
    """DeepAgents 실행 결과에서 마지막 메시지를 꺼냅니다."""
    messages = raw_result.get("messages", [])
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)


def save_orchestrator_result(run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Orchestrator 결과를 저장하고 data_path를 붙입니다."""
    file_path = DATA_ROOT / run_id / "orchestrator_output.json"
    result["data_path"] = str(file_path)
    save_json(file_path, result)
    return result
