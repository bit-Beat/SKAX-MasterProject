"""LangChain DeepAgents 기준의 최소 Orchestrator 구성."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List

from deepagents import create_deep_agent
from langgraph.types import Overwrite
from langchain_openai import AzureChatOpenAI

from agents.agent_models import FinalReviewReport
from agents.basic_quality_agent import build_basic_quality_agent_spec
from agents.coverage_agent import build_coverage_agent_spec
from agents.qa_agent import build_qa_agent_spec
from agents.report_agent import build_report_agent_spec
from agents.self_quality_agent import build_self_quality_agent_spec
from agents.traceability_agent import build_traceability_agent_spec
from agents.ui_match_agent import build_ui_match_agent_spec
from tools.review_tools import build_toolset, get_document_catalog_data
from utils.common_method import save_json, log
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
    build_self_quality_agent_spec,
    build_qa_agent_spec,
    build_report_agent_spec,
]  # 역할별 SubAgent 구성을 개별 파일에서 읽어오는 빌더 목록

SUBAGENT_DISPLAY = {
    "basic-quality-agent": {
        "label": "기초 품질 점검",
        "progress_key": "basic_quality",
        "counts_progress": True,
    },
    "traceability-agent": {
        "label": "문서 연결성 점검",
        "progress_key": "traceability",
        "counts_progress": True,
    },
    "ui-match-agent": {
        "label": "기능-화면 일치 점검",
        "progress_key": "ui_match",
        "counts_progress": True,
    },
    "coverage-agent": {
        "label": "기능 완전성 분석",
        "progress_key": "coverage",
        "counts_progress": True,
    },
    "self-quality-agent": {
        "label": "자가 교정 점검",
        "progress_key": "self_quality",
        "counts_progress": False,
    },
    "qa-agent": {
        "label": "추가 확인 질문 정리",
        "progress_key": "qa",
        "counts_progress": False,
    },
    "report-agent": {
        "label": "최종 보고서 작성",
        "progress_key": "report",
        "counts_progress": True,
    },
}

TOOL_DISPLAY = {
    "get_document_catalog": "문서 목록 확인",
    "get_document_preview": "문서 미리보기 조회",
    "get_scenario_definition": "시나리오 기준 확인",
    "run_basic_quality_review": "기초 품질 점검 실행",
    "run_traceability_review": "문서 연결성 점검 실행",
    "run_ui_match_review": "기능-화면 일치 점검 실행",
    "run_coverage_review": "기능 완전성 분석 실행",
    "build_improvement_actions": "개선 액션 생성",
    "persist_subagent_output": "결과 저장",
    "persist_corrected_document_outputs": "문서별 보완본 저장",
    "get_subagent_outputs": "서브에이전트 결과 수집",
    "get_corrected_document_outputs": "문서별 보완본 조회",
    "run_self_quality_review": "자가 교정 점검 실행",
    "persist_self_quality_output": "자가 교정 결과 저장",
}


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
        response_format=None,  # 메인 에이전트는 report-agent를 호출해 결과를 얻음
        name="orchestrator",
    )


def run_orchestrator(
    agent_request: Dict[str, Any],
    on_stream_event: Callable[[Dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    """DeepAgents 실행 후 결과를 반환합니다."""
    run_id = agent_request.get("run_id", "manual_run")
    agent = create_orchestrator_agent(agent_request)
    task = build_task_prompt(agent_request)

    raw_result = stream_agent_and_build_result(
        agent=agent,
        task=task,
        scenario_order=agent_request.get("scenario_order", []),
        on_stream_event=on_stream_event,
    )

    final_report = normalize_report(
        run_id=run_id,
        scenario_order=agent_request.get("scenario_order", []),
        structured_response=raw_result.get("structured_response"),
        fallback_text=extract_last_message(raw_result),
    )
    save_json(DATA_ROOT / run_id / "final_report.json", final_report)
 
    result = {
        "status": "completed",
        "mode": "langchain_deepagents_streaming",
        "message": "LangChain DeepAgents Orchestrator 실행이 완료되었습니다.",
        "run_id": run_id,
        "model": LLM.profile["name"],
        "document_catalog": get_document_catalog_data(agent_request.get("documents", [])),
        "final_report": final_report,
        "raw_last_message": extract_last_message(raw_result),
    }
    emit_stream_event(
        {
            "kind": "success",
            "message": "Main Agent가 최종 보고서를 정리했습니다.",
            "progress": 1.0,
        },
        on_stream_event,
    )
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
2. 시나리오는 순차 실행한다. scenario_order에 따라 하나씩 subagent를 호출하라.
3. 각 시나리오 완료 후 다음 시나리오를 실행하라.
4. 직접 세부 분석을 오래 수행하지 말고 반드시 시나리오별 SubAgent에 위임한다.
5. SC-001/basic_quality는 basic-quality-agent에 위임한다.
6. SC-002/traceability는 traceability-agent에 위임한다.
7. SC-003/ui_match는 ui-match-agent에 위임한다.
8. SC-004/coverage는 coverage-agent에 위임한다.
9. basic_quality, traceability, ui_match SubAgent 실행 직후에는 반드시 self-quality-agent를 호출해 해당 SubAgent가 생성한 문서별 보완본 3개를 검증한다.
10. coverage-agent는 현재 산출물 기준 누락/추가/분해 권고만 생성하므로 문서별 교정 output을 만들지 않고 self-quality-agent도 호출하지 않는다.
11. self-quality-agent의 score가 threshold 미만이거나 rerun_required=true이면, self-quality-agent의 correction_guidance를 원 SubAgent 입력에 포함해 해당 시나리오 SubAgent를 1회 재실행한다. 단, coverage는 재실행/교정 검증 대상에서 제외한다.
12. 원 SubAgent를 재실행한 경우 다시 self-quality-agent를 호출해 재검증한다. 동일 시나리오의 재실행은 최대 1회로 제한한다.
13. 모든 교정 대상 SubAgent와 self-quality-agent 검증이 끝난 뒤에만 report-agent로 최종 보고서를 통합한다.
14. 문서가 애매하거나 판단 근거가 부족하면 qa-agent로 확인 질문을 생성한다.
15. 동일 Tool 반복 호출은 피하고, 불확실한 내용은 확정 판단으로 공유하지 않는다.
16. report-agent는 반드시 get_subagent_outputs로 저장된 서브에이전트 결과를 읽고, score와 주요 findings/warnings/recommendations를 사용해야 한다. 단, 각 목록은 최대 8개만 최종 응답에 포함한다.
17. 최종 응답은 반드시 구조화된 보고서로 반환한다.
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

반드시 시나리오를 이 순서대로 하나씩 실행하라. 
먼저 basic_quality를 실행하라. basic_quality가 완료되면 traceability를 실행하라. traceability가 완료되면 ui_match를 실행하라. ui_match가 완료되면 coverage를 실행하라. 
모든 시나리오가 완료된 후 report-agent로 최종 보고서를 생성하라.
basic_quality, traceability, ui_match 실행 후에는 self-quality-agent로 문서별 보완본을 검증하라.
coverage는 현재 산출물 기준 누락/추가/분해 권고만 생성하므로 문서별 교정 output과 self-quality-agent 검증을 수행하지 마라.
self-quality-agent가 rerun_required=true를 반환하면 correction_guidance를 포함해 원 SubAgent를 최대 1회 재실행한 뒤 다시 검증하라. 단, coverage는 재실행/교정 검증 대상에서 제외한다.
반드시 저장된 서브에이전트 결과의 시나리오별 요약, 점수, 주요 findings, 주요 warnings, 주요 recommendations 를 반영하고,
각 findings/warnings/recommendations 목록은 최대 8개로 제한하라.
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
        if payload.get("load_error"):
            continue
        scenario_key = normalize_scenario_key(payload.get("scenario_key") or file_path.stem)
        if scenario_key not in {"basic_quality", "traceability", "ui_match", "coverage"}:
            scenario_key = normalize_scenario_key(file_path.stem)
        if not scenario_key:
            continue
        payload["scenario_key"] = scenario_key
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
        "basic_quality": "basic_quality",
        "basic-quality-agent": "basic_quality",
        "basic-quality": "basic_quality",
        "sc_001": "basic_quality",
        "sc001": "basic_quality",
        "traceability_agent": "traceability",
        "traceability": "traceability",
        "traceability-agent": "traceability",
        "sc_002": "traceability",
        "sc002": "traceability",
        "ui_match_agent": "ui_match",
        "ui_match": "ui_match",
        "ui-match-agent": "ui_match",
        "ui-match": "ui_match",
        "sc_003": "ui_match",
        "sc003": "ui_match",
        "coverage_agent": "coverage",
        "coverage": "coverage",
        "coverage-agent": "coverage",
        "coverage_review_agent": "coverage",
        "coverage-review-agent": "coverage",
        "sc_004": "coverage",
        "sc004": "coverage",
    }
    return aliases.get(raw_value, raw_value)


def to_scenario_report(scenario_key: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """서브에이전트 결과를 FinalReviewReport의 ScenarioReport 형태로 변환합니다."""
    score = source.get("score")
    score = score if isinstance(score, int) else 0
    findings = limit_items(list(source.get("findings") or []), 8)
    warnings = limit_items(list(source.get("warnings") or []), 8)
    recommendations = limit_items(list(source.get("recommendations") or []), 8)
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


def limit_items(items: List[Any], limit: int) -> List[Any]:
    """긴 결과 목록이 모델/화면 컨텍스트를 과도하게 키우지 않도록 제한합니다."""
    if len(items) <= limit:
        return items
    return [*items[:limit], f"... 외 {len(items) - limit}건 생략"]


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
    content = get_message_content(messages[-1])
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)


def stream_agent_and_build_result(
    agent: Any,
    task: str,
    scenario_order: List[str],
    on_stream_event: Callable[[Dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    """DeepAgents 스트림 이벤트를 사용자 친화적 상태로 변환하고 최종 상태를 재구성합니다."""
    raw_result: Dict[str, Any] = {
        "messages": [],
        "structured_response": None,
    }
    seen_messages: set[str] = set()
    seen_task_call_ids: set[str] = set()
    seen_completed_task_call_ids: set[str] = set()
    seen_subagent_running: set[str] = set()
    seen_tool_call_ids: set[tuple[str, str]] = set()
    active_subagents: Dict[str, Dict[str, Any]] = {}
    completed_units: set[str] = set()
    latest_state: Dict[str, Any] = {}
    total_units = max(len(list(scenario_order)) + 1, 1)
    main_status_sent = False

    emit_stream_event(
        {
            "kind": "status",
            "message": "Main Agent가 통합 점검 계획을 세우고 있습니다.",
            "progress": build_progress_value(total_units, completed_units, phase="preparing"),
        },
        on_stream_event,
    )

    try:
        for chunk in agent.stream(
            {"messages": [{"role": "user", "content": task}]},
            stream_mode=["updates", "values"],
            subgraphs=True,
            version="v2",
        ):
            if not isinstance(chunk, dict):
                continue

            chunk_type = str(chunk.get("type") or "")
            namespace = tuple(str(item) for item in (chunk.get("ns") or ()))
            data = chunk.get("data") or {}
            print(
                "[STREAM_CHUNK] "
                + json.dumps(
                    {
                        "type": chunk_type,
                        "namespace": namespace,
                        "data_keys": list(data.keys()) if isinstance(data, dict) else [],
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )

            if chunk_type == "values":
                if isinstance(data, dict):
                    latest_state = data
                    merge_state_into_raw_result(raw_result, data, seen_messages)
                continue

            if chunk_type != "updates" or not isinstance(data, dict):
                continue

            if not namespace and not main_status_sent:
                emit_stream_event(
                    {
                        "kind": "status",
                        "message": "Main Agent가 점검 순서를 조율하고 있습니다.",
                        "progress": build_progress_value(total_units, completed_units, phase="running"),
                    },
                    on_stream_event,
                )
                main_status_sent = True

            if not namespace:
                process_main_agent_updates(
                    data=data,
                    raw_result=raw_result,
                    seen_messages=seen_messages,
                    seen_task_call_ids=seen_task_call_ids,
                    seen_completed_task_call_ids=seen_completed_task_call_ids,
                    active_subagents=active_subagents,
                    completed_units=completed_units,
                    total_units=total_units,
                    on_stream_event=on_stream_event,
                )
                continue

            process_subagent_updates(
                namespace=namespace,
                data=data,
                raw_result=raw_result,
                seen_messages=seen_messages,
                seen_subagent_running=seen_subagent_running,
                seen_tool_call_ids=seen_tool_call_ids,
                active_subagents=active_subagents,
                completed_units=completed_units,
                total_units=total_units,
                on_stream_event=on_stream_event,
            )
    except Exception as error:
        print(
            "[STREAM_ERROR] "
            + json.dumps(
                {
                    "error_type": error.__class__.__name__,
                    "error": str(error),
                    "active_subagents": active_subagents,
                    "completed_units": sorted(completed_units),
                },
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )
        raise

    if latest_state:
        merge_state_into_raw_result(raw_result, latest_state, seen_messages)

    return raw_result


def process_main_agent_updates(
    data: Dict[str, Any],
    raw_result: Dict[str, Any],
    seen_messages: set[str],
    seen_task_call_ids: set[str],
    seen_completed_task_call_ids: set[str],
    active_subagents: Dict[str, Dict[str, Any]],
    completed_units: set[str],
    total_units: int,
    on_stream_event: Callable[[Dict[str, Any]], None] | None,
) -> None:
    """메인 에이전트 업데이트에서 서브에이전트 시작/완료 이벤트를 추출합니다."""
    for node_data in data.values():
        if not isinstance(node_data, dict):
            continue

        merge_state_into_raw_result(raw_result, node_data, seen_messages)
        messages = coerce_messages(node_data.get("messages"))

        for message in messages:
            for tool_call in extract_tool_calls_from_message(message):
                if get_tool_call_name(tool_call) != "task":
                    continue

                task_call_id = get_tool_call_id(tool_call)
                if not task_call_id or task_call_id in seen_task_call_ids:
                    continue

                args = get_tool_call_args(tool_call)
                subagent_type = normalize_subagent_type(
                    args.get("subagent_type") or args.get("agent_type") or args.get("subagent_name")
                )
                meta = build_subagent_meta(subagent_type)
                target_label = infer_self_quality_target_label(args) if subagent_type == "self-quality-agent" else ""
                if target_label:
                    meta["label"] = f"{target_label} 자가 교정 점검"
                is_repeat = bool(
                    meta.get("counts_progress", True)
                    and str(meta.get("progress_key")) in completed_units
                )
                meta["is_repeat"] = is_repeat
                active_subagents[task_call_id] = meta
                seen_task_call_ids.add(task_call_id)
                start_phase = "rerun_started" if is_repeat else "started"
                start_message = (
                    f"{meta['label']} 재점검을 시작했습니다."
                    if is_repeat
                    else f"{meta['label']}을 시작했습니다."
                )

                emit_stream_event(
                    {
                        "kind": "status",
                        "message": start_message,
                        "progress": build_progress_value(
                            total_units,
                            completed_units,
                            meta=meta,
                            phase=start_phase,
                        ),
                    },
                    on_stream_event,
                )

            if get_message_type(message) != "tool":
                continue

            if get_message_name(message) != "task":
                continue

            task_call_id = get_message_tool_call_id(message)
            if not task_call_id or task_call_id in seen_completed_task_call_ids:
                continue

            meta = active_subagents.get(task_call_id, build_subagent_meta(""))
            seen_completed_task_call_ids.add(task_call_id)

            was_already_completed = bool(
                meta.get("counts_progress", True)
                and str(meta.get("progress_key")) in completed_units
            )
            if meta.get("counts_progress", True) and not was_already_completed:
                completed_units.add(str(meta["progress_key"]))
            complete_phase = "rerun_completed" if was_already_completed else "completed"
            complete_message = (
                f"{meta['label']} 재점검이 완료되었습니다."
                if was_already_completed
                else f"{meta['label']}이 완료되었습니다."
            )

            emit_stream_event(
                {
                    "kind": "success",
                    "message": complete_message,
                    "progress": build_progress_value(
                        total_units,
                        completed_units,
                        meta=meta,
                        phase=complete_phase,
                    ),
                },
                on_stream_event,
            )


def process_subagent_updates(
    namespace: tuple[str, ...],
    data: Dict[str, Any],
    raw_result: Dict[str, Any],
    seen_messages: set[str],
    seen_subagent_running: set[str],
    seen_tool_call_ids: set[tuple[str, str]],
    active_subagents: Dict[str, Dict[str, Any]],
    completed_units: set[str],
    total_units: int,
    on_stream_event: Callable[[Dict[str, Any]], None] | None,
) -> None:
    """서브에이전트 업데이트에서 실행 상태와 내부 툴 사용 이벤트를 추출합니다."""
    task_call_id, meta = find_active_subagent(namespace, active_subagents)
    if not task_call_id:
        return

    if task_call_id not in seen_subagent_running:
        seen_subagent_running.add(task_call_id)
        is_repeat = bool(meta.get("is_repeat"))
        running_phase = "rerun_running" if is_repeat else "running"
        running_message = (
            f"{meta['label']} 재점검을 수행하고 있습니다."
            if is_repeat
            else f"{meta['label']}이 문서를 분석하고 있습니다."
        )
        emit_stream_event(
            {
                "kind": "status",
                "message": running_message,
                "progress": build_progress_value(
                    total_units,
                    completed_units,
                    meta=meta,
                    phase=running_phase,
                ),
            },
            on_stream_event,
        )

    for node_data in data.values():
        if not isinstance(node_data, dict):
            continue

        merge_state_into_raw_result(raw_result, node_data, seen_messages)
        messages = coerce_messages(node_data.get("messages"))

        for message in messages:
            for tool_call in extract_tool_calls_from_message(message):
                tool_name = get_tool_call_name(tool_call)
                if not tool_name or tool_name == "task":
                    continue

                internal_call_id = get_tool_call_id(tool_call) or tool_name
                dedupe_key = (task_call_id, internal_call_id)
                if dedupe_key in seen_tool_call_ids:
                    continue

                seen_tool_call_ids.add(dedupe_key)
                is_repeat = bool(meta.get("is_repeat"))
                tool_phase = "rerun_tool" if is_repeat else "tool"
                tool_message = (
                    f"{meta['label']} 재점검에서 {get_tool_display_name(tool_name)}를 사용하고 있습니다."
                    if is_repeat
                    else f"{meta['label']}이 {get_tool_display_name(tool_name)}를 사용하고 있습니다."
                )
                emit_stream_event(
                    {
                        "kind": "status",
                        "message": tool_message,
                        "progress": build_progress_value(
                            total_units,
                            completed_units,
                            meta=meta,
                            phase=tool_phase,
                        ),
                    },
                    on_stream_event,
                )


def merge_state_into_raw_result(
    raw_result: Dict[str, Any],
    state: Dict[str, Any],
    seen_messages: set[str],
) -> None:
    """스트림 중간 상태에서 messages와 structured_response를 누적합니다."""
    messages = coerce_messages(state.get("messages"))
    if messages:
        append_messages(raw_result["messages"], messages, seen_messages)

    structured_response = unwrap_stream_value(state.get("structured_response"))
    if structured_response is not None:
        raw_result["structured_response"] = structured_response


def append_messages(
    target_messages: List[Any],
    new_messages: List[Any],
    seen_messages: set[str],
) -> None:
    """중복 없이 메시지를 누적합니다."""
    for message in new_messages:
        signature = build_message_signature(message)
        if signature in seen_messages:
            continue
        seen_messages.add(signature)
        target_messages.append(message)


def unwrap_stream_value(value: Any) -> Any:
    """LangGraph stream wrapper를 실제 값으로 풀어냅니다."""
    if isinstance(value, Overwrite):
        return value.value
    return value


def coerce_messages(value: Any) -> List[Any]:
    """messages 필드를 항상 순회 가능한 list 형태로 맞춥니다."""
    unwrapped = unwrap_stream_value(value)
    if isinstance(unwrapped, list):
        return unwrapped
    return []


def build_message_signature(message: Any) -> str:
    """스트림 메시지 중복 제거용 서명을 생성합니다."""
    message_id = message.get("id") if isinstance(message, dict) else getattr(message, "id", None)
    if message_id:
        return f"id:{message_id}"

    payload = {
        "type": get_message_type(message),
        "name": get_message_name(message),
        "tool_call_id": get_message_tool_call_id(message),
        "content": get_message_content(message),
    }
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def extract_tool_calls_from_message(message: Any) -> List[Any]:
    """AIMessage 또는 dict 형태에서 tool_calls를 안전하게 추출합니다."""
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list):
        return tool_calls

    if isinstance(message, dict):
        dict_calls = message.get("tool_calls")
        if isinstance(dict_calls, list):
            return dict_calls

    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        kw_calls = additional_kwargs.get("tool_calls")
        if isinstance(kw_calls, list):
            return kw_calls

    return []


def get_tool_call_name(tool_call: Any) -> str:
    """tool_call에서 툴 이름을 꺼냅니다."""
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "")
    return str(getattr(tool_call, "name", "") or "")


def get_tool_call_id(tool_call: Any) -> str:
    """tool_call에서 호출 ID를 꺼냅니다."""
    if isinstance(tool_call, dict):
        return str(tool_call.get("id") or "")
    return str(getattr(tool_call, "id", "") or "")


def get_tool_call_args(tool_call: Any) -> Dict[str, Any]:
    """tool_call 인자를 dict로 표준화합니다."""
    if isinstance(tool_call, dict):
        args = tool_call.get("args") or {}
    else:
        args = getattr(tool_call, "args", {}) or {}

    return args if isinstance(args, dict) else {}


def get_message_type(message: Any) -> str:
    """메시지 타입을 소문자 문자열로 반환합니다."""
    if isinstance(message, dict):
        return str(message.get("type") or message.get("role") or "dict").lower()

    message_type = getattr(message, "type", None)
    if message_type:
        return str(message_type).lower()
    return message.__class__.__name__.lower()


def get_message_name(message: Any) -> str:
    """메시지의 name 필드를 안전하게 반환합니다."""
    if isinstance(message, dict):
        return str(message.get("name") or "")
    return str(getattr(message, "name", "") or "")


def get_message_tool_call_id(message: Any) -> str:
    """메시지의 tool_call_id를 안전하게 반환합니다."""
    if isinstance(message, dict):
        return str(message.get("tool_call_id") or "")
    return str(getattr(message, "tool_call_id", "") or "")


def get_message_content(message: Any) -> Any:
    """메시지의 content를 안전하게 반환합니다."""
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def normalize_subagent_type(value: Any) -> str:
    """여러 서브에이전트 표기를 canonical key로 통일합니다."""
    raw_value = str(value or "").strip()
    if "/" in raw_value:
        raw_value = raw_value.split("/")[-1]

    normalized = raw_value.replace("_", "-").lower()
    aliases = {
        "basic-quality-agent": "basic-quality-agent",
        "basic-quality": "basic-quality-agent",
        "basic-quality-review-agent": "basic-quality-agent",
        "basic-quality-check": "basic-quality-agent",
        "basic-quality-check-agent": "basic-quality-agent",
        "traceability-agent": "traceability-agent",
        "traceability": "traceability-agent",
        "ui-match-agent": "ui-match-agent",
        "ui-match": "ui-match-agent",
        "coverage-agent": "coverage-agent",
        "coverage": "coverage-agent",
        "self-quality-agent": "self-quality-agent",
        "self-quality": "self-quality-agent",
        "self_quality_agent": "self-quality-agent",
        "self_quality": "self-quality-agent",
        "report-agent": "report-agent",
        "report": "report-agent",
        "qa-agent": "qa-agent",
        "qa": "qa-agent",
    }
    return aliases.get(normalized, normalized)


def build_subagent_meta(subagent_type: str) -> Dict[str, Any]:
    """서브에이전트 표시용 메타데이터를 구성합니다."""
    normalized = normalize_subagent_type(subagent_type)
    defaults = SUBAGENT_DISPLAY.get(
        normalized,
        {
            "label": normalized or "서브에이전트",
            "progress_key": normalized or "subagent",
            "counts_progress": False,
        },
    )
    return {
        "type": normalized,
        "label": defaults["label"],
        "progress_key": defaults["progress_key"],
        "counts_progress": defaults["counts_progress"],
    }


def infer_self_quality_target_label(args: Dict[str, Any]) -> str:
    """자가 교정 점검이 어떤 시나리오를 검증하는지 task 인자에서 추정합니다."""
    raw_text = json.dumps(args, ensure_ascii=False, default=str).lower().replace("-", "_")
    targets = [
        ("basic_quality", "기초 품질"),
        ("basic_quality_agent", "기초 품질"),
        ("sc_001", "기초 품질"),
        ("traceability", "문서 연결성"),
        ("traceability_agent", "문서 연결성"),
        ("sc_002", "문서 연결성"),
        ("ui_match", "기능-화면 일치"),
        ("ui_match_agent", "기능-화면 일치"),
        ("sc_003", "기능-화면 일치"),
    ]
    for token, label in targets:
        if token in raw_text:
            return label
    return ""


def find_active_subagent(
    namespace: tuple[str, ...],
    active_subagents: Dict[str, Dict[str, Any]],
) -> tuple[str, Dict[str, Any]]:
    """namespace에서 현재 서브에이전트 task_call_id를 찾아냅니다."""
    for task_call_id, meta in active_subagents.items():
        if any(task_call_id == segment or task_call_id in segment for segment in namespace):
            return task_call_id, meta
    return "", {}


def get_tool_display_name(tool_name: str) -> str:
    """툴 이름을 사용자용 라벨로 변환합니다."""
    return TOOL_DISPLAY.get(tool_name, tool_name.replace("_", " "))


def build_progress_value(
    total_units: int,
    completed_units: set[str],
    meta: Dict[str, Any] | None = None,
    phase: str = "running",
) -> float:
    """서브에이전트 이벤트를 UI 진행률 값으로 변환합니다."""
    if total_units <= 0:
        return 0.0

    completed_count = len(completed_units)
    phase_weights = {
        "preparing": 0.05,
        "started": 0.20,
        "running": 0.45,
        "tool": 0.72,
        "rerun_started": 0.26,
        "rerun_running": 0.32,
        "rerun_tool": 0.38,
        "rerun_completed": 0.42,
    }

    if phase == "completed":
        if meta and not meta.get("counts_progress", True):
            return min((completed_count + 0.16) / total_units, 0.98)
        return min(completed_count / total_units, 1.0)
    if phase == "rerun_completed":
        return min((completed_count + phase_weights["rerun_completed"]) / total_units, 0.98)

    weight = phase_weights.get(phase, 0.45)
    if meta and not meta.get("counts_progress", True):
        weight = min(weight, 0.12)

    return min((completed_count + weight) / total_units, 0.98)


def emit_stream_event(
    event: Dict[str, Any],
    on_stream_event: Callable[[Dict[str, Any]], None] | None,
) -> None:
    """사용자 스트림 이벤트를 콜백과 로그로 동시에 전달합니다."""
    print(
        "[STREAM_EVENT] "
        + json.dumps(event, ensure_ascii=False, default=str),
        flush=True,
    )
    if on_stream_event is not None:
        on_stream_event(event)

    #log(event.get("message", "Agent가 작업 중입니다."), "info")


def save_orchestrator_result(run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Orchestrator 결과를 저장하고 data_path를 붙입니다."""
    file_path = DATA_ROOT / run_id / "orchestrator_output.json"
    result["data_path"] = str(file_path)
    save_json(file_path, result)
    return result
