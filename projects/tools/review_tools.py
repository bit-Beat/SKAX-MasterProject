"""DeepAgents에서 사용하는 최소 review tool 모음."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from ui.service_data import get_scenario_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data" / "subagents"
SKILLS_ROOT = PROJECT_ROOT / "skills"
DOCUMENT_LABELS = {
    "requirement_definition": "요구사항 정의서",
    "feature_definition": "기능 정의서",
    "ui_design": "UI 설계서",
}
TERM_GROUPS = [("조회", "검색"), ("사용자", "회원"), ("삭제", "제거")]


def build_toolset(agent_request: Dict[str, Any]) -> Dict[str, Any]:
    """현재 요청 기준으로 DeepAgents tool registry를 만듭니다."""
    run_id = agent_request.get("run_id", "manual_run")
    documents = agent_request.get("documents", [])

    @tool("get_document_catalog")
    def get_document_catalog_tool() -> Dict[str, Any]:
        """현재 업로드된 문서의 파싱 상태와 행 수를 반환합니다."""
        return {"documents": get_document_catalog_data(documents)}

    @tool("get_document_preview")
    def get_document_preview_tool(document_key: str, max_rows: int = 3) -> Dict[str, Any]:
        """문서 컬럼과 샘플 행을 미리 확인합니다."""
        document = get_document(documents, document_key)
        if document is None:
            return {"document_key": document_key, "status": "not_found"}
        rows = get_rows(document)
        return {
            "document_key": document_key,
            "document_label": document.get("document_label", ""),
            "columns": get_columns(document),
            "row_count": len(rows),
            "preview_rows": rows[: max(1, min(max_rows, 10))],
        }

    @tool("get_scenario_definition")
    def get_scenario_definition_tool(scenario_key: str) -> Dict[str, Any]:
        """시나리오 설명, 필수 문서, 점검 항목을 반환합니다."""
        return {"scenario_key": scenario_key, **get_scenario_config(scenario_key)}

    @tool("run_basic_quality_review")
    def run_basic_quality_review_tool() -> Dict[str, Any]:
        """기초 품질 점검을 수행합니다."""
        return review_basic_quality(documents)

    @tool("run_traceability_review")
    def run_traceability_review_tool() -> Dict[str, Any]:
        """요구사항-기능-UI 연결 구조를 점검합니다."""
        return review_traceability(documents)

    @tool("run_ui_match_review")
    def run_ui_match_review_tool() -> Dict[str, Any]:
        """기능과 UI 간 일치성을 점검합니다."""
        return review_ui_match(documents)

    @tool("run_coverage_review")
    def run_coverage_review_tool() -> Dict[str, Any]:
        """요구사항 대비 기능 완전성을 점검합니다."""
        return review_coverage(documents)

    @tool("build_improvement_actions")
    def build_improvement_actions_tool(
        scenario_key: str,
        findings: List[str],
        warnings: List[str],
    ) -> List[str]:
        """findings와 warnings를 기반으로 개선 액션을 만듭니다."""
        return make_actions(scenario_key, findings, warnings)

    @tool("persist_subagent_output")
    def persist_subagent_output_tool(scenario_key: str, agent_name: str, payload_json: str) -> str:
        """서브에이전트 결과를 JSON 파일로 저장합니다."""
        payload = parse_json(payload_json)
        file_path = DATA_ROOT / run_id / scenario_key / f"{sanitize_name(agent_name)}.json"
        save_json(file_path, payload)
        return str(file_path)

    shared = [
        get_document_catalog_tool,
        get_document_preview_tool,
        get_scenario_definition_tool,
        persist_subagent_output_tool,
    ]
    return {
        "shared": shared,
        "guide": shared,
        "validation": [
            get_scenario_definition_tool,
            run_basic_quality_review_tool,
            run_traceability_review_tool,
            persist_subagent_output_tool,
        ],
        "review": [
            get_scenario_definition_tool,
            run_ui_match_review_tool,
            run_coverage_review_tool,
            persist_subagent_output_tool,
        ],
        "improvement": [
            get_scenario_definition_tool,
            build_improvement_actions_tool,
            persist_subagent_output_tool,
        ],
        "skills": {
            "orchestrator_agent": [str(SKILLS_ROOT / "orchestrator_agent")],
            "guide_agent": [str(SKILLS_ROOT / "guide_agent")],
            "qa_agent": [str(SKILLS_ROOT / "qa_agent")],
            "validation_agent": [str(SKILLS_ROOT / "validation_agent")],
            "deep_review_agent": [str(SKILLS_ROOT / "deep_review_agent")],
            "improvement_agent": [str(SKILLS_ROOT / "improvement_agent")],
            "report_agent": [str(SKILLS_ROOT / "report_agent")],
        },
    }


def get_document_catalog_data(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """문서별 파서 상태와 행 수만 간단히 요약합니다."""
    return [
        {
            "document_key": document.get("document_key", ""),
            "document_label": DOCUMENT_LABELS.get(document.get("document_key", ""), document.get("document_label", "")),
            "file_name": document.get("file_name", ""),
            "parser_status": document.get("content_summary", {}).get("parser_status", "unknown"),
            "row_count": len(get_rows(document)),
        }
        for document in documents
    ]


def review_basic_quality(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """기초 품질 점검 휴리스틱."""
    findings: List[str] = []
    warnings: List[str] = []

    for document_key, document_label in DOCUMENT_LABELS.items():
        document = get_document(documents, document_key)
        if document is None:
            findings.append(f"{document_label} 문서가 없습니다.")
            continue

        rows = get_rows(document)
        columns = get_columns(document)
        if document.get("content_summary", {}).get("parser_status") != "success":
            findings.append(f"{document_label} 문서 파싱이 정상 완료되지 않았습니다.")
            continue
        if not rows:
            findings.append(f"{document_label}에서 읽힌 데이터 행이 없습니다.")
            continue

        id_column = find_column(rows, ["id"])
        name_column = find_column(rows, ["명"])
        if id_column:
            empty_ids = [str(index) for index, row in enumerate(rows, start=1) if not str(row.get(id_column, "")).strip()]
            invalid_ids = [
                str(row.get(id_column, ""))
                for row in rows
                if str(row.get(id_column, "")).strip() and not re.match(r"^[A-Za-z][A-Za-z0-9_-]+$", str(row.get(id_column, "")).strip())
            ]
            if empty_ids:
                findings.append(f"{document_label}의 식별자 누락 행이 있습니다. 예: {', '.join(empty_ids[:3])}행")
            if invalid_ids:
                findings.append(f"{document_label}의 식별자 형식이 일정하지 않습니다. 예: {', '.join(invalid_ids[:3])}")
        if id_column and name_column:
            missing_rows = [
                str(index)
                for index, row in enumerate(rows, start=1)
                if not str(row.get(id_column, "")).strip() or not str(row.get(name_column, "")).strip()
            ]
            if missing_rows:
                warnings.append(f"{document_label}의 필수값 누락 행이 있습니다. 예: {', '.join(missing_rows[:3])}행")
        if document_key == "ui_design" and not find_column(rows, ["화면id"]):
            warnings.append("UI 설계서에서 화면ID 컬럼을 찾지 못했습니다.")
        if not columns:
            warnings.append(f"{document_label}의 컬럼 정보를 읽지 못했습니다.")

    combined_text = " ".join(" ".join(str(value) for row in get_rows(doc) for value in row.values()) for doc in documents)
    for left, right in TERM_GROUPS:
        if left in combined_text and right in combined_text:
            warnings.append(f"`{left}`와 `{right}` 용어가 혼용되어 있습니다.")

    score = max(0, 100 - len(findings) * 12 - len(warnings) * 4)
    return {
        "scenario_key": "basic_quality",
        "summary": "형식, 필수값, 용어 기준으로 기초 품질을 점검했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": make_actions("basic_quality", findings, warnings),
    }


def review_traceability(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """요구사항-기능-UI 연결 구조 점검."""
    requirement_rows = get_rows(get_document(documents, "requirement_definition"))
    feature_rows = get_rows(get_document(documents, "feature_definition"))
    ui_rows = get_rows(get_document(documents, "ui_design"))

    req_id_col = find_column(requirement_rows, ["요구사항 id"])
    feat_req_col = find_column(feature_rows, ["요구사항 id"])
    feat_screen_col = find_column(feature_rows, ["화면id"])
    ui_screen_col = find_column(ui_rows, ["화면id"])

    req_ids = set(non_empty_values(requirement_rows, req_id_col))
    feat_req_ids = set(non_empty_values(feature_rows, feat_req_col))
    feat_screen_ids = set(non_empty_values(feature_rows, feat_screen_col))
    ui_screen_ids = set(non_empty_values(ui_rows, ui_screen_col))

    findings: List[str] = []
    warnings: List[str] = []

    if not req_id_col:
        findings.append("요구사항 정의서에서 요구사항 ID 컬럼을 찾지 못했습니다.")
    if not feat_req_col:
        findings.append("기능 정의서에서 요구사항 ID 컬럼을 찾지 못했습니다.")
    if missing_values(req_ids, feat_req_ids):
        findings.append(f"요구사항 중 기능 정의로 연결되지 않은 ID가 있습니다. 예: {', '.join(missing_values(req_ids, feat_req_ids)[:3])}")
    if feat_screen_ids and not ui_screen_col:
        findings.append("UI 설계서에서 화면ID 컬럼을 찾지 못했습니다.")
    if feat_screen_ids and ui_screen_ids:
        gap = missing_values(feat_screen_ids, ui_screen_ids)
        if gap:
            findings.append(f"기능 정의서의 화면ID가 UI 설계서와 연결되지 않습니다. 예: {', '.join(gap[:3])}")
    if ui_rows and req_ids and feat_req_ids != req_ids:
        warnings.append("요구사항-기능-UI 연결이 일부 구간에서 끊겨 있을 수 있습니다.")

    score = max(0, 100 - len(findings) * 12 - len(warnings) * 4)
    return {
        "scenario_key": "traceability",
        "summary": "요구사항, 기능, UI 간 ID 연결 구조를 점검했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": make_actions("traceability", findings, warnings),
    }


def review_ui_match(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """기능과 UI 간 일치성 점검."""
    feature_rows = get_rows(get_document(documents, "feature_definition"))
    ui_rows = get_rows(get_document(documents, "ui_design"))

    screen_col = find_column(feature_rows, ["화면id"])
    ui_screen_col = find_column(ui_rows, ["화면id"])
    name_col = find_column(feature_rows, ["기능명"])
    ui_text = " ".join(flatten_row_text(ui_rows)).lower()

    findings: List[str] = []
    warnings: List[str] = []

    if not screen_col:
        findings.append("기능 정의서에서 화면ID 컬럼을 찾지 못했습니다.")
    if not ui_screen_col:
        findings.append("UI 설계서에서 화면ID 컬럼을 찾지 못했습니다.")
    if screen_col and ui_screen_col:
        missing_screens = missing_values(set(non_empty_values(feature_rows, screen_col)), set(non_empty_values(ui_rows, ui_screen_col)))
        if missing_screens:
            findings.append(f"기능 정의서의 화면ID가 UI 설계서에 없습니다. 예: {', '.join(missing_screens[:3])}")
    if name_col:
        low_overlap = []
        for row in feature_rows:
            feature_name = str(row.get(name_col, "")).strip()
            if feature_name and not any(token in ui_text for token in extract_tokens(feature_name)):
                low_overlap.append(feature_name)
        if low_overlap:
            warnings.append(f"UI 문서에서 직접 확인되지 않는 기능명이 있습니다. 예: {', '.join(low_overlap[:2])}")

    score = max(0, 100 - len(findings) * 12 - len(warnings) * 4)
    return {
        "scenario_key": "ui_match",
        "summary": "기능 정의와 UI 설계 간 화면 연결과 용어 일치성을 점검했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": make_actions("ui_match", findings, warnings),
    }


def review_coverage(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """요구사항 대비 기능 완전성 점검."""
    requirement_rows = get_rows(get_document(documents, "requirement_definition"))
    feature_rows = get_rows(get_document(documents, "feature_definition"))

    req_id_col = find_column(requirement_rows, ["요구사항 id"])
    feat_req_col = find_column(feature_rows, ["요구사항 id"])
    req_ids = set(non_empty_values(requirement_rows, req_id_col))
    feat_req_ids = set(non_empty_values(feature_rows, feat_req_col))

    findings: List[str] = []
    warnings: List[str] = []

    if missing_values(req_ids, feat_req_ids):
        findings.append(f"요구사항 대비 기능 정의가 누락된 항목이 있습니다. 예: {', '.join(missing_values(req_ids, feat_req_ids)[:3])}")
    if len(feature_rows) < len(requirement_rows):
        warnings.append("기능 정의 행 수가 요구사항 수보다 적어 세부 기능 분해가 부족할 수 있습니다.")

    score = max(0, 100 - len(findings) * 12 - len(warnings) * 4)
    return {
        "scenario_key": "coverage",
        "summary": "요구사항 대비 기능 정의의 누락과 과잉을 분석했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": make_actions("coverage", findings, warnings),
    }


def make_actions(scenario_key: str, findings: List[str], warnings: List[str]) -> List[str]:
    """이슈를 간단한 개선 액션으로 바꿉니다."""
    guide = {
        "basic_quality": "필수 컬럼과 ID 형식을 먼저 정리하세요.",
        "traceability": "요구사항-기능-UI 매핑표를 기준 문서로 고정하세요.",
        "ui_match": "기능명과 화면ID를 1:1 기준으로 다시 매핑하세요.",
        "coverage": "요구사항을 기능 단위로 다시 분해해 누락 항목을 보완하세요.",
    }.get(scenario_key, "핵심 이슈부터 순서대로 보완하세요.")

    actions = []
    for text in findings[:2] + warnings[:2]:
        action = f"{shorten(text)} -> {guide}"
        if action not in actions:
            actions.append(action)
    return actions or ["정기 점검을 유지하세요."]


def get_document(documents: List[Dict[str, Any]], document_key: str) -> Optional[Dict[str, Any]]:
    """문서 키로 문서를 찾습니다."""
    for document in documents:
        if document.get("document_key") == document_key:
            return document
    return None


def get_rows(document: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """문서의 모든 시트 데이터를 하나의 row 목록으로 합칩니다."""
    if not document:
        return []
    rows: List[Dict[str, Any]] = []
    for sheet in document.get("content_summary", {}).get("sheets", []):
        rows.extend(sheet.get("data", []))
    return rows


def get_columns(document: Optional[Dict[str, Any]]) -> List[str]:
    """문서의 컬럼 이름을 중복 없이 합칩니다."""
    if not document:
        return []
    columns: List[str] = []
    for sheet in document.get("content_summary", {}).get("sheets", []):
        for column in sheet.get("columns", []):
            if column and column not in columns:
                columns.append(column)
    return columns


def find_column(rows: List[Dict[str, Any]], keywords: List[str]) -> Optional[str]:
    """행 데이터에서 키워드와 맞는 컬럼을 찾습니다."""
    if not rows:
        return None
    for column in rows[0].keys():
        normalized_column = normalize(column)
        for keyword in keywords:
            if normalize(keyword) in normalized_column:
                return column
    return None


def non_empty_values(rows: List[Dict[str, Any]], column_name: Optional[str]) -> List[str]:
    """선택한 컬럼의 빈 값이 아닌 항목만 반환합니다."""
    if not column_name:
        return []
    return [str(row.get(column_name, "")).strip() for row in rows if str(row.get(column_name, "")).strip()]


def missing_values(source: set, target: set) -> List[str]:
    """source에는 있지만 target에는 없는 값을 정렬해 반환합니다."""
    return sorted(source - target)


def flatten_row_text(rows: List[Dict[str, Any]]) -> List[str]:
    """행 값을 한 줄 텍스트로 펼칩니다."""
    return [" ".join(str(value).strip() for value in row.values() if str(value).strip()) for row in rows]


def extract_tokens(text: str) -> List[str]:
    """문자열에서 비교용 토큰만 단순 추출합니다."""
    return [token.lower() for token in re.findall(r"[A-Za-z0-9가-힣]+", text) if len(token) >= 2]


def normalize(value: Any) -> str:
    """문자열을 비교용으로 정규화합니다."""
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ").strip().lower())


def shorten(text: str, max_length: int = 30) -> str:
    """긴 문장을 짧은 제목처럼 줄입니다."""
    cleaned = str(text).replace("`", "").strip()
    return cleaned if len(cleaned) <= max_length else f"{cleaned[:max_length - 1]}…"


def parse_json(payload_json: str) -> Dict[str, Any]:
    """문자열 JSON을 dict로 변환합니다."""
    try:
        parsed = json.loads(payload_json)
        return parsed if isinstance(parsed, dict) else {"payload": parsed}
    except json.JSONDecodeError:
        return {"raw_payload": payload_json}


def sanitize_name(name: str) -> str:
    """저장용 파일 이름으로 정리합니다."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "agent"


def save_json(file_path: Path, payload: Dict[str, Any]) -> None:
    """UTF-8 JSON 파일로 저장합니다."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
