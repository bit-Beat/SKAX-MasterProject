"""DeepAgents에서 사용하는 최소 review tool 모음."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from ui.service_data import get_scenario_config
from utils.common_method import save_json, log, pretty_trace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data" / "subagents"
SKILLS_ROOT = PROJECT_ROOT / "skills"
DOCUMENT_LABELS = {
    "requirement_definition": "요구사항 정의서",
    "feature_definition": "기능 정의서",
    "ui_design": "UI 설계서",
}
TERM_GROUPS = [("조회", "검색"), ("사용자", "회원"), ("삭제", "제거")]


def _suggest_req_id(value: str) -> Optional[str]:
    """명확히 보정 가능한 요구사항 ID 후보를 반환합니다."""
    match = re.fullmatch(r"(REQ|RQ)[_-]?(\d{1,3})", value.strip().upper())
    if not match:
        return None
    return f"REQ-{int(match.group(2)):03d}"


def _suggest_func_id(value: str) -> Optional[str]:
    """명확히 보정 가능한 기능ID 후보를 반환합니다."""
    match = re.fullmatch(r"REQ[_-]?(\d{1,3})[_-]?F[_-]?(\d{1,2})", value.strip().upper())
    if not match:
        return None
    return f"REQ-{int(match.group(1)):03d}-F{int(match.group(2)):02d}"


def _suggest_ui_id(value: str) -> Optional[str]:
    """명확히 보정 가능한 화면ID 후보를 반환합니다."""
    match = re.fullmatch(r"(UI|U)[_-]?(\d{1,3})(?:[-_][A-Z]+|[A-Z]+)?", value.strip().upper())
    if not match:
        return None
    return f"UI-{int(match.group(2)):03d}"


def _invalid_id_message(
    rule_id: str,
    doc_label: str,
    row_idx: int,
    field_label: str,
    value: str,
    expected_format: str,
    suggestion: Optional[str],
) -> str:
    message = (
        f"[{rule_id}] {doc_label} {row_idx}행: "
        f"{field_label} '{value}'는 {expected_format} 형식이어야 합니다."
    )
    if suggestion and suggestion != value:
        message += f" 권장 수정값: '{suggestion}'"
    return message


def build_toolset(agent_request: Dict[str, Any]) -> Dict[str, Any]:
    """현재 요청 기준으로 DeepAgents tool registry를 만듭니다."""
    run_id = agent_request.get("run_id", "manual_run")
    documents = agent_request.get("documents", [])
    #log(f"documents : {documents}")

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
        canonical_key = canonical_scenario_key(scenario_key)
        return {"scenario_key": canonical_key, **get_scenario_config(canonical_key)}

    @tool("run_basic_quality_review")
    def run_basic_quality_review_tool() -> Dict[str, Any]:
        """기초 품질 점검을 수행합니다."""
        return compact_review_result(review_basic_quality(documents))

    @tool("run_traceability_review")
    def run_traceability_review_tool() -> Dict[str, Any]:
        """요구사항-기능-UI 연결 구조를 점검합니다."""
        return compact_review_result(review_traceability(documents))

    @tool("run_ui_match_review")
    def run_ui_match_review_tool() -> Dict[str, Any]:
        """기능과 UI 간 일치성을 점검합니다."""
        return compact_review_result(review_ui_match(documents))

    @tool("run_coverage_review")
    def run_coverage_review_tool() -> Dict[str, Any]:
        """요구사항 대비 기능 완전성을 점검합니다."""
        return compact_review_result(review_coverage(documents))

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
        canonical_scenario = canonical_scenario_key(scenario_key) or canonical_scenario_key(agent_name)
        payload = normalize_subagent_output_payload(documents, canonical_scenario, agent_name, payload)
        if isinstance(payload, dict):
            payload["scenario_key"] = canonical_scenario
        file_path = DATA_ROOT / run_id / canonical_subagent_file_name(canonical_scenario, agent_name)
        if file_path.exists():
            try:
                existing_payload = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing_payload = {}
            if isinstance(existing_payload, dict) and is_preferred_subagent_payload(payload, existing_payload):
                corrected_paths = maybe_persist_corrected_documents(run_id, documents, canonical_scenario, agent_name, payload)
                if corrected_paths:
                    payload["corrected_document_paths"] = corrected_paths
                else:
                    payload.pop("corrected_document_paths", None)
                save_json(file_path, payload)
            return str(file_path)
        corrected_paths = maybe_persist_corrected_documents(run_id, documents, canonical_scenario, agent_name, payload)
        if corrected_paths:
            payload["corrected_document_paths"] = corrected_paths
        else:
            payload.pop("corrected_document_paths", None)
        save_json(file_path, payload)
        return str(file_path)

    @tool("persist_corrected_document_outputs")
    def persist_corrected_document_outputs_tool(
        scenario_key: str,
        agent_name: str,
        review_payload_json: str,
    ) -> Dict[str, Any]:
        """점검 결과를 반영한 문서별 보완본 JSON 3개를 저장합니다."""
        review_payload = parse_json(review_payload_json)
        if canonical_scenario_key(scenario_key) == "coverage":
            return {
                "run_id": run_id,
                "scenario_key": "coverage",
                "agent_name": sanitize_name(agent_name),
                "saved_paths": [],
                "skipped": True,
                "reason": "coverage-agent는 현재 산출물 기준 보완 권고를 생성하는 역할이므로 문서별 교정 output을 생성하지 않습니다.",
            }
        saved_paths = persist_corrected_documents(
            run_id,
            documents,
            scenario_key,
            agent_name,
            review_payload,
        )
        return {
            "run_id": run_id,
            "scenario_key": canonical_scenario_key(scenario_key),
            "agent_name": sanitize_name(agent_name),
            "saved_paths": saved_paths,
        }

    @tool("get_subagent_outputs")
    def get_subagent_outputs_tool() -> Dict[str, Any]:
        """현재 run_id에 저장된 시나리오별 서브에이전트 결과 JSON을 반환합니다."""
        run_dir = DATA_ROOT / run_id
        outputs: List[Dict[str, Any]] = []
        if not run_dir.exists():
            return {"run_id": run_id, "outputs": outputs}

        loaded_by_scenario: Dict[str, Dict[str, Any]] = {}
        for file_path in sorted(run_dir.glob("*agent.json")):
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                outputs.append({
                    "agent_name": file_path.stem,
                    "artifact_path": str(file_path),
                    "load_error": str(exc),
                })
                continue

            if isinstance(payload, dict):
                payload.setdefault("artifact_path", str(file_path))
                payload.setdefault("agent_name", file_path.stem)
                scenario_key = canonical_scenario_key(payload.get("scenario_key") or file_path.stem)
                previous = loaded_by_scenario.get(scenario_key)
                if previous is None or is_preferred_subagent_payload(payload, previous):
                    loaded_by_scenario[scenario_key] = payload

        outputs.extend(
            compact_subagent_output_for_report(loaded_by_scenario[key])
            for key in ["basic_quality", "traceability", "ui_match", "coverage"]
            if key in loaded_by_scenario
        )

        return {"run_id": run_id, "outputs": outputs}

    @tool("build_final_review_report")
    def build_final_review_report_tool() -> Dict[str, Any]:
        """저장된 서브에이전트 결과로 최종 보고서 JSON을 생성하고 저장합니다."""
        final_report = build_final_review_report_payload(
            run_id=run_id,
            scenario_order=agent_request.get("scenario_order", []),
        )
        file_path = DATA_ROOT / run_id / "final_report.json"
        save_json(file_path, final_report)
        return {
            "run_id": run_id,
            "artifact_path": str(file_path),
            "overall_score": final_report.get("overall_score", 0),
            "blocked_scenarios": final_report.get("blocked_scenarios", []),
            "scenario_count": len(final_report.get("scenario_results") or []),
        }

    @tool("get_corrected_document_outputs")
    def get_corrected_document_outputs_tool(scenario_key: str) -> Dict[str, Any]:
        """시나리오 SubAgent가 생성한 문서별 보완본 JSON과 원 점검 결과를 반환합니다."""
        scenario = canonical_scenario_key(scenario_key)
        return get_corrected_document_outputs(run_id, scenario)

    @tool("run_self_quality_review")
    def run_self_quality_review_tool(scenario_key: str, threshold: int = 85) -> Dict[str, Any]:
        """문서별 보완본이 원 점검 결과를 제대로 교정했는지 검증합니다."""
        return run_self_quality_review(run_id, canonical_scenario_key(scenario_key), threshold)

    @tool("persist_self_quality_output")
    def persist_self_quality_output_tool(scenario_key: str, payload_json: str) -> str:
        """자가 교정 점검 결과를 JSON 파일로 저장합니다."""
        scenario = canonical_scenario_key(scenario_key)
        payload = parse_json(payload_json)
        if isinstance(payload, dict):
            payload.setdefault("scenario_key", scenario)
            payload.setdefault("agent_name", "self_quality_agent")
        file_path = DATA_ROOT / run_id / f"self_quality_agent_{scenario}.json"
        save_json(file_path, payload)
        return str(file_path)

    shared = [
        get_document_catalog_tool,
        get_document_preview_tool,
        get_scenario_definition_tool,
        persist_subagent_output_tool,
    ]
    report_tools = [
        get_document_catalog_tool,
        get_scenario_definition_tool,
        get_subagent_outputs_tool,
        build_final_review_report_tool,
    ]
    self_quality_tools = [
        get_corrected_document_outputs_tool,
        run_self_quality_review_tool,
        persist_self_quality_output_tool,
    ]
    return {
        "shared": shared,
        "guide": shared,
        "basic_quality": [
            get_scenario_definition_tool,
            run_basic_quality_review_tool,
            persist_subagent_output_tool,
        ],
        "traceability": [
            get_scenario_definition_tool,
            run_traceability_review_tool,
            persist_subagent_output_tool,
        ],
        "ui_match": [
            get_scenario_definition_tool,
            run_ui_match_review_tool,
            persist_subagent_output_tool,
        ],
        "coverage": [
            get_scenario_definition_tool,
            run_coverage_review_tool,
            persist_subagent_output_tool,
        ],
        "self_quality": self_quality_tools,
        "improvement": [
            get_scenario_definition_tool,
            build_improvement_actions_tool,
            persist_subagent_output_tool,
        ],
        "report": report_tools,
        "skills": {
            "orchestrator_agent": [str(SKILLS_ROOT / "orchestrator_agent")],
            "guide_agent": [str(SKILLS_ROOT / "guide_agent")],
            "qa_agent": [str(SKILLS_ROOT / "qa_agent")],
            "basic_quality_agent": [str(SKILLS_ROOT / "basic_quality_agent")],
            "traceability_agent": [str(SKILLS_ROOT / "traceability_agent")],
            "ui_match_agent": [str(SKILLS_ROOT / "ui_match_agent")],
            "coverage_agent": [str(SKILLS_ROOT / "coverage_agent")],
            "improvement_agent": [str(SKILLS_ROOT / "improvement_agent")],
            "self_quality_agent": [str(SKILLS_ROOT / "self_quality_agent")],
            "report_agent": [str(SKILLS_ROOT / "report_agent")],
        },
    }


def get_document_catalog_data(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """문서별 파서 상태와 행 수만 간단히 요약합니다."""
    return [
        {
            "document_key": document.get("document_key", ""),
            "saved_path": document.get("saved_path", ""),
            "document_label": DOCUMENT_LABELS.get(document.get("document_key", ""), document.get("document_label", "")),
            "file_name": document.get("file_name", ""),
            "parser_status": document.get("content_summary", {}).get("parser_status", "unknown"),
            "row_count": len(get_rows(document)),
        }
        for document in documents
    ]


def review_basic_quality(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """SKILL.md 기반 기초 품질 점검 - 모든 검증 규칙 적용."""
    findings: List[str] = []
    warnings: List[str] = []
    
    # 정규식 및 허용값 정의
    REQ_ID_PATTERN = r"^REQ-\d{3}$"
    FUNC_ID_PATTERN = r"^REQ-\d{3}-F\d{2}$"
    UI_ID_PATTERN = r"^UI-\d{3}$"
    DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
    OWNER_PATTERN = r"^[가-힣A-Za-z ]{2,20}$"
    ISOLATED_JAMO_PATTERN = r"[ㄱ-ㅎㅏ-ㅣ]"
    
    ALLOWED_STATUS = {"신규", "추가", "수정", "삭제", "진행중", "완료", "보류"}
    ALLOWED_UI_TYPES = {"화면", "팝업", "영역", "모바일", "배치", "컴포넌트"}
    ALLOWED_PRIORITY = {"1", "2", "3", "4", "5"}
    
    TYPO_DICTIONARY = {
        "모니터링ㄱ": "모니터링",
        "결괏": "결과",
        "누랑": "누락",
        "대시보트": "대시보드",
        "포멧팅": "포매팅",
        "에이전투": "에이전트",
        "Agnet": "Agent",
        "Desginer": "Designer",
        "재검토요망": "재검토 필요"
    }
    
    # 문서별 필수 컬럼 정의
    REQUIRED_COLUMNS = {
        "requirement_definition": [
            ("시스템(Application)", ["시스템", "Application", "시스템명"]),
            ("업무그룹", []),
            ("요구사항 ID", ["요구사항ID", "Req ID", "Requirement ID"]),
            ("요구사항명", []),
            ("요청자(요구사항 Owner)", ["요청자", "요구사항 Owner", "Owner"]),
            ("상태", []),
            ("최초요청일자", ["최초 요청일자", "요청일자"]),
            ("기능 요구사항", []),
            ("프로세스 요구사항", []),
            ("화면 요구사항", []),
            ("보안 요구사항", []),
            ("데이터 요구사항", []),
        ],
        "feature_definition": [
            ("시스템(Application)", ["시스템", "Application", "시스템명"]),
            ("요구사항 ID", ["요구사항ID", "Req ID", "Requirement ID"]),
            ("기능ID", ["기능 ID", "Function ID"]),
            ("기능명", []),
            ("요청자(요구사항 Owner)", ["요청자", "요구사항 Owner", "Owner"]),
            ("상태", []),
            ("설명", []),
            ("기능", []),
            ("입력", []),
            ("출력", []),
            ("화면ID", ["화면 ID", "UI ID", "Screen ID"]),
            ("우선순위", []),
        ],
        "ui_design": [
            ("시스템(Application)", ["시스템", "Application", "시스템명"]),
            ("업무그룹", []),
            ("요구사항 ID", ["요구사항ID", "Req ID", "Requirement ID"]),
            ("기능ID", ["기능 ID", "Function ID"]),
            ("화면ID", ["화면 ID", "UI ID", "Screen ID"]),
            ("화면명", []),
            ("화면유형", []),
            ("상태", []),
            ("사용자행위/버튼", []),
            ("권한", []),
        ],
    }
    
    # 검증 수행
    for document_key, document_label in DOCUMENT_LABELS.items():
        document = get_document(documents, document_key)
        
        # 1. 문서 존재 여부
        if document is None:
            findings.append(f"[G-DOC-001] {document_label} 문서가 없습니다.")
            continue
        
        rows = get_rows(document)
        columns = get_columns(document)
        
        # 2. 파싱 상태 확인
        if document.get("content_summary", {}).get("parser_status") != "success":
            findings.append(f"[G-DOC-001] {document_label} 문서 파싱 실패: {document.get('content_summary', {}).get('error_message', 'Unknown error')}")
            continue
        
        # 3. 데이터 행 확인
        if not rows:
            findings.append(f"[G-SHEET-001] {document_label}에 데이터 행이 없습니다.")
            continue
        
        # 4. 필수 컬럼 확인
        required_cols = REQUIRED_COLUMNS.get(document_key, [])
        col_map = {}  # 정규화된 컬럼 이름 매핑
        
        for primary_col, aliases in required_cols:
            normalized_primary = normalize(primary_col)
            found_col = None
            
            for col in columns:
                normalized_col = normalize(col)
                if normalized_col == normalized_primary or normalized_col in [normalize(a) for a in aliases]:
                    found_col = col
                    break
            
            if not found_col:
                findings.append(f"[REQ-COL-001/FUNC-COL-001/UI-COL-001] {document_label}에서 필수 컬럼 '{primary_col}'을 찾지 못했습니다.")
            else:
                col_map[primary_col] = found_col
        
        if len(col_map) < len(required_cols) * 0.6:
            findings.append(f"[G-HEADER-001] {document_label}의 필수 컬럼 인식률이 60% 미만입니다.")
            continue
        
        # 5. 행 단위 검증
        for row_idx, row in enumerate(rows, start=4):  # 데이터 행은 4행부터 시작
            # 빈 행 제거
            if not any(str(v).strip() for v in row.values()):
                warnings.append(f"[G-ROW-001] {document_label} {row_idx}행: 완전 빈 행입니다.")
                continue
            
            # 문서별 검증
            if document_key == "requirement_definition":
                _validate_requirement_row(row, col_map, row_idx, document_label, findings, warnings,
                                         REQ_ID_PATTERN, DATE_PATTERN, OWNER_PATTERN, ISOLATED_JAMO_PATTERN,
                                         ALLOWED_STATUS, TYPO_DICTIONARY)
            
            elif document_key == "feature_definition":
                _validate_function_row(row, col_map, row_idx, document_label, findings, warnings,
                                      REQ_ID_PATTERN, FUNC_ID_PATTERN, UI_ID_PATTERN, OWNER_PATTERN,
                                      ISOLATED_JAMO_PATTERN, ALLOWED_STATUS, ALLOWED_PRIORITY, TYPO_DICTIONARY)
            
            elif document_key == "ui_design":
                _validate_ui_row(row, col_map, row_idx, document_label, findings, warnings,
                                REQ_ID_PATTERN, FUNC_ID_PATTERN, UI_ID_PATTERN, ISOLATED_JAMO_PATTERN,
                                ALLOWED_STATUS, ALLOWED_UI_TYPES, TYPO_DICTIONARY)
    
    score = _calculate_score(findings, warnings)
    return {
        "scenario_key": "basic_quality",
        "summary": "SKILL.md 기준 기초 품질을 점검했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": make_actions("basic_quality", findings, warnings),
    }


def _validate_requirement_row(row, col_map, row_idx, doc_label, findings, warnings, 
                              req_id_pattern, date_pattern, owner_pattern, jamo_pattern,
                              allowed_status, typo_dict):
    """요구사항정의서 행 검증."""
    # 요구사항 ID 검증
    if "요구사항 ID" in col_map:
        req_id = str(row.get(col_map["요구사항 ID"], "")).strip()
        if not req_id:
            findings.append(f"[REQ-NAME-001] {doc_label} {row_idx}행: 요구사항 ID가 누락되었습니다.")
        elif not re.match(req_id_pattern, req_id):
            findings.append(_invalid_id_message(
                "REQ-ID-001", doc_label, row_idx, "요구사항 ID", req_id, "REQ-001", _suggest_req_id(req_id)
            ))
    
    # 요청자 검증
    if "요청자(요구사항 Owner)" in col_map:
        owner = str(row.get(col_map["요청자(요구사항 Owner)"], "")).strip()
        if not owner:
            findings.append(f"[REQ-OWNER-001] {doc_label} {row_idx}행: 요청자(요구사항 Owner)가 누락되었습니다.")
        elif not re.match(owner_pattern, owner):
            findings.append(f"[REQ-OWNER-001] {doc_label} {row_idx}행: 요청자 '{owner}'는 2~20자 한글/영문만 허용됩니다.")
    
    # 상태 검증
    if "상태" in col_map:
        status = str(row.get(col_map["상태"], "")).strip()
        if not status:
            findings.append(f"[G-VALUE-001] {doc_label} {row_idx}행: 상태가 누락되었습니다.")
        elif status not in allowed_status:
            findings.append(f"[G-STATUS-001] {doc_label} {row_idx}행: 상태 '{status}'은 허용값이 아닙니다.")
    
    # 최초요청일자 검증
    if "최초요청일자" in col_map:
        date_val = str(row.get(col_map["최초요청일자"], "")).strip()
        if not date_val:
            findings.append(f"[G-VALUE-001] {doc_label} {row_idx}행: 최초요청일자가 누락되었습니다.")
        elif not re.match(date_pattern, date_val):
            findings.append(f"[G-DATE-001] {doc_label} {row_idx}행: 날짜 '{date_val}'는 YYYY-MM-DD 형식이어야 합니다.")
    
    # 요구사항명 검증
    if "요구사항명" in col_map:
        name = str(row.get(col_map["요구사항명"], "")).strip()
        if not name:
            findings.append(f"[REQ-NAME-001] {doc_label} {row_idx}행: 요구사항명이 누락되었습니다.")
        elif re.search(jamo_pattern, name):
            warnings.append(f"[G-TYPO-001] {doc_label} {row_idx}행: 요구사항명 '{name}'에 단독 한글 자모가 포함되어 있습니다.")
        elif len(name) < 5:
            warnings.append(f"[REQ-BODY-002] {doc_label} {row_idx}행: 요구사항명 '{name}'은 5자 미만으로 구체성이 부족할 수 있습니다.")
    
    # 오탈자 검사
    for col_name in ["요구사항명", "기능 요구사항", "프로세스 요구사항"]:
        if col_name in col_map:
            val = str(row.get(col_map[col_name], ""))
            for typo, correct in typo_dict.items():
                if typo in val:
                    warnings.append(f"[G-TYPO-002] {doc_label} {row_idx}행 '{col_name}': '{typo}'은 '{correct}'로 수정 권장됩니다.")


def _validate_function_row(row, col_map, row_idx, doc_label, findings, warnings,
                           req_id_pattern, func_id_pattern, ui_id_pattern, owner_pattern,
                           jamo_pattern, allowed_status, allowed_priority, typo_dict):
    """기능정의서 행 검증."""
    # 요구사항 ID 검증
    if "요구사항 ID" in col_map:
        req_id = str(row.get(col_map["요구사항 ID"], "")).strip()
        if not req_id:
            findings.append(f"[FUNC-REQ-ID-001] {doc_label} {row_idx}행: 요구사항 ID가 누락되었습니다.")
        elif not re.match(req_id_pattern, req_id):
            findings.append(_invalid_id_message(
                "FUNC-REQ-ID-001", doc_label, row_idx, "요구사항 ID", req_id, "REQ-001", _suggest_req_id(req_id)
            ))
    
    # 기능ID 검증
    if "기능ID" in col_map:
        func_id = str(row.get(col_map["기능ID"], "")).strip()
        if not func_id:
            findings.append(f"[FUNC-ID-002] {doc_label} {row_idx}행: 기능ID가 누락되었습니다.")
        elif not re.match(func_id_pattern, func_id):
            findings.append(_invalid_id_message(
                "FUNC-ID-001", doc_label, row_idx, "기능ID", func_id, "REQ-001-F01", _suggest_func_id(func_id)
            ))
    
    # 기능명 검증
    if "기능명" in col_map:
        name = str(row.get(col_map["기능명"], "")).strip()
        if not name:
            findings.append(f"[FUNC-NAME-001] {doc_label} {row_idx}행: 기능명이 누락되었습니다.")
    
    # 요청자 검증
    if "요청자(요구사항 Owner)" in col_map:
        owner = str(row.get(col_map["요청자(요구사항 Owner)"], "")).strip()
        if not owner:
            findings.append(f"[FUNC-NAME-001] {doc_label} {row_idx}행: 요청자가 누락되었습니다.")
    
    # 상태 검증
    if "상태" in col_map:
        status = str(row.get(col_map["상태"], "")).strip()
        if not status:
            findings.append(f"[FUNC-STATUS-001] {doc_label} {row_idx}행: 상태가 누락되었습니다.")
        elif status not in allowed_status:
            findings.append(f"[G-STATUS-001] {doc_label} {row_idx}행: 상태 '{status}'는 허용값이 아닙니다.")
    
    # 화면ID 검증
    if "화면ID" in col_map:
        ui_id = str(row.get(col_map["화면ID"], "")).strip()
        if not ui_id:
            findings.append(f"[FUNC-UI-ID-001] {doc_label} {row_idx}행: 화면ID가 누락되었습니다.")
        elif not re.match(ui_id_pattern, ui_id):
            findings.append(_invalid_id_message(
                "FUNC-UI-ID-001", doc_label, row_idx, "화면ID", ui_id, "UI-001", _suggest_ui_id(ui_id)
            ))
    
    # 우선순위 검증
    if "우선순위" in col_map:
        priority = str(row.get(col_map["우선순위"], "")).strip()
        if not priority:
            findings.append(f"[FUNC-PRIORITY-001] {doc_label} {row_idx}행: 우선순위가 누락되었습니다.")
        elif priority not in allowed_priority:
            findings.append(f"[FUNC-PRIORITY-001] {doc_label} {row_idx}행: 우선순위 '{priority}'는 1~5 정수만 허용됩니다.")


def _validate_ui_row(row, col_map, row_idx, doc_label, findings, warnings,
                     req_id_pattern, func_id_pattern, ui_id_pattern, jamo_pattern,
                     allowed_status, allowed_ui_types, typo_dict):
    """UI설계서 행 검증."""
    # 요구사항 ID 검증
    if "요구사항 ID" in col_map:
        req_id = str(row.get(col_map["요구사항 ID"], "")).strip()
        if req_id and not re.match(req_id_pattern, req_id):
            findings.append(_invalid_id_message(
                "UI-REQ-ID-001", doc_label, row_idx, "요구사항 ID", req_id, "REQ-001", _suggest_req_id(req_id)
            ))
    
    # 기능ID 검증
    if "기능ID" in col_map:
        func_id = str(row.get(col_map["기능ID"], "")).strip()
        if func_id and not re.match(func_id_pattern, func_id):
            findings.append(_invalid_id_message(
                "UI-FUNC-ID-001", doc_label, row_idx, "기능ID", func_id, "REQ-001-F01", _suggest_func_id(func_id)
            ))
    
    # 화면ID 검증
    if "화면ID" in col_map:
        ui_id = str(row.get(col_map["화면ID"], "")).strip()
        if not ui_id:
            findings.append(f"[UI-ID-001] {doc_label} {row_idx}행: 화면ID가 누락되었습니다.")
        elif not re.match(ui_id_pattern, ui_id):
            findings.append(_invalid_id_message(
                "UI-ID-001", doc_label, row_idx, "화면ID", ui_id, "UI-001", _suggest_ui_id(ui_id)
            ))
    
    # 화면명 검증
    if "화면명" in col_map:
        name = str(row.get(col_map["화면명"], "")).strip()
        if not name:
            findings.append(f"[UI-NAME-001] {doc_label} {row_idx}행: 화면명이 누락되었습니다.")
    
    # 화면유형 검증
    if "화면유형" in col_map:
        ui_type = str(row.get(col_map["화면유형"], "")).strip()
        if not ui_type:
            findings.append(f"[UI-TYPE-001] {doc_label} {row_idx}행: 화면유형이 누락되었습니다.")
        elif ui_type not in allowed_ui_types:
            findings.append(f"[UI-TYPE-001] {doc_label} {row_idx}행: 화면유형 '{ui_type}'는 허용값이 아닙니다.")
    
    # 상태 검증
    if "상태" in col_map:
        status = str(row.get(col_map["상태"], "")).strip()
        if not status:
            findings.append(f"[UI-STATUS-001] {doc_label} {row_idx}행: 상태가 누락되었습니다.")
    
    # 권한 검증
    if "권한" in col_map:
        auth = str(row.get(col_map["권한"], "")).strip()
        if not auth:
            findings.append(f"[UI-AUTH-001] {doc_label} {row_idx}행: 권한이 누락되었습니다.")


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
    feature_id_col = find_column(feature_rows, ["기능id"])
    ui_feature_id_col = find_column(ui_rows, ["기능id"])
    name_col = find_column(feature_rows, ["기능명"])
    feature_desc_cols = [
        column for column in [
            name_col,
            find_column(feature_rows, ["설명"]),
            find_column(feature_rows, ["기능"]),
        ] if column
    ]
    feature_input_col = find_column(feature_rows, ["입력"])
    feature_output_col = find_column(feature_rows, ["출력"])
    ui_name_col = find_column(ui_rows, ["화면명"])
    ui_action_col = find_column(ui_rows, ["사용자행위", "버튼"])
    ui_input_col = find_column(ui_rows, ["주요 입력", "입력"])
    ui_output_col = find_column(ui_rows, ["주요 출력", "출력"])

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
    if not feature_id_col:
        warnings.append("기능 정의서에서 기능ID 컬럼을 찾지 못해 기능ID 기준 내용 일치성 검증이 제한됩니다.")
    if not ui_feature_id_col:
        warnings.append("UI 설계서에서 기능ID 컬럼을 찾지 못해 화면ID 기준으로 보조 매칭합니다.")

    ui_by_feature_id = group_rows_by_value(ui_rows, ui_feature_id_col)
    ui_by_screen_id = group_rows_by_value(ui_rows, ui_screen_col)

    for feature_row in feature_rows:
        feature_id = cell_value(feature_row, feature_id_col)
        screen_id = cell_value(feature_row, screen_col)
        feature_name = cell_value(feature_row, name_col) or feature_id or screen_id
        matched_ui_rows = ui_by_feature_id.get(feature_id, []) if feature_id else []
        if not matched_ui_rows and screen_id:
            matched_ui_rows = ui_by_screen_id.get(screen_id, [])
        if not matched_ui_rows:
            continue

        feature_text = row_text(feature_row, feature_desc_cols)
        ui_text = row_text(matched_ui_rows, [ui_name_col, ui_action_col, ui_input_col, ui_output_col])
        ui_action_text = row_text(matched_ui_rows, [ui_action_col])
        feature_actions = detect_action_terms(feature_text)
        ui_actions = detect_action_terms(ui_action_text)
        feature_tokens = significant_tokens(feature_text)
        ui_tokens = significant_tokens(ui_text)

        missing_actions = sorted(
            action for action in feature_actions
            if action not in ui_actions and action not in {"검증"}
        )
        if missing_actions:
            findings.append(
                f"기능-UI 행위 불일치: 기능ID {feature_id or '(미기재)'} / 화면ID {screen_id or '(미기재)'} "
                f"기능 '{feature_name}'에는 {', '.join(missing_actions)} 행위가 필요하지만 UI 설계서 사용자행위/버튼에서 확인되지 않습니다."
            )

        unsupported_ui_actions = sorted(
            action for action in ui_actions - feature_actions
            if action in {"삭제", "승인", "반려", "완료", "마감", "확정"}
        )
        if unsupported_ui_actions:
            findings.append(
                f"기능 범위 밖 UI 행위: 기능ID {feature_id or '(미기재)'} / 화면ID {screen_id or '(미기재)'} "
                f"기능 '{feature_name}'에 근거가 약한 UI 행위가 있습니다. 예: {', '.join(unsupported_ui_actions)}"
            )

        if feature_tokens and ui_tokens and not (feature_tokens & ui_tokens):
            warnings.append(
                f"기능-UI 용어 일치도 낮음: 기능ID {feature_id or '(미기재)'} "
                f"기능명 '{feature_name}'과 UI 화면/행위의 핵심 용어가 거의 겹치지 않습니다."
            )

        missing_inputs = missing_field_terms(cell_value(feature_row, feature_input_col), row_text(matched_ui_rows, [ui_input_col]))
        if missing_inputs:
            warnings.append(
                f"UI 입력항목 보완 필요: 기능ID {feature_id or '(미기재)'} "
                f"기능 입력 '{', '.join(missing_inputs[:3])}'이 UI 주요 입력항목에서 명확히 확인되지 않습니다."
            )

        missing_outputs = missing_field_terms(cell_value(feature_row, feature_output_col), row_text(matched_ui_rows, [ui_output_col]))
        if missing_outputs:
            warnings.append(
                f"UI 출력항목 보완 필요: 기능ID {feature_id or '(미기재)'} "
                f"기능 출력 '{', '.join(missing_outputs[:3])}'이 UI 주요 출력항목에서 명확히 확인되지 않습니다."
            )

    score = calculate_semantic_review_score(findings, warnings)
    recommendations = make_ui_match_recommendations(findings, warnings)
    return {
        "scenario_key": "ui_match",
        "summary": "기능 정의와 UI 설계 간 기능ID/화면ID 매핑 및 실제 행위/입출력 일치성을 점검했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def review_coverage(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """요구사항 대비 기능 완전성 점검."""
    requirement_rows = get_rows(get_document(documents, "requirement_definition"))
    feature_rows = get_rows(get_document(documents, "feature_definition"))
    ui_rows = get_rows(get_document(documents, "ui_design"))

    req_id_col = find_column(requirement_rows, ["요구사항 id"])
    feat_req_col = find_column(feature_rows, ["요구사항 id"])
    ui_req_col = find_column(ui_rows, ["요구사항 id"])
    req_name_col = find_column(requirement_rows, ["요구사항명"])
    req_body_cols = [
        column for column in [
            req_name_col,
            find_column(requirement_rows, ["기능 요구사항"]),
            find_column(requirement_rows, ["프로세스 요구사항"]),
            find_column(requirement_rows, ["화면 요구사항"]),
            find_column(requirement_rows, ["기타 요구사항"]),
        ] if column
    ]
    feature_id_col = find_column(feature_rows, ["기능id"])
    feature_name_col = find_column(feature_rows, ["기능명"])
    feature_body_cols = [
        column for column in [
            feature_name_col,
            find_column(feature_rows, ["설명"]),
            find_column(feature_rows, ["기능"]),
            find_column(feature_rows, ["입력"]),
            find_column(feature_rows, ["출력"]),
        ] if column
    ]
    ui_body_cols = [
        column for column in [
            find_column(ui_rows, ["화면명"]),
            find_column(ui_rows, ["사용자행위", "버튼"]),
            find_column(ui_rows, ["주요 입력", "입력"]),
            find_column(ui_rows, ["주요 출력", "출력"]),
        ] if column
    ]
    req_ids = set(non_empty_values(requirement_rows, req_id_col))
    feat_req_ids = set(non_empty_values(feature_rows, feat_req_col))
    ui_req_ids = set(non_empty_values(ui_rows, ui_req_col))
    features_by_req = group_rows_by_value(feature_rows, feat_req_col)
    ui_by_req = group_rows_by_value(ui_rows, ui_req_col)

    findings: List[str] = []
    warnings: List[str] = []

    missing_feature_req_ids = missing_values(req_ids, feat_req_ids)
    if missing_feature_req_ids:
        findings.append(f"요구사항 대비 기능 정의가 누락된 항목이 있습니다. 예: {', '.join(missing_feature_req_ids[:3])}")
    missing_ui_req_ids = missing_values(req_ids, ui_req_ids)
    if missing_ui_req_ids:
        findings.append(f"요구사항 대비 UI 설계가 누락된 항목이 있습니다. 예: {', '.join(missing_ui_req_ids[:3])}")

    extra_feature_req_ids = missing_values(feat_req_ids, req_ids)
    if extra_feature_req_ids:
        warnings.append(f"요구사항 정의서에 없는 요구사항 ID를 참조하는 기능 정의가 있습니다. 예: {', '.join(extra_feature_req_ids[:3])}")

    for req_row in requirement_rows:
        req_id = cell_value(req_row, req_id_col)
        if not req_id:
            continue
        req_name = cell_value(req_row, req_name_col) or req_id
        req_text = row_text(req_row, req_body_cols)
        req_actions = refine_requirement_actions(detect_action_terms(req_text), cell_value(req_row, req_name_col))
        matched_features = features_by_req.get(req_id, [])
        matched_ui_rows = ui_by_req.get(req_id, [])
        feature_text = row_text(matched_features, feature_body_cols)
        ui_text = row_text(matched_ui_rows, ui_body_cols)
        ui_action_text = row_text(matched_ui_rows, [find_column(ui_rows, ["사용자행위", "버튼"])])
        feature_actions = detect_action_terms(feature_text)
        ui_actions = detect_action_terms(ui_action_text)

        missing_feature_actions = sorted(action for action in req_actions - feature_actions if action not in {"검증"})
        if matched_features and missing_feature_actions:
            findings.append(
                f"기능 정의 보완 필요: 요구사항 {req_id} '{req_name}'의 핵심 행위 "
                f"{', '.join(missing_feature_actions)}가 기능 정의서에 충분히 반영되지 않았습니다."
            )

        missing_ui_actions = sorted(action for action in req_actions - ui_actions if action in UI_RELEVANT_ACTIONS)
        if matched_ui_rows and missing_ui_actions:
            warnings.append(
                f"UI 설계 보완 필요: 요구사항 {req_id} '{req_name}'의 화면 행위 "
                f"{', '.join(missing_ui_actions)}가 UI 설계서에서 명확히 확인되지 않습니다."
            )

        if len(req_actions) >= 3 and len(matched_features) <= 1:
            warnings.append(
                f"기능 분해 검토 필요: 요구사항 {req_id} '{req_name}'은 여러 핵심 행위({', '.join(sorted(req_actions))})를 포함하지만 "
                f"기능 정의가 {len(matched_features)}건입니다."
            )

        for feature_row in matched_features:
            feature_id = cell_value(feature_row, feature_id_col)
            feature_name = cell_value(feature_row, feature_name_col) or feature_id
            feature_actions_for_row = detect_action_terms(row_text(feature_row, feature_body_cols))
            extra_actions = sorted(
                action for action in feature_actions_for_row - req_actions
                if action in {"삭제", "승인", "반려", "완료", "취소", "마감"}
            )
            if extra_actions:
                warnings.append(
                    f"과잉 기능 후보: 기능ID {feature_id or '(미기재)'} '{feature_name}'의 "
                    f"{', '.join(extra_actions)} 행위는 요구사항 {req_id} 근거가 약합니다."
                )

    if len(feature_rows) < len(requirement_rows):
        warnings.append("기능 정의 행 수가 요구사항 수보다 적어 세부 기능 분해가 부족할 수 있습니다.")

    score = calculate_semantic_review_score(findings, warnings)
    recommendations = make_coverage_recommendations(findings, warnings)
    return {
        "scenario_key": "coverage",
        "summary": "요구사항 대비 기능 정의와 UI 설계의 누락, 과잉, 분해 부족을 분석했습니다.",
        "score": score,
        "findings": findings,
        "warnings": warnings,
        "recommendations": recommendations,
    }


ACTION_KEYWORDS = {
    "로그인": {"로그인", "인증", "sso"},
    "조회": {"조회", "검색", "확인"},
    "상세조회": {"상세조회", "상세보기", "상세", "팝업"},
    "등록": {"등록", "저장", "작성"},
    "임시저장": {"임시저장"},
    "수정": {"수정", "변경", "편집"},
    "삭제": {"삭제", "제거"},
    "필터": {"필터", "필터적용"},
    "정렬": {"정렬", "정렬변경"},
    "스캔": {"스캔", "scan"},
    "투입": {"투입"},
    "검증": {"검증", "체크", "유효성"},
    "승인": {"승인"},
    "반려": {"반려"},
    "완료": {"완료", "완료처리"},
    "취소": {"취소"},
    "마감": {"마감"},
    "확정": {"확정"},
    "발급": {"발급"},
    "다운로드": {"다운로드", "내보내기"},
    "업로드": {"업로드", "가져오기"},
}

UI_RELEVANT_ACTIONS = {
    "로그인", "조회", "상세조회", "등록", "임시저장", "수정", "삭제",
    "필터", "정렬", "스캔", "투입", "승인", "반려", "완료", "취소",
    "마감", "확정", "발급", "다운로드", "업로드",
}

GENERIC_TOKENS = {
    "기능", "화면", "결과", "정보", "목록", "사용자", "기반", "조건", "항목",
    "주요", "정의", "설계", "처리", "입력", "출력", "버튼", "행위",
}


def cell_value(row: Dict[str, Any], column_name: Optional[str]) -> str:
    """행에서 문자열 값을 안전하게 꺼냅니다."""
    if not column_name:
        return ""
    return str(row.get(column_name, "")).strip()


def row_text(rows_or_row: Any, columns: List[Optional[str]]) -> str:
    """지정한 컬럼 값을 비교용 텍스트로 합칩니다."""
    rows = rows_or_row if isinstance(rows_or_row, list) else [rows_or_row]
    values: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in columns:
            if column:
                value = cell_value(row, column)
                if value:
                    values.append(value)
    return " ".join(values)


def group_rows_by_value(rows: List[Dict[str, Any]], column_name: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """특정 컬럼 값을 기준으로 행을 그룹화합니다."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not column_name:
        return grouped
    for row in rows:
        value = cell_value(row, column_name)
        if value:
            grouped.setdefault(value, []).append(row)
    return grouped


def detect_action_terms(text: str) -> set:
    """기능/요구사항/UI 텍스트에서 핵심 행위 용어를 추출합니다."""
    normalized_text = normalize(text)
    actions = set()
    for action, keywords in ACTION_KEYWORDS.items():
        if any(normalize(keyword) in normalized_text for keyword in keywords):
            actions.add(action)

    # 상세조회는 보통 "상세"와 "조회"가 분리되어 표현될 수 있습니다.
    if "상세" in normalized_text and ("조회" in normalized_text or "보기" in normalized_text):
        actions.add("상세조회")
    return actions


def refine_requirement_actions(actions: set, requirement_name: str) -> set:
    """요구사항 본문의 보조 표현이 핵심 기능 누락으로 과검출되지 않도록 보정합니다."""
    refined = set(actions)
    name_actions = detect_action_terms(requirement_name)

    # "조회 후 다운로드", "입력 후 완료 처리"처럼 보조 단계로 등장한 행위는
    # 요구사항명에 없으면 기능 누락 판단에서 한 단계 낮춥니다.
    for supporting_action in {"조회", "완료", "투입", "검증"}:
        if supporting_action in refined and supporting_action not in name_actions and len(refined) > 1:
            refined.remove(supporting_action)

    return refined


def calculate_semantic_review_score(findings: List[str], warnings: List[str]) -> int:
    """의미 기반 점검은 반복 이슈가 많아도 감점 상한을 둬 과도한 0점을 방지합니다."""
    finding_penalty = min(60, len(findings) * 8)
    warning_penalty = min(25, len(warnings) * 2)
    return max(0, round(100 - finding_penalty - warning_penalty))


def significant_tokens(text: str) -> set:
    """기능명/화면명 비교용 핵심 토큰을 추출합니다."""
    tokens = set(extract_tokens(text))
    return {token for token in tokens if token not in GENERIC_TOKENS and not token.isdigit()}


def split_field_terms(text: str) -> List[str]:
    """입력/출력 항목 문자열을 개별 항목 후보로 분리합니다."""
    terms = []
    for part in re.split(r"[,/·|、，\n]+", str(text or "")):
        cleaned = part.strip()
        if cleaned and len(cleaned) >= 2:
            terms.append(cleaned)
    return terms


def missing_field_terms(source_text: str, target_text: str) -> List[str]:
    """source의 항목이 target에 명확히 포함되는지 확인합니다."""
    normalized_target = normalize(target_text)
    missing = []
    for term in split_field_terms(source_text):
        normalized_term = normalize(term)
        if normalized_term and normalized_term not in normalized_target:
            missing.append(term)
    return missing


def make_ui_match_recommendations(findings: List[str], warnings: List[str]) -> List[str]:
    """기능-UI 일치성 점검 결과에 맞는 개선 권고를 생성합니다."""
    if not findings and not warnings:
        return ["기능 정의서와 UI 설계서의 기능ID/화면ID 및 주요 행위 일치 상태를 정기 점검하세요."]

    actions = set()
    joined = "\n".join([*findings, *warnings])
    if "기능 정의서의 화면ID가 UI 설계서에 없습니다" in joined:
        actions.add("기능 정의서의 화면ID를 UI 설계서에 추가하거나, 잘못된 화면ID를 올바른 UI-### 값으로 재매핑하세요.")
    if "기능-UI 행위 불일치" in joined:
        actions.add("기능정의서의 기능명/기능 설명과 UI설계서의 사용자행위/버튼을 기능ID 기준으로 맞추세요.")
    if "기능 범위 밖 UI 행위" in joined:
        actions.add("UI에만 존재하는 삭제/승인/취소 등 고위험 버튼은 제거하거나 요구사항 및 기능정의서에 근거를 추가하세요.")
    if "입력항목" in joined:
        actions.add("기능정의서의 입력 항목이 UI설계서 주요 입력항목에 반영되도록 화면 입력 필드를 보완하세요.")
    if "출력항목" in joined:
        actions.add("기능정의서의 출력 항목이 UI설계서 주요 출력항목에 반영되도록 화면 출력 정보를 보완하세요.")
    if "용어 일치도 낮음" in joined:
        actions.add("기능명과 화면명/버튼 용어를 동일한 업무 용어로 정렬하세요.")
    actions.add("수정 후 SC-003 기능-UI 일치성 점검을 재수행하세요.")
    return list(actions)


def make_coverage_recommendations(findings: List[str], warnings: List[str]) -> List[str]:
    """요구사항 커버리지 점검 결과에 맞는 개선 권고를 생성합니다."""
    if not findings and not warnings:
        return ["요구사항과 기능정의서/UI설계서 간 커버리지 상태를 정기 점검하세요."]

    actions = set()
    joined = "\n".join([*findings, *warnings])
    if "기능 정의가 누락" in joined:
        actions.add("누락된 요구사항 ID에 대해 기능ID를 발급하고 기능명, 설명, 입력, 출력, 화면ID를 기능정의서에 추가하세요.")
    if "UI 설계가 누락" in joined:
        actions.add("누락된 요구사항 ID에 대해 화면ID와 사용자행위/버튼, 주요 입력/출력 항목을 UI설계서에 추가하세요.")
    if "기능 정의 보완 필요" in joined:
        actions.add("요구사항의 핵심 행위가 기능정의서에 빠진 항목은 기능을 추가하거나 기존 기능 설명을 보강하세요.")
    if "UI 설계 보완 필요" in joined:
        actions.add("요구사항의 화면 행위가 UI설계서에 드러나도록 화면명, 버튼, 입력/출력 항목을 보완하세요.")
    if "기능 분해 검토 필요" in joined:
        actions.add("여러 핵심 행위를 포함한 요구사항은 목록조회/상세조회/등록/삭제 등 독립 기능 단위로 분해하세요.")
    if "과잉 기능 후보" in joined:
        actions.add("요구사항 근거가 약한 과잉 기능은 요구사항에 반영하거나 기능정의서에서 제거 여부를 결정하세요.")
    actions.add("수정 후 SC-004 요구사항 커버리지 점검을 재수행하세요.")
    return list(actions)


def persist_corrected_documents(
    run_id: str,
    documents: List[Dict[str, Any]],
    scenario_key: str,
    agent_name: str,
    review_payload: Dict[str, Any],
) -> List[str]:
    """시나리오 점검 결과를 반영한 문서별 보완본 JSON을 저장합니다."""
    scenario = canonical_scenario_key(scenario_key) or canonical_scenario_key(agent_name)
    output_prefix = corrected_output_prefix(scenario, agent_name)
    outputs: Dict[str, Dict[str, Any]] = {}
    changes_by_document: Dict[str, List[Dict[str, Any]]] = {key: [] for key in DOCUMENT_LABELS}
    warnings_by_document: Dict[str, List[str]] = {key: [] for key in DOCUMENT_LABELS}

    for document_key in DOCUMENT_LABELS:
        document = get_document(documents, document_key)
        outputs[document_key] = build_corrected_document_payload(
            document_key=document_key,
            document=document,
            scenario_key=scenario,
            agent_name=agent_name,
            review_payload=review_payload,
        )
        if scenario != "traceability":
            apply_common_document_corrections(
                document_key,
                outputs[document_key],
                scenario,
                changes_by_document[document_key],
                warnings_by_document[document_key],
            )

    if scenario == "traceability":
        apply_traceability_document_corrections(outputs, changes_by_document, warnings_by_document)
    elif scenario == "ui_match":
        apply_ui_match_document_corrections(outputs, changes_by_document, warnings_by_document)
    elif scenario == "coverage":
        apply_coverage_document_corrections(outputs, changes_by_document, warnings_by_document)

    if scenario == "traceability":
        connection_report = build_traceability_connection_report(
            run_id=run_id,
            outputs=outputs,
            changes_by_document=changes_by_document,
            warnings_by_document=warnings_by_document,
        )
        file_path = traceability_connection_report_path(run_id)
        save_json(file_path, connection_report)
        return [str(file_path)]

    saved_paths: List[str] = []
    for document_key, payload in outputs.items():
        payload["correction_metadata"]["applied_changes"] = changes_by_document[document_key]
        payload["correction_metadata"]["remaining_warnings"] = warnings_by_document[document_key]
        payload["correction_metadata"]["change_count"] = len(changes_by_document[document_key])
        file_path = corrected_document_output_path(run_id, scenario, output_prefix, document_key)
        save_json(file_path, payload)
        saved_paths.append(str(file_path))

    return saved_paths


def maybe_persist_corrected_documents(
    run_id: str,
    documents: List[Dict[str, Any]],
    scenario_key: str,
    agent_name: str,
    review_payload: Dict[str, Any],
) -> List[str]:
    """Persist corrected document outputs only for agents that actually perform corrections."""
    scenario = canonical_scenario_key(scenario_key) or canonical_scenario_key(agent_name)
    if scenario == "coverage":
        return []
    return persist_corrected_documents(run_id, documents, scenario, agent_name, review_payload)


def build_corrected_document_payload(
    document_key: str,
    document: Optional[Dict[str, Any]],
    scenario_key: str,
    agent_name: str,
    review_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """원본 파싱 JSON 구조를 유지하면서 보완본 메타데이터를 붙입니다."""
    if document is None:
        payload: Dict[str, Any] = {
            "parser": "missing_document",
            "parser_status": "not_found",
            "sheet_count": 0,
            "sheet_names": [],
            "sheets": [],
        }
    else:
        payload = deepcopy(document.get("content_summary", {}))
        if not isinstance(payload, dict):
            payload = {"parser": "unknown", "parser_status": "invalid_payload", "sheets": []}

    payload.setdefault("sheets", [])
    payload["correction_metadata"] = {
        "document_key": document_key,
        "document_label": DOCUMENT_LABELS.get(document_key, document_key),
        "source_agent": sanitize_name(agent_name),
        "scenario_key": scenario_key,
        "source_file_name": document.get("file_name", "") if document else "",
        "source_saved_path": document.get("saved_path", "") if document else "",
        "source_review": {
            "summary": review_payload.get("summary", ""),
            "score": review_payload.get("score"),
            "findings": list(review_payload.get("findings") or []),
            "warnings": list(review_payload.get("warnings") or []),
            "recommendations": list(review_payload.get("recommendations") or []),
        },
        "self_quality_check_target": True,
        "note": "자가 품질 점검 Agent가 원본 대비 보완 적용 여부를 검증할 수 있도록 생성한 문서별 보완본입니다.",
        "applied_changes": [],
        "remaining_warnings": [],
        "change_count": 0,
    }
    return payload


def apply_common_document_corrections(
    document_key: str,
    payload: Dict[str, Any],
    scenario_key: str,
    changes: List[Dict[str, Any]],
    remaining_warnings: List[str],
) -> None:
    """모든 시나리오에서 안전하게 적용할 수 있는 기초 보정을 수행합니다."""
    del scenario_key
    allowed_status = {"신규", "추가", "수정", "삭제", "진행중", "완료", "보류"}
    typo_dictionary = {
        "모니터링ㄱ": "모니터링",
        "결괏": "결과",
        "누랑": "누락",
        "대시보트": "대시보드",
        "포멧팅": "포매팅",
        "에이전투": "에이전트",
        "Agnet": "Agent",
        "Desginer": "Designer",
        "재검토요망": "재검토 필요",
    }

    for sheet in payload.get("sheets", []):
        rows = sheet.get("data", [])
        if not isinstance(rows, list):
            continue
        columns = sheet.get("columns", [])
        if not isinstance(columns, list):
            columns = []

        req_col = find_column_name(columns, ["요구사항 id"])
        func_col = find_column_name(columns, ["기능id"])
        ui_col = find_column_name(columns, ["화면id"])
        status_col = find_column_name(columns, ["상태"])
        priority_col = find_column_name(columns, ["우선순위"])
        ui_type_col = find_column_name(columns, ["화면유형"])

        for row_index, row in enumerate(rows, start=4):
            if not isinstance(row, dict):
                continue

            for column_name, raw_value in list(row.items()):
                if not isinstance(raw_value, str):
                    continue
                cleaned = re.sub(r"[\t\r\n]+", " ", raw_value).strip()
                for typo, corrected in typo_dictionary.items():
                    cleaned = cleaned.replace(typo, corrected)
                update_cell_if_changed(
                    row,
                    column_name,
                    cleaned,
                    document_key,
                    sheet.get("sheet_name", ""),
                    row_index,
                    changes,
                    "trim_typo_control_characters",
                )

            normalize_id_cell(row, req_col, _suggest_req_id, document_key, sheet, row_index, changes)
            normalize_id_cell(row, func_col, _suggest_func_id, document_key, sheet, row_index, changes)
            normalize_id_cell(row, ui_col, _suggest_ui_id, document_key, sheet, row_index, changes)

            if status_col:
                status = str(row.get(status_col, "")).strip()
                if not status:
                    update_cell_if_changed(
                        row,
                        status_col,
                        "신규",
                        document_key,
                        sheet.get("sheet_name", ""),
                        row_index,
                        changes,
                        "fill_missing_status",
                    )
                elif status not in allowed_status:
                    remaining_warnings.append(
                        f"{DOCUMENT_LABELS[document_key]} {row_index}행 상태 '{status}'은 자동 확정하기 어려워 자가점검이 필요합니다."
                    )

            if priority_col:
                priority = str(row.get(priority_col, "")).strip()
                if not priority:
                    update_cell_if_changed(
                        row,
                        priority_col,
                        "3",
                        document_key,
                        sheet.get("sheet_name", ""),
                        row_index,
                        changes,
                        "fill_missing_priority",
                    )
                elif priority.isdigit() and int(priority) > 5:
                    update_cell_if_changed(
                        row,
                        priority_col,
                        "5",
                        document_key,
                        sheet.get("sheet_name", ""),
                        row_index,
                        changes,
                        "cap_priority_to_allowed_range",
                    )

            if ui_type_col and not str(row.get(ui_type_col, "")).strip():
                update_cell_if_changed(
                    row,
                    ui_type_col,
                    "화면",
                    document_key,
                    sheet.get("sheet_name", ""),
                    row_index,
                    changes,
                    "fill_missing_ui_type",
                )


def apply_traceability_document_corrections(
    outputs: Dict[str, Dict[str, Any]],
    changes_by_document: Dict[str, List[Dict[str, Any]]],
    warnings_by_document: Dict[str, List[str]],
) -> None:
    """ID 연결성 보완을 위해 누락된 연결 후보 행을 생성합니다."""
    requirement_rows = output_rows(outputs["requirement_definition"])
    feature_rows = output_rows(outputs["feature_definition"])
    ui_rows = output_rows(outputs["ui_design"])

    req_col = find_column(requirement_rows, ["요구사항 id"])
    feat_req_col = find_column(feature_rows, ["요구사항 id"])
    feat_screen_col = find_column(feature_rows, ["화면id"])
    ui_screen_col = find_column(ui_rows, ["화면id"])

    req_ids = set(non_empty_values(requirement_rows, req_col))
    feature_req_ids = set(non_empty_values(feature_rows, feat_req_col))
    ui_screen_ids = set(non_empty_values(ui_rows, ui_screen_col))

    for req_id in missing_values(req_ids, feature_req_ids):
        requirement_row = first_row_by_value(requirement_rows, req_col, req_id)
        added = append_feature_candidate(outputs["feature_definition"], requirement_row, req_id, "traceability-agent 연결 보완 후보")
        if added:
            changes_by_document["feature_definition"].append(added)

    if feat_screen_col and ui_screen_col:
        for feature_row in feature_rows:
            screen_id = str(feature_row.get(feat_screen_col, "")).strip()
            if not screen_id or screen_id in ui_screen_ids:
                continue
            added = append_ui_candidate(outputs["ui_design"], feature_row, screen_id, "traceability-agent 화면 연결 보완 후보")
            if added:
                ui_screen_ids.add(screen_id)
                changes_by_document["ui_design"].append(added)
    else:
        warnings_by_document["ui_design"].append("화면ID 컬럼을 찾지 못해 traceability 보완 행 자동 생성이 제한되었습니다.")


def build_traceability_connection_report(
    run_id: str,
    outputs: Dict[str, Dict[str, Any]],
    changes_by_document: Dict[str, List[Dict[str, Any]]],
    warnings_by_document: Dict[str, List[str]],
) -> Dict[str, Any]:
    """Build a traceability-specific report focused on requirement-feature-UI links."""
    requirement_rows = output_rows(outputs["requirement_definition"])
    feature_rows = output_rows(outputs["feature_definition"])
    ui_rows = output_rows(outputs["ui_design"])

    req_id_col = find_column(requirement_rows, ["요구사항 id", "요구사항id", "requirement id"])
    req_name_col = find_column(requirement_rows, ["요구사항명", "requirement name"])
    feat_req_col = find_column(feature_rows, ["요구사항 id", "요구사항id", "requirement id"])
    feature_id_col = find_column(feature_rows, ["기능id", "기능 id", "function id", "feature id"])
    feature_name_col = find_column(feature_rows, ["기능명", "function name", "feature name"])
    feature_screen_col = find_column(feature_rows, ["화면id", "화면 id", "screen id", "ui id"])
    ui_req_col = find_column(ui_rows, ["요구사항 id", "요구사항id", "requirement id"])
    ui_feature_id_col = find_column(ui_rows, ["기능id", "기능 id", "function id", "feature id"])
    ui_screen_col = find_column(ui_rows, ["화면id", "화면 id", "screen id", "ui id"])
    ui_name_col = find_column(ui_rows, ["화면명", "screen name", "ui name"])

    feature_by_req = group_rows_by_value(feature_rows, feat_req_col)
    ui_by_feature = group_rows_by_value(ui_rows, ui_feature_id_col)
    ui_by_screen = group_rows_by_value(ui_rows, ui_screen_col)
    traceability_changes = collect_traceability_changes(changes_by_document)
    added_feature_req_ids = {
        change_after_value(change, ["요구사항 id", "요구사항id", "requirement id"])
        for change in traceability_changes
        if change.get("reason") == "append_feature_candidate"
    }
    added_ui_feature_ids = {
        change_after_value(change, ["기능id", "기능 id", "function id", "feature id"])
        for change in traceability_changes
        if change.get("reason") == "append_ui_candidate"
    }
    added_ui_screen_ids = {
        change_after_value(change, ["화면id", "화면 id", "screen id", "ui id"])
        for change in traceability_changes
        if change.get("reason") == "append_ui_candidate"
    }
    added_feature_req_ids.discard("")
    added_ui_feature_ids.discard("")
    added_ui_screen_ids.discard("")

    requirement_links: List[Dict[str, Any]] = []
    for requirement_row in requirement_rows:
        req_id = cell_value(requirement_row, req_id_col)
        if not req_id:
            continue

        linked_features = feature_by_req.get(req_id, [])
        feature_ids = compact_unique(cell_value(row, feature_id_col) for row in linked_features)
        feature_names = compact_unique(cell_value(row, feature_name_col) for row in linked_features)
        screen_ids = compact_unique(cell_value(row, feature_screen_col) for row in linked_features)
        correction_applied = req_id in added_feature_req_ids
        status = "corrected" if correction_applied else ("linked" if linked_features else "missing_feature")
        requirement_links.append({
            "requirement_id": req_id,
            "requirement_name": cell_value(requirement_row, req_name_col),
            "status": status,
            "status_label": "보완됨" if status == "corrected" else ("연결됨" if status == "linked" else "기능 누락"),
            "correction_applied": correction_applied,
            "feature_count": len(linked_features),
            "feature_ids": feature_ids,
            "feature_names": feature_names,
            "screen_ids": screen_ids,
            "action": "기능 후보 추가됨, 담당자 검토 필요" if correction_applied else ("기능 정의 연결 확인" if status == "linked" else "기능 정의서에 요구사항 기반 기능 후보를 추가/검토"),
        })

    feature_links: List[Dict[str, Any]] = []
    for feature_row in feature_rows:
        feature_id = cell_value(feature_row, feature_id_col)
        req_id = cell_value(feature_row, feat_req_col)
        screen_id = cell_value(feature_row, feature_screen_col)
        if not any([feature_id, req_id, screen_id]):
            continue

        matched_ui_rows = ui_by_feature.get(feature_id, []) if feature_id else []
        if not matched_ui_rows and screen_id:
            matched_ui_rows = ui_by_screen.get(screen_id, [])

        ui_ids = compact_unique(cell_value(row, ui_screen_col) for row in matched_ui_rows)
        ui_names = compact_unique(cell_value(row, ui_name_col) for row in matched_ui_rows)
        correction_applied = bool(
            (feature_id and feature_id in added_ui_feature_ids)
            or (screen_id and screen_id in added_ui_screen_ids)
        )
        status = "corrected" if correction_applied else ("linked" if matched_ui_rows else "missing_ui")
        feature_links.append({
            "requirement_id": req_id,
            "feature_id": feature_id,
            "feature_name": cell_value(feature_row, feature_name_col),
            "screen_id": screen_id,
            "status": status,
            "status_label": "보완됨" if status == "corrected" else ("연결됨" if status == "linked" else "UI 누락"),
            "correction_applied": correction_applied,
            "ui_match_count": len(matched_ui_rows),
            "ui_screen_ids": ui_ids,
            "ui_names": ui_names,
            "action": "UI 후보 추가됨, 담당자 검토 필요" if correction_applied else ("UI 설계 연결 확인" if status == "linked" else "UI 설계서에 화면/기능 매핑 후보를 추가/검토"),
        })

    req_ids = set(non_empty_values(requirement_rows, req_id_col))
    feature_req_ids = set(non_empty_values(feature_rows, feat_req_col))
    feature_ids = set(non_empty_values(feature_rows, feature_id_col))
    feature_screen_ids = set(non_empty_values(feature_rows, feature_screen_col))
    ui_req_ids = set(non_empty_values(ui_rows, ui_req_col))
    ui_feature_ids = set(non_empty_values(ui_rows, ui_feature_id_col))
    ui_screen_ids = set(non_empty_values(ui_rows, ui_screen_col))

    return {
        "run_id": run_id,
        "scenario_key": "traceability",
        "artifact_type": "traceability_connection_map",
        "summary": build_traceability_summary(requirement_links, feature_links, requirement_rows, feature_rows, ui_rows),
        "requirement_to_feature": requirement_links,
        "feature_to_ui": feature_links,
        "orphan_references": {
            "feature_requirement_ids_not_in_requirements": missing_values(feature_req_ids, req_ids),
            "ui_requirement_ids_not_in_requirements": missing_values(ui_req_ids, req_ids),
            "ui_feature_ids_not_in_features": missing_values(ui_feature_ids, feature_ids),
            "ui_screen_ids_not_in_features": missing_values(ui_screen_ids, feature_screen_ids),
        },
        "traceability_changes": traceability_changes,
        "remaining_warnings": warnings_by_document,
    }


def build_traceability_summary(
    requirement_links: List[Dict[str, Any]],
    feature_links: List[Dict[str, Any]],
    requirement_rows: List[Dict[str, Any]],
    feature_rows: List[Dict[str, Any]],
    ui_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize link coverage rates for the traceability UI."""
    requirement_total = len(requirement_links)
    feature_total = len(feature_links)
    linked_requirements = sum(1 for item in requirement_links if item.get("status") in {"linked", "corrected"})
    linked_features = sum(1 for item in feature_links if item.get("status") in {"linked", "corrected"})

    return {
        "requirement_row_count": len(requirement_rows),
        "feature_row_count": len(feature_rows),
        "ui_row_count": len(ui_rows),
        "requirement_count": requirement_total,
        "feature_count": feature_total,
        "linked_requirement_count": linked_requirements,
        "missing_requirement_to_feature_count": max(requirement_total - linked_requirements, 0),
        "requirement_to_feature_coverage_rate": percent_rate(linked_requirements, requirement_total),
        "linked_feature_count": linked_features,
        "missing_feature_to_ui_count": max(feature_total - linked_features, 0),
        "feature_to_ui_coverage_rate": percent_rate(linked_features, feature_total),
    }


def collect_traceability_changes(changes_by_document: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Keep only traceability-created link candidate rows from correction metadata."""
    traceability_reasons = {"append_feature_candidate", "append_ui_candidate"}
    changes: List[Dict[str, Any]] = []
    for document_key, document_changes in changes_by_document.items():
        for change in document_changes:
            if not isinstance(change, dict) or change.get("reason") not in traceability_reasons:
                continue
            changes.append({
                "document_key": document_key,
                "document_label": change.get("document_label") or DOCUMENT_LABELS.get(document_key, document_key),
                "sheet_name": change.get("sheet_name", ""),
                "row_index": change.get("row_index"),
                "change_type": "기능 후보 추가" if change.get("reason") == "append_feature_candidate" else "UI 후보 추가",
                "after": change.get("after"),
                "reason": change.get("reason"),
            })
    return changes


def change_after_value(change: Dict[str, Any], keywords: List[str]) -> str:
    """Find a value in a traceability change's inserted row."""
    after = change.get("after", {})
    if not isinstance(after, dict):
        return ""
    column = find_column([after], keywords)
    return cell_value(after, column)


def compact_unique(values: Any) -> List[str]:
    """Return distinct non-empty string values in input order."""
    seen: set[str] = set()
    compacted: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        compacted.append(text)
    return compacted


def percent_rate(numerator: int, denominator: int) -> float:
    """Return a one-decimal percentage rate without raising on zero."""
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def apply_ui_match_document_corrections(
    outputs: Dict[str, Dict[str, Any]],
    changes_by_document: Dict[str, List[Dict[str, Any]]],
    warnings_by_document: Dict[str, List[str]],
) -> None:
    """기능-UI 의미 일치성 보완을 위해 UI 행위/입출력 항목을 보강합니다."""
    feature_rows = output_rows(outputs["feature_definition"])
    ui_rows = output_rows(outputs["ui_design"])
    feature_id_col = find_column(feature_rows, ["기능id"])
    screen_col = find_column(feature_rows, ["화면id"])
    ui_feature_id_col = find_column(ui_rows, ["기능id"])
    ui_screen_col = find_column(ui_rows, ["화면id"])
    ui_action_col = find_column(ui_rows, ["사용자행위", "버튼"])
    ui_input_col = find_column(ui_rows, ["주요 입력", "입력"])
    ui_output_col = find_column(ui_rows, ["주요 출력", "출력"])
    feature_input_col = find_column(feature_rows, ["입력"])
    feature_output_col = find_column(feature_rows, ["출력"])
    feature_desc_cols = [
        column for column in [
            find_column(feature_rows, ["기능명"]),
            find_column(feature_rows, ["설명"]),
            find_column(feature_rows, ["기능"]),
        ] if column
    ]
    ui_by_feature_id = group_rows_by_value(ui_rows, ui_feature_id_col)
    ui_by_screen_id = group_rows_by_value(ui_rows, ui_screen_col)

    for feature_row in feature_rows:
        feature_id = cell_value(feature_row, feature_id_col)
        screen_id = cell_value(feature_row, screen_col)
        matched_ui_rows = ui_by_feature_id.get(feature_id, []) if feature_id else []
        if not matched_ui_rows and screen_id:
            matched_ui_rows = ui_by_screen_id.get(screen_id, [])
        if not matched_ui_rows:
            warnings_by_document["ui_design"].append(
                f"기능ID {feature_id or '(미기재)'} / 화면ID {screen_id or '(미기재)'}에 매칭되는 UI 행이 없어 자동 보강이 제한되었습니다."
            )
            continue

        target_row = matched_ui_rows[0]
        target_index = ui_rows.index(target_row) + 4
        feature_text = row_text(feature_row, feature_desc_cols)
        missing_actions = sorted(detect_action_terms(feature_text) - detect_action_terms(cell_value(target_row, ui_action_col)))
        append_terms_to_cell(
            target_row,
            ui_action_col,
            missing_actions,
            "사용자행위/버튼",
            "ui_match_append_missing_actions",
            "ui_design",
            target_index,
            changes_by_document["ui_design"],
        )
        append_terms_to_cell(
            target_row,
            ui_input_col,
            missing_field_terms(cell_value(feature_row, feature_input_col), cell_value(target_row, ui_input_col)),
            "주요 입력",
            "ui_match_append_missing_inputs",
            "ui_design",
            target_index,
            changes_by_document["ui_design"],
        )
        append_terms_to_cell(
            target_row,
            ui_output_col,
            missing_field_terms(cell_value(feature_row, feature_output_col), cell_value(target_row, ui_output_col)),
            "주요 출력",
            "ui_match_append_missing_outputs",
            "ui_design",
            target_index,
            changes_by_document["ui_design"],
        )


def apply_coverage_document_corrections(
    outputs: Dict[str, Dict[str, Any]],
    changes_by_document: Dict[str, List[Dict[str, Any]]],
    warnings_by_document: Dict[str, List[str]],
) -> None:
    """요구사항 커버리지 보완을 위해 누락된 기능/UI 후보 행을 생성합니다."""
    requirement_rows = output_rows(outputs["requirement_definition"])
    feature_rows = output_rows(outputs["feature_definition"])
    ui_rows = output_rows(outputs["ui_design"])
    req_col = find_column(requirement_rows, ["요구사항 id"])
    feat_req_col = find_column(feature_rows, ["요구사항 id"])
    ui_req_col = find_column(ui_rows, ["요구사항 id"])

    req_ids = set(non_empty_values(requirement_rows, req_col))
    feature_req_ids = set(non_empty_values(feature_rows, feat_req_col))
    ui_req_ids = set(non_empty_values(ui_rows, ui_req_col))

    for req_id in missing_values(req_ids, feature_req_ids):
        requirement_row = first_row_by_value(requirement_rows, req_col, req_id)
        added = append_feature_candidate(outputs["feature_definition"], requirement_row, req_id, "coverage-agent 기능 커버리지 보완 후보")
        if added:
            changes_by_document["feature_definition"].append(added)

    for req_id in missing_values(req_ids, ui_req_ids):
        requirement_row = first_row_by_value(requirement_rows, req_col, req_id)
        screen_id = suggested_ui_id_from_req(req_id)
        added = append_ui_candidate(outputs["ui_design"], requirement_row, screen_id, "coverage-agent UI 커버리지 보완 후보")
        if added:
            changes_by_document["ui_design"].append(added)

    extra_feature_req_ids = missing_values(feature_req_ids, req_ids)
    if extra_feature_req_ids:
        feature_note_col = ensure_column(outputs["feature_definition"], "기타")
        for row in feature_rows:
            req_id = cell_value(row, feat_req_col)
            if req_id in extra_feature_req_ids:
                append_terms_to_cell(
                    row,
                    feature_note_col,
                    ["요구사항 근거 확인 필요"],
                    "기타",
                    "coverage_mark_extra_feature_scope",
                    "feature_definition",
                    feature_rows.index(row) + 4,
                    changes_by_document["feature_definition"],
                )
    if not req_col:
        warnings_by_document["requirement_definition"].append("요구사항 ID 컬럼을 찾지 못해 coverage 보완 후보 생성이 제한되었습니다.")


def output_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """보완본 payload의 모든 행을 반환합니다."""
    rows: List[Dict[str, Any]] = []
    for sheet in payload.get("sheets", []):
        if isinstance(sheet, dict):
            data = sheet.get("data", [])
            if isinstance(data, list):
                rows.extend(row for row in data if isinstance(row, dict))
    return rows


def find_column_name(columns: List[str], keywords: List[str]) -> Optional[str]:
    """컬럼명 목록에서 키워드에 맞는 컬럼을 찾습니다."""
    for column in columns:
        normalized_column = normalize(column)
        for keyword in keywords:
            if normalize(keyword) in normalized_column:
                return column
    return None


def normalize_id_cell(
    row: Dict[str, Any],
    column_name: Optional[str],
    suggest_func,
    document_key: str,
    sheet: Dict[str, Any],
    row_index: int,
    changes: List[Dict[str, Any]],
) -> None:
    """ID 셀을 명확히 보정 가능한 표준 형식으로 수정합니다."""
    if not column_name:
        return
    current_value = str(row.get(column_name, "")).strip()
    suggestion = suggest_func(current_value) if current_value else None
    if suggestion and suggestion != current_value:
        update_cell_if_changed(
            row,
            column_name,
            suggestion,
            document_key,
            sheet.get("sheet_name", ""),
            row_index,
            changes,
            "normalize_identifier_format",
        )


def update_cell_if_changed(
    row: Dict[str, Any],
    column_name: str,
    new_value: str,
    document_key: str,
    sheet_name: str,
    row_index: int,
    changes: List[Dict[str, Any]],
    reason: str,
) -> None:
    """셀 값 변경 내역을 기록하며 값을 갱신합니다."""
    old_value = row.get(column_name, "")
    if old_value == new_value:
        return
    row[column_name] = new_value
    changes.append({
        "document_key": document_key,
        "document_label": DOCUMENT_LABELS.get(document_key, document_key),
        "sheet_name": sheet_name,
        "row_index": row_index,
        "column": column_name,
        "before": old_value,
        "after": new_value,
        "reason": reason,
    })


def append_terms_to_cell(
    row: Dict[str, Any],
    column_name: Optional[str],
    terms: List[str],
    fallback_column_name: str,
    reason: str,
    document_key: str,
    row_index: int,
    changes: List[Dict[str, Any]],
) -> None:
    """셀에 누락된 용어를 중복 없이 추가합니다."""
    if not terms:
        return
    target_column = column_name or fallback_column_name
    current = str(row.get(target_column, "")).strip()
    additions = [term for term in terms if term and term not in current]
    if not additions:
        return
    joined = ", ".join(additions)
    new_value = f"{current}, {joined}" if current else joined
    update_cell_if_changed(row, target_column, new_value, document_key, "", row_index, changes, reason)


def first_row_by_value(rows: List[Dict[str, Any]], column_name: Optional[str], value: str) -> Dict[str, Any]:
    """특정 컬럼 값이 일치하는 첫 행을 반환합니다."""
    if not column_name:
        return {}
    for row in rows:
        if str(row.get(column_name, "")).strip() == value:
            return row
    return {}


def append_feature_candidate(payload: Dict[str, Any], source_row: Dict[str, Any], req_id: str, note: str) -> Optional[Dict[str, Any]]:
    """기능정의서 보완 후보 행을 추가합니다."""
    sheet = first_payload_sheet(payload)
    if sheet is None:
        return None
    columns = ensure_columns(sheet, ["시스템", "요구사항 ID", "기능ID", "기능명", "상태", "설명", "기능", "입력", "출력", "화면ID", "우선순위", "기타"])
    new_row = {column: "" for column in columns}
    req_num = req_number(req_id)
    system_col = find_column_name(columns, ["시스템"]) or "시스템"
    req_col = find_column_name(columns, ["요구사항 id"]) or "요구사항 ID"
    func_col = find_column_name(columns, ["기능id"]) or "기능ID"
    name_col = find_column_name(columns, ["기능명"]) or "기능명"
    status_col = find_column_name(columns, ["상태"]) or "상태"
    desc_col = find_column_name(columns, ["설명"]) or "설명"
    body_col = find_column_name(columns, ["기능"]) or "기능"
    input_col = find_column_name(columns, ["입력"]) or "입력"
    output_col = find_column_name(columns, ["출력"]) or "출력"
    ui_col = find_column_name(columns, ["화면id"]) or "화면ID"
    priority_col = find_column_name(columns, ["우선순위"]) or "우선순위"
    note_col = find_column_name(columns, ["기타"]) or "기타"
    req_name_col = find_column([source_row], ["요구사항명"])

    new_row[system_col] = cell_value(source_row, find_column([source_row], ["시스템"])) or "MES"
    new_row[req_col] = req_id
    new_row[func_col] = f"{req_id}-F01" if req_id else "자가점검필요-F01"
    new_row[name_col] = cell_value(source_row, req_name_col) or f"{req_id} 기능 보완"
    new_row[status_col] = "신규"
    new_row[desc_col] = row_text(source_row, list(source_row.keys())) or "자가점검 필요"
    new_row[body_col] = row_text(source_row, list(source_row.keys())) or "자가점검 필요"
    new_row[input_col] = "자가점검 필요"
    new_row[output_col] = "자가점검 필요"
    new_row[ui_col] = suggested_ui_id_from_req(req_id) if req_num is not None else "UI-자가점검"
    new_row[priority_col] = "3"
    new_row[note_col] = note
    sheet.setdefault("data", []).append(new_row)
    sheet["row_count"] = len(sheet.get("data", []))
    return {
        "document_key": "feature_definition",
        "document_label": DOCUMENT_LABELS["feature_definition"],
        "sheet_name": sheet.get("sheet_name", ""),
        "row_index": sheet["row_count"] + 3,
        "column": "*",
        "before": None,
        "after": new_row,
        "reason": "append_feature_candidate",
    }


def append_ui_candidate(payload: Dict[str, Any], source_row: Dict[str, Any], screen_id: str, note: str) -> Optional[Dict[str, Any]]:
    """UI설계서 보완 후보 행을 추가합니다."""
    sheet = first_payload_sheet(payload)
    if sheet is None:
        return None
    columns = ensure_columns(sheet, ["시스템", "업무그룹", "요구사항 ID", "기능ID", "화면ID", "화면명", "화면유형", "상태", "사용자행위/버튼", "권한", "주요 입력", "주요 출력", "기타"])
    new_row = {column: "" for column in columns}
    req_id = cell_value(source_row, find_column([source_row], ["요구사항 id"]))
    func_id = cell_value(source_row, find_column([source_row], ["기능id"])) or (f"{req_id}-F01" if req_id else "")
    name = cell_value(source_row, find_column([source_row], ["기능명", "요구사항명"])) or f"{screen_id} 화면"

    set_if_column(new_row, columns, ["시스템"], cell_value(source_row, find_column([source_row], ["시스템"])) or "MES")
    set_if_column(new_row, columns, ["업무그룹"], cell_value(source_row, find_column([source_row], ["업무그룹"])))
    set_if_column(new_row, columns, ["요구사항 id"], req_id)
    set_if_column(new_row, columns, ["기능id"], func_id)
    set_if_column(new_row, columns, ["화면id"], screen_id)
    set_if_column(new_row, columns, ["화면명"], name)
    set_if_column(new_row, columns, ["화면유형"], "화면")
    set_if_column(new_row, columns, ["상태"], "신규")
    set_if_column(new_row, columns, ["사용자행위", "버튼"], ", ".join(sorted(detect_action_terms(row_text(source_row, list(source_row.keys()))))) or "조회")
    set_if_column(new_row, columns, ["권한"], "일반사용자")
    set_if_column(new_row, columns, ["주요 입력", "입력"], cell_value(source_row, find_column([source_row], ["입력"])) or "자가점검 필요")
    set_if_column(new_row, columns, ["주요 출력", "출력"], cell_value(source_row, find_column([source_row], ["출력"])) or "자가점검 필요")
    set_if_column(new_row, columns, ["기타"], note)
    sheet.setdefault("data", []).append(new_row)
    sheet["row_count"] = len(sheet.get("data", []))
    return {
        "document_key": "ui_design",
        "document_label": DOCUMENT_LABELS["ui_design"],
        "sheet_name": sheet.get("sheet_name", ""),
        "row_index": sheet["row_count"] + 3,
        "column": "*",
        "before": None,
        "after": new_row,
        "reason": "append_ui_candidate",
    }


def first_payload_sheet(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """payload의 첫 번째 시트를 반환하고 없으면 기본 시트를 생성합니다."""
    sheets = payload.setdefault("sheets", [])
    if not isinstance(sheets, list):
        payload["sheets"] = []
        sheets = payload["sheets"]
    if not sheets:
        sheets.append({"sheet_name": "보완본", "file_name": "보완본", "columns": [], "data": [], "row_count": 0})
    return sheets[0] if isinstance(sheets[0], dict) else None


def ensure_columns(sheet: Dict[str, Any], required_columns: List[str]) -> List[str]:
    """시트에 필요한 컬럼을 추가하고 컬럼 목록을 반환합니다."""
    columns = sheet.setdefault("columns", [])
    if not isinstance(columns, list):
        columns = []
        sheet["columns"] = columns
    for column in required_columns:
        if not find_column_name(columns, [column]):
            columns.append(column)
    return columns


def ensure_column(payload: Dict[str, Any], column_name: str) -> str:
    """첫 시트에 컬럼을 보장하고 실제 컬럼명을 반환합니다."""
    sheet = first_payload_sheet(payload)
    if sheet is None:
        return column_name
    columns = ensure_columns(sheet, [column_name])
    return find_column_name(columns, [column_name]) or column_name


def set_if_column(row: Dict[str, Any], columns: List[str], keywords: List[str], value: str) -> None:
    """키워드에 맞는 컬럼에 값을 설정합니다."""
    column = find_column_name(columns, keywords)
    if column:
        row[column] = value


def req_number(req_id: str) -> Optional[int]:
    """REQ-###에서 숫자 부분을 반환합니다."""
    match = re.search(r"(\d{1,3})", str(req_id))
    return int(match.group(1)) if match else None


def suggested_ui_id_from_req(req_id: str) -> str:
    """요구사항 ID 기반 화면ID 후보를 생성합니다."""
    number = req_number(req_id)
    return f"UI-{number:03d}" if number is not None else "UI-자가점검"


def corrected_output_prefix(scenario_key: str, agent_name: str) -> str:
    """문서별 보완본 파일 prefix를 반환합니다."""
    scenario = canonical_scenario_key(scenario_key) or canonical_scenario_key(agent_name)
    prefixes = {
        "basic_quality": "basic_quality_agent",
        "traceability": "traceability_agent",
        "ui_match": "ui_match_agent",
        "coverage": "coverage_agent",
    }
    return prefixes.get(scenario, sanitize_name(agent_name).replace("-", "_"))


def corrected_document_output_path(
    run_id: str,
    scenario_key: str,
    output_prefix: str,
    document_key: str,
) -> Path:
    """문서별 보완본 JSON 저장 경로를 반환합니다."""
    scenario = canonical_scenario_key(scenario_key)
    return DATA_ROOT / run_id / scenario / f"{output_prefix}_output_{document_key}.json"


def traceability_connection_report_path(run_id: str) -> Path:
    """Return the saved traceability connection map artifact path."""
    return DATA_ROOT / run_id / "traceability" / "traceability_agent_connection_map.json"


def get_corrected_document_outputs(run_id: str, scenario_key: str) -> Dict[str, Any]:
    """저장된 원 SubAgent 결과와 문서별 보완본 요약을 읽습니다."""
    scenario = canonical_scenario_key(scenario_key)
    prefix = corrected_output_prefix(scenario, f"{scenario}-agent")
    subagent_result = load_subagent_result(run_id, scenario)

    if scenario == "traceability":
        file_path = traceability_connection_report_path(run_id)
        connection_report = load_json_dict(file_path) if file_path.exists() else {}
        return {
            "run_id": run_id,
            "scenario_key": scenario,
            "target_agent_name": prefix,
            "subagent_result": summarize_subagent_result(subagent_result),
            "connection_report_path": str(file_path),
            "connection_report": connection_report,
            "documents": {},
            "missing_documents": [],
        }

    documents: Dict[str, Dict[str, Any]] = {}
    missing_documents: List[str] = []

    for document_key in DOCUMENT_LABELS:
        file_path = corrected_document_output_path(run_id, scenario, prefix, document_key)
        if not file_path.exists():
            documents[document_key] = {
                "document_key": document_key,
                "document_label": DOCUMENT_LABELS[document_key],
                "artifact_path": str(file_path),
                "status": "missing",
            }
            missing_documents.append(document_key)
            continue
        payload = load_json_dict(file_path)
        documents[document_key] = summarize_corrected_document_payload(document_key, payload, file_path)

    return {
        "run_id": run_id,
        "scenario_key": scenario,
        "target_agent_name": corrected_output_prefix(scenario, f"{scenario}-agent"),
        "subagent_result": summarize_subagent_result(subagent_result),
        "documents": documents,
        "missing_documents": missing_documents,
    }


def load_corrected_document_payloads(run_id: str, scenario_key: str) -> Dict[str, Dict[str, Any]]:
    """자가 점검 내부 실행용으로 보완본 전체 payload를 읽습니다."""
    scenario = canonical_scenario_key(scenario_key)
    prefix = corrected_output_prefix(scenario, f"{scenario}-agent")
    documents: Dict[str, Dict[str, Any]] = {}
    for document_key in DOCUMENT_LABELS:
        file_path = corrected_document_output_path(run_id, scenario, prefix, document_key)
        if not file_path.exists():
            documents[document_key] = {
                "document_key": document_key,
                "document_label": DOCUMENT_LABELS[document_key],
                "artifact_path": str(file_path),
                "status": "missing",
            }
            continue
        payload = load_json_dict(file_path)
        payload.setdefault("document_key", document_key)
        payload.setdefault("document_label", DOCUMENT_LABELS[document_key])
        payload.setdefault("artifact_path", str(file_path))
        documents[document_key] = payload
    return documents


def summarize_corrected_document_payload(document_key: str, payload: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
    """LLM 도구 반환을 작게 유지하기 위한 보완본 요약을 만듭니다."""
    if payload.get("load_error"):
        return {
            "document_key": document_key,
            "document_label": DOCUMENT_LABELS.get(document_key, document_key),
            "artifact_path": str(file_path),
            "parser_status": "load_error",
            "status": "load_error",
            "load_error": payload.get("load_error"),
            "sheet_count": 0,
            "row_count": 0,
            "change_count": 0,
            "applied_change_samples": [],
            "remaining_warning_samples": [],
        }

    metadata = payload.get("correction_metadata", {}) if isinstance(payload, dict) else {}
    applied_changes = metadata.get("applied_changes", []) if isinstance(metadata, dict) else []
    remaining_warnings = metadata.get("remaining_warnings", []) if isinstance(metadata, dict) else []
    sheets = payload.get("sheets", []) if isinstance(payload, dict) else []
    row_count = 0
    if isinstance(sheets, list):
        row_count = sum(
            len(sheet.get("data") or [])
            for sheet in sheets
            if isinstance(sheet, dict) and isinstance(sheet.get("data"), list)
        )
    return {
        "document_key": document_key,
        "document_label": DOCUMENT_LABELS.get(document_key, document_key),
        "artifact_path": str(file_path),
        "parser_status": payload.get("parser_status") if isinstance(payload, dict) else "invalid",
        "sheet_count": payload.get("sheet_count", len(sheets) if isinstance(sheets, list) else 0) if isinstance(payload, dict) else 0,
        "row_count": row_count,
        "change_count": len(applied_changes) if isinstance(applied_changes, list) else 0,
        "applied_change_samples": limit_items(applied_changes if isinstance(applied_changes, list) else [], 3),
        "remaining_warning_samples": limit_items(remaining_warnings if isinstance(remaining_warnings, list) else [], 3),
    }


def summarize_subagent_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """원 SubAgent 결과도 요약해서 LLM으로 넘깁니다."""
    if not isinstance(payload, dict):
        return {}
    if payload.get("load_error"):
        return {"load_error": payload.get("load_error")}
    return {
        "scenario_key": canonical_scenario_key(payload.get("scenario_key") or payload.get("agent_name")),
        "agent_name": payload.get("agent_name", ""),
        "summary": payload.get("summary", ""),
        "score": payload.get("score"),
        "findings_count": len(payload.get("findings") or []),
        "warnings_count": len(payload.get("warnings") or []),
        "recommendations_count": len(payload.get("recommendations") or []),
        "finding_samples": limit_items(payload.get("findings") or [], 5),
        "warning_samples": limit_items(payload.get("warnings") or [], 5),
        "corrected_document_paths": limit_items(payload.get("corrected_document_paths") or [], 3),
    }


def compact_subagent_output_for_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return only bounded fields needed by report-agent."""
    if not isinstance(payload, dict):
        return {}
    if payload.get("load_error"):
        return {
            "agent_name": payload.get("agent_name", ""),
            "artifact_path": payload.get("artifact_path", ""),
            "load_error": payload.get("load_error"),
        }
    return {
        "scenario_key": canonical_scenario_key(payload.get("scenario_key") or payload.get("agent_name")),
        "agent_name": payload.get("agent_name", ""),
        "artifact_path": payload.get("artifact_path", ""),
        "summary": payload.get("summary", ""),
        "score": payload.get("score"),
        "findings": limit_items(payload.get("findings") or [], 8),
        "warnings": limit_items(payload.get("warnings") or [], 8),
        "recommendations": limit_items(payload.get("recommendations") or [], 8),
        "findings_count": len(payload.get("findings") or []),
        "warnings_count": len(payload.get("warnings") or []),
        "recommendations_count": len(payload.get("recommendations") or []),
    }


def build_final_review_report_payload(run_id: str, scenario_order: List[str]) -> Dict[str, Any]:
    """저장된 서브에이전트 결과를 최종 보고서 JSON 형태로 조립합니다."""
    normalized_order = [canonical_scenario_key(key) for key in scenario_order] or [
        "basic_quality",
        "traceability",
        "ui_match",
        "coverage",
    ]
    scenario_results: List[Dict[str, Any]] = []

    for scenario_key in normalized_order:
        payload = load_subagent_result(run_id, scenario_key)
        if payload:
            scenario_results.append(build_final_scenario_result(scenario_key, payload))
        else:
            scenario_results.append(build_missing_scenario_result(scenario_key))

    scores = [
        result["score"]
        for result in scenario_results
        if isinstance(result.get("score"), int)
    ]
    overall_score = round(sum(scores) / len(scores)) if scores else 0
    blocked_scenarios = [
        result["scenario_key"]
        for result in scenario_results
        if result.get("status") == "보완 필요"
    ]

    return {
        "run_id": run_id,
        "summary": build_final_report_summary(scenario_results, overall_score),
        "overall_score": overall_score,
        "blocked_scenarios": blocked_scenarios,
        "scenario_order": normalized_order,
        "scenario_results": scenario_results,
        "verdict_cards": build_final_verdict_cards(scenario_results, overall_score, blocked_scenarios),
        "top_risks": build_final_top_risks(scenario_results),
        "traceability_overview": build_final_traceability_overview(run_id),
        "document_fix_points": build_final_document_fix_points(scenario_results),
        "business_impact_features": build_final_business_impact_features(scenario_results),
        "priority_actions": build_final_priority_actions(scenario_results),
    }


def build_final_scenario_result(scenario_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """서브에이전트 저장 결과를 최종 보고서의 시나리오 항목으로 변환합니다."""
    score = payload.get("score")
    score = score if isinstance(score, int) else 0
    findings = limit_items(payload.get("findings") or [], 9)
    warnings = limit_items(payload.get("warnings") or [], 9)
    recommendations = limit_items(payload.get("recommendations") or [], 9)
    status = payload.get("status") or infer_final_status(score, findings)
    return {
        "scenario_key": canonical_scenario_key(scenario_key),
        "scenario_label": final_scenario_label(scenario_key),
        "status": status,
        "score": score,
        "summary": payload.get("summary") or f"{final_scenario_label(scenario_key)} 결과입니다.",
        "findings": findings,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def build_missing_scenario_result(scenario_key: str) -> Dict[str, Any]:
    """실행 대상이지만 저장 결과가 없는 시나리오를 최종 보고서에 표시합니다."""
    return {
        "scenario_key": canonical_scenario_key(scenario_key),
        "scenario_label": final_scenario_label(scenario_key),
        "status": "보완 필요",
        "score": 0,
        "summary": "저장된 서브에이전트 결과가 없어 최종 보고서에서 누락 위험으로 표시했습니다.",
        "findings": ["서브에이전트 결과 JSON이 생성되지 않았습니다."],
        "warnings": [],
        "recommendations": ["해당 시나리오 점검을 다시 실행하고 결과 JSON 저장 여부를 확인하세요."],
    }


def infer_final_status(score: int, findings: List[Any]) -> str:
    """최종 보고서용 상태를 점수와 findings 기준으로 산정합니다."""
    if score >= 85 and not findings:
        return "통과"
    if score >= 70 and not findings:
        return "검토 권장"
    return "보완 필요"


def final_scenario_label(scenario_key: str) -> str:
    """최종 보고서 표시용 시나리오 라벨을 반환합니다."""
    labels = {
        "basic_quality": "기초 품질 점검",
        "traceability": "요구사항-기능-UI 구조 정합성",
        "ui_match": "기능-UI 내용 일치성",
        "coverage": "요구사항 기반 기능 완전성",
    }
    return labels.get(canonical_scenario_key(scenario_key), str(scenario_key))


def build_final_report_summary(scenario_results: List[Dict[str, Any]], overall_score: int) -> str:
    """최종 보고서 요약을 생성합니다."""
    blocked = [
        str(result.get("scenario_label") or result.get("scenario_key"))
        for result in scenario_results
        if result.get("status") == "보완 필요"
    ]
    if blocked:
        return (
            "저장된 서브에이전트 결과를 기준으로 최종 품질 점검을 종합했습니다. "
            f"전체 점수는 {overall_score}점이며, 보완 필요 시나리오는 {', '.join(blocked)}입니다."
        )
    return (
        "저장된 서브에이전트 결과를 기준으로 최종 품질 점검을 종합했습니다. "
        f"전체 점수는 {overall_score}점이며, 모든 시나리오가 통과 또는 검토 권장 수준입니다."
    )


def build_final_verdict_cards(
    scenario_results: List[Dict[str, Any]],
    overall_score: int,
    blocked_scenarios: List[str],
) -> List[Dict[str, str]]:
    """Build top-level verdict cards for the summary tab."""
    if overall_score >= 85:
        verdict = "양호"
        detail = "전체 품질이 기준 이상입니다."
    elif overall_score >= 70:
        verdict = "검토 필요"
        detail = "일부 시나리오에서 보완 검토가 필요합니다."
    else:
        verdict = "보완 필요"
        detail = "핵심 산출물 간 품질 문제가 누적되어 있습니다."

    lowest = min(
        scenario_results,
        key=lambda result: result.get("score", 101) if isinstance(result.get("score"), int) else 101,
        default={},
    )
    return [
        {"label": "전체 판정", "value": verdict, "detail": detail},
        {"label": "전체 점수", "value": f"{overall_score}점", "detail": "100점 만점 기준"},
        {"label": "보완 필요", "value": f"{len(blocked_scenarios)}개", "detail": "기준 미달 시나리오 수"},
        {
            "label": "최저 점수",
            "value": f"{lowest.get('score', 0)}점",
            "detail": str(lowest.get("scenario_label") or "점검 결과 없음"),
        },
    ]


def build_final_top_risks(scenario_results: List[Dict[str, Any]]) -> List[str]:
    """Build the top 3 concrete risks across subagents."""
    candidates: List[Dict[str, Any]] = []
    for result in scenario_results:
        scenario_key = str(result.get("scenario_key") or "")
        scenario_label = str(result.get("scenario_label") or final_scenario_label(scenario_key))
        score = result.get("score", 0)
        score = score if isinstance(score, int) else 0
        for index, finding in enumerate(result.get("findings") or []):
            add_summary_item_candidate(candidates, scenario_key, scenario_label, score, "오류", finding, index)
        for index, warning in enumerate(result.get("warnings") or []):
            add_summary_item_candidate(candidates, scenario_key, scenario_label, score, "경고", warning, index)

    return select_ranked_summary_items(candidates, 3)


def build_final_traceability_overview(run_id: str) -> Dict[str, Any]:
    """Build traceability summary values from the connection report."""
    file_path = traceability_connection_report_path(run_id)
    payload = load_json_dict(file_path) if file_path.exists() else {}
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    orphan_references = payload.get("orphan_references", {}) if isinstance(payload, dict) else {}
    orphan_count = 0
    if isinstance(orphan_references, dict):
        orphan_count = sum(len(value) for value in orphan_references.values() if isinstance(value, list))

    return {
        "requirement_to_feature_coverage_rate": summary.get("requirement_to_feature_coverage_rate", 0) if isinstance(summary, dict) else 0,
        "feature_to_ui_coverage_rate": summary.get("feature_to_ui_coverage_rate", 0) if isinstance(summary, dict) else 0,
        "missing_requirement_to_feature_count": summary.get("missing_requirement_to_feature_count", 0) if isinstance(summary, dict) else 0,
        "missing_feature_to_ui_count": summary.get("missing_feature_to_ui_count", 0) if isinstance(summary, dict) else 0,
        "traceability_changes_count": len(payload.get("traceability_changes", [])) if isinstance(payload, dict) else 0,
        "orphan_reference_count": orphan_count,
        "artifact_path": str(file_path),
    }


def build_final_document_fix_points(scenario_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group concrete findings by artifact document."""
    document_labels = ["요구사항 정의서", "기능 정의서", "UI 설계서"]
    grouped: Dict[str, List[str]] = {label: [] for label in document_labels}
    for result in scenario_results:
        scenario_label = str(result.get("scenario_label") or final_scenario_label(result.get("scenario_key", "")))
        for item in [*(result.get("findings") or []), *(result.get("warnings") or [])]:
            text = str(item).strip()
            if should_skip_priority_action(text):
                continue
            for document_label in document_labels:
                if document_label in text and len(grouped[document_label]) < 3:
                    grouped[document_label].append(f"[{scenario_label}] {text}")

    return [
        {"document_label": document_label, "points": points}
        for document_label, points in grouped.items()
        if points
    ]


def build_final_business_impact_features(scenario_results: List[Dict[str, Any]]) -> List[str]:
    """Extract feature or requirement issues likely to affect user-facing behavior."""
    impact_keywords = [
        "기능-UI 행위 불일치",
        "기능 범위 밖 UI 행위",
        "기능 정의 보완 필요",
        "UI 설계 보완 필요",
        "요구사항 대비 기능 정의가 누락",
        "요구사항 대비 UI 설계가 누락",
    ]
    candidates: List[Dict[str, Any]] = []
    for result in scenario_results:
        scenario_key = str(result.get("scenario_key") or "")
        scenario_label = str(result.get("scenario_label") or final_scenario_label(scenario_key))
        score = result.get("score", 0)
        score = score if isinstance(score, int) else 0
        for index, item in enumerate([*(result.get("findings") or []), *(result.get("warnings") or [])]):
            text = str(item).strip()
            if not any(keyword in text for keyword in impact_keywords):
                continue
            add_summary_item_candidate(candidates, scenario_key, scenario_label, score, "영향", text, index)

    return select_ranked_summary_items(candidates, 5)


def add_summary_item_candidate(
    candidates: List[Dict[str, Any]],
    scenario_key: str,
    scenario_label: str,
    score: int,
    item_type: str,
    raw_text: Any,
    item_index: int,
) -> None:
    """Add one summary-section item candidate."""
    text = str(raw_text).strip()
    if should_skip_priority_action(text):
        return
    type_rank = {"오류": 0, "경고": 1, "영향": 2, "개선": 3}.get(item_type, 4)
    candidates.append({
        "text": f"[{scenario_label} {item_type}] {text}",
        "rank": (
            priority_specificity_rank(text),
            type_rank,
            score,
            {
                "basic_quality": 0,
                "traceability": 1,
                "ui_match": 2,
                "coverage": 3,
            }.get(canonical_scenario_key(scenario_key), 9),
            item_index,
        ),
    })


def select_ranked_summary_items(candidates: List[Dict[str, Any]], limit: int) -> List[str]:
    """Sort and de-duplicate summary candidates."""
    candidates.sort(key=lambda item: item["rank"])
    selected: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate.get("text") or "")
        key = normalize_priority_action_key(text)
        if not text or key in seen:
            continue
        seen.add(key)
        selected.append(text)
        if len(selected) >= limit:
            break
    return selected


def build_final_priority_actions(scenario_results: List[Dict[str, Any]]) -> List[str]:
    """Build concrete top-priority actions from subagent findings, warnings, and recommendations."""
    candidates: List[Dict[str, Any]] = []
    for result in scenario_results:
        scenario_key = str(result.get("scenario_key") or "")
        scenario_label = str(result.get("scenario_label") or final_scenario_label(scenario_key))
        score = result.get("score", 0)
        score = score if isinstance(score, int) else 0

        for index, finding in enumerate(result.get("findings") or []):
            add_priority_candidate(candidates, scenario_key, scenario_label, score, "오류", finding, index)

        for index, warning in enumerate(result.get("warnings") or []):
            add_priority_candidate(candidates, scenario_key, scenario_label, score, "경고", warning, index)

        for index, recommendation in enumerate(result.get("recommendations") or []):
            add_priority_candidate(candidates, scenario_key, scenario_label, score, "개선", recommendation, index)

    candidates.sort(key=lambda item: item["rank"])
    actions: List[str] = []
    seen_keys: set[str] = set()
    for candidate in candidates:
        text = candidate["action"]
        dedupe_key = normalize_priority_action_key(text)
        if not text or dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        actions.append(text)
        if len(actions) >= 5:
            break
    return actions


def add_priority_candidate(
    candidates: List[Dict[str, Any]],
    scenario_key: str,
    scenario_label: str,
    score: int,
    item_type: str,
    raw_text: Any,
    item_index: int,
) -> None:
    """Add one concrete priority-action candidate if the text is useful enough."""
    text = str(raw_text).strip()
    if should_skip_priority_action(text):
        return

    action = format_priority_action(scenario_label, item_type, text)
    type_rank = {"오류": 0, "경고": 1, "개선": 2}.get(item_type, 3)
    scenario_rank = {
        "basic_quality": 0,
        "traceability": 1,
        "ui_match": 2,
        "coverage": 3,
    }.get(canonical_scenario_key(scenario_key), 9)
    candidates.append({
        "action": action,
        "rank": (
            priority_specificity_rank(text),
            type_rank,
            scenario_rank,
            score,
            item_index,
        ),
    })


def should_skip_priority_action(text: str) -> bool:
    """Filter broad or non-actionable priority-action candidates."""
    if not text:
        return True
    normalized = normalize(text)
    skip_fragments = [
        "개선 필요 사항이 없습니다",
        "정기 점검",
        "재검사",
        "재수행",
        "위 항목",
        "수정 후 sc-",
    ]
    return any(fragment in normalized for fragment in skip_fragments)


def priority_specificity_rank(text: str) -> int:
    """Prefer row/ID-specific findings over broad recommendations."""
    if re.search(r"\d+\s*행", text):
        return 0
    if re.search(r"\b(REQ|RQ|UI|U|F)-?[A-Z0-9_]*\d+", text, re.IGNORECASE):
        return 1
    if "예:" in text or "/" in text:
        return 2
    return 3


def format_priority_action(scenario_label: str, item_type: str, text: str) -> str:
    """Format a subagent issue as a concrete priority action."""
    if item_type == "개선":
        return f"[{scenario_label} 개선] {text}"
    return f"[{scenario_label} {item_type}] {text}"


def normalize_priority_action_key(text: str) -> str:
    """Build a stable key for removing duplicated priority actions."""
    normalized = normalize(text)
    normalized = re.sub(r"^\[[^\]]+\]\s*", "", normalized)
    return normalized[:160]


def run_self_quality_review(run_id: str, scenario_key: str, threshold: int = 85) -> Dict[str, Any]:
    """문서별 보완본을 점검해 교정 품질과 보완 권고 필요 여부를 판단합니다."""
    scenario = canonical_scenario_key(scenario_key)
    if scenario == "coverage":
        return {
            "scenario_key": "coverage",
            "target_agent_name": "coverage-agent",
            "summary": "coverage-agent는 산출물 교정이 아니라 누락/추가 권고를 생성하는 역할이므로 자가 교정 점검을 수행하지 않습니다.",
            "score": 100,
            "threshold": threshold,
            "rerun_required": False,
            "findings": [],
            "warnings": [],
            "correction_guidance": [],
            "checked_document_paths": [],
            "document_scores": {},
            "skipped": True,
        }
    if scenario == "traceability":
        subagent_result = load_subagent_result(run_id, scenario)
        file_path = traceability_connection_report_path(run_id)
        connection_report = load_json_dict(file_path) if file_path.exists() else {}
        findings: List[str] = []
        warnings: List[str] = []
        guidance: List[str] = []
        score = 100

        required_keys = {
            "summary",
            "requirement_to_feature",
            "feature_to_ui",
            "orphan_references",
            "traceability_changes",
        }
        missing_keys = sorted(key for key in required_keys if key not in connection_report)
        if not connection_report:
            findings.append("traceability 연결 리포트 JSON이 생성되지 않았습니다.")
            guidance.append("traceability_agent_connection_map.json을 생성하고 요구사항->기능->UI 연결 정보를 저장하세요.")
            score = 0
        elif missing_keys:
            findings.append(f"traceability 연결 리포트에 필수 필드가 없습니다: {', '.join(missing_keys)}")
            guidance.append("연결 리포트에 summary, requirement_to_feature, feature_to_ui, orphan_references, traceability_changes를 포함하세요.")
            score -= 35

        summary = connection_report.get("summary", {}) if isinstance(connection_report, dict) else {}
        if isinstance(summary, dict):
            req_coverage = float(summary.get("requirement_to_feature_coverage_rate") or 0)
            ui_coverage = float(summary.get("feature_to_ui_coverage_rate") or 0)
            if req_coverage < 100:
                warnings.append(f"요구사항->기능 연결률이 {req_coverage}%입니다.")
                guidance.append("기능 정의서에 연결되지 않은 요구사항 ID를 우선 보완하세요.")
                score -= 10
            if ui_coverage < 100:
                warnings.append(f"기능->UI 연결률이 {ui_coverage}%입니다.")
                guidance.append("UI 설계서에 연결되지 않은 기능/화면ID를 검토하세요.")
                score -= 10

        orphan_references = connection_report.get("orphan_references", {}) if isinstance(connection_report, dict) else {}
        orphan_count = 0
        if isinstance(orphan_references, dict):
            orphan_count = sum(len(value) for value in orphan_references.values() if isinstance(value, list))
        if orphan_count:
            warnings.append(f"정의되지 않은 ID 또는 고아 ID 후보가 {orphan_count}건 있습니다.")
            guidance.append("정의되지 않은 ID 참조를 요구사항/기능/UI 원천 문서 기준으로 정리하세요.")
            score -= min(20, orphan_count * 2)

        score = max(0, min(100, score))
        rerun_required = score < threshold
        target_agent_name = scenario_to_agent_name(scenario)
        return {
            "scenario_key": scenario,
            "target_agent_name": target_agent_name,
            "summary": (
                f"{target_agent_name} 연결 리포트를 점검했습니다. "
                f"교정 품질 점수는 {score}점이며 기준 점수 {threshold}점 "
                f"{'미만으로 보완 권고가 필요합니다.' if rerun_required else '이상으로 통과했습니다'}."
            ),
            "score": score,
            "threshold": threshold,
            "rerun_required": rerun_required,
            "findings": limit_items(findings, 8),
            "warnings": limit_items(warnings, 8),
            "correction_guidance": limit_items(guidance, 8),
            "checked_document_paths": [str(file_path)] if file_path.exists() else [],
            "document_scores": {"traceability_connection_report": score},
            "source_result_summary": summarize_subagent_result(subagent_result),
        }
    subagent_result = load_subagent_result(run_id, scenario)
    corrected_docs_by_key = load_corrected_document_payloads(run_id, scenario)
    findings: List[str] = []
    warnings: List[str] = []
    guidance: List[str] = []
    document_scores: Dict[str, int] = {}
    checked_paths: List[str] = []

    corrected_documents: List[Dict[str, Any]] = []
    for document_key, document_label in DOCUMENT_LABELS.items():
        payload = corrected_docs_by_key.get(document_key, {})
        artifact_path = payload.get("artifact_path", "")
        if artifact_path:
            checked_paths.append(str(artifact_path))

        if payload.get("status") == "missing":
            findings.append(f"{document_label} 보완본 JSON이 생성되지 않았습니다.")
            guidance.append(f"{document_label} 보완본을 {corrected_output_prefix(scenario, scenario)}_output_{document_key}.json 형식으로 생성하세요.")
            document_scores[document_key] = 0
            continue

        document_score = score_corrected_document(document_key, payload, findings, warnings, guidance)
        document_scores[document_key] = document_score
        corrected_documents.append({
            "document_key": document_key,
            "document_label": document_label,
            "file_name": payload.get("correction_metadata", {}).get("source_file_name", ""),
            "saved_path": artifact_path,
            "content_summary": payload,
        })

    scenario_review = run_review_for_scenario(scenario, corrected_documents)
    residual_findings = list(scenario_review.get("findings") or [])
    residual_warnings = list(scenario_review.get("warnings") or [])
    if residual_findings:
        findings.extend(f"보완본 재점검 잔여 오류: {item}" for item in residual_findings)
        guidance.extend(build_guidance_from_messages(scenario, residual_findings))
    if residual_warnings:
        warnings.extend(f"보완본 재점검 잔여 경고: {item}" for item in residual_warnings)

    source_findings_count = len(subagent_result.get("findings") or []) if isinstance(subagent_result, dict) else 0
    source_warnings_count = len(subagent_result.get("warnings") or []) if isinstance(subagent_result, dict) else 0
    applied_change_count = sum(
        len((payload.get("correction_metadata") or {}).get("applied_changes") or [])
        for payload in corrected_docs_by_key.values()
        if isinstance(payload, dict)
    )
    if (source_findings_count or source_warnings_count) and applied_change_count == 0:
        findings.append("원 점검 결과에 오류/경고가 있었지만 문서별 보완본의 applied_changes가 비어 있습니다.")
        guidance.append("원 SubAgent는 findings/warnings 근거에 따라 최소 1개 이상의 셀 수정 또는 보완 후보 행 추가를 수행해야 합니다.")

    structure_score = round(sum(document_scores.values()) / len(DOCUMENT_LABELS)) if document_scores else 0
    residual_score = int(scenario_review.get("score", 0)) if isinstance(scenario_review.get("score"), int) else 0
    score = max(0, min(100, round((structure_score * 0.45) + (residual_score * 0.55))))
    if findings:
        score = max(0, score - min(30, len(findings) * 5))
    if warnings:
        score = max(0, score - min(15, len(warnings) * 2))

    rerun_required = score < threshold
    target_agent_name = scenario_to_agent_name(scenario)
    if rerun_required and not guidance:
        guidance.append(f"{target_agent_name} 문서별 보완본의 잔여 오류를 줄일 수 있도록 관련 문서 행과 컬럼을 보완하세요.")

    summary = (
        f"{target_agent_name} 문서별 보완본 3종을 자가 점검했습니다. "
        f"교정 품질 점수는 {score}점이며 기준점수 {threshold}점 "
        f"{'미만으로 보완 권고가 필요합니다' if rerun_required else '이상으로 통과했습니다'}."
    )
    return {
        "scenario_key": scenario,
        "target_agent_name": target_agent_name,
        "summary": summary,
        "score": score,
        "threshold": threshold,
        "rerun_required": rerun_required,
        "findings": limit_items(findings, 8),
        "warnings": limit_items(warnings, 8),
        "correction_guidance": limit_items(guidance, 8),
        "checked_document_paths": checked_paths,
        "document_scores": document_scores,
    }


def score_corrected_document(
    document_key: str,
    payload: Dict[str, Any],
    findings: List[str],
    warnings: List[str],
    guidance: List[str],
) -> int:
    """단일 보완본 문서 구조와 correction metadata 품질을 점수화합니다."""
    score = 100
    document_label = DOCUMENT_LABELS.get(document_key, document_key)
    if payload.get("load_error"):
        findings.append(f"{document_label} 보완본 JSON을 읽을 수 없습니다: {payload.get('load_error')}")
        guidance.append(f"{document_label} 보완본이 UTF-8 JSON 형식을 유지하도록 저장 상태를 보완하세요.")
        return 0

    parser_status = payload.get("parser_status")
    sheets = payload.get("sheets", [])
    metadata = payload.get("correction_metadata", {})

    if parser_status != "success":
        score -= 25
        findings.append(f"{document_label} 보완본 parser_status가 success가 아닙니다: {parser_status}")
        guidance.append(f"{document_label} 보완본은 원본 파싱 JSON 구조와 parser_status=success를 유지해야 합니다.")
    if not isinstance(sheets, list) or not sheets:
        score -= 25
        findings.append(f"{document_label} 보완본에 sheets 데이터가 없습니다.")
        guidance.append(f"{document_label} 보완본에 원본 sheets[].data 구조를 유지하세요.")
    else:
        row_count = sum(len(sheet.get("data") or []) for sheet in sheets if isinstance(sheet, dict))
        if row_count == 0:
            score -= 15
            findings.append(f"{document_label} 보완본에 데이터 행이 없습니다.")
    if not isinstance(metadata, dict) or not metadata:
        score -= 25
        findings.append(f"{document_label} 보완본에 correction_metadata가 없습니다.")
        guidance.append(f"{document_label} 보완본에 source_review, applied_changes, remaining_warnings를 포함하세요.")
    else:
        if not metadata.get("source_review"):
            score -= 10
            findings.append(f"{document_label} correction_metadata.source_review가 비어 있습니다.")
        if "applied_changes" not in metadata:
            score -= 10
            findings.append(f"{document_label} correction_metadata.applied_changes가 없습니다.")
        remaining = metadata.get("remaining_warnings") or []
        if remaining:
            score -= min(15, len(remaining) * 3)
            warnings.extend(f"{document_label} 잔여 경고: {item}" for item in remaining[:5])

    return max(0, min(100, score))


def run_review_for_scenario(scenario_key: str, corrected_documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """보완본을 해당 시나리오 룰로 재점검합니다."""
    if scenario_key == "basic_quality":
        return review_basic_quality(corrected_documents)
    if scenario_key == "traceability":
        return review_traceability(corrected_documents)
    if scenario_key == "ui_match":
        return review_ui_match(corrected_documents)
    if scenario_key == "coverage":
        return review_coverage(corrected_documents)
    return {
        "scenario_key": scenario_key,
        "summary": "지원하지 않는 시나리오입니다.",
        "score": 0,
        "findings": [f"지원하지 않는 시나리오: {scenario_key}"],
        "warnings": [],
        "recommendations": [],
    }


def compact_review_result(result: Dict[str, Any], limit: int = 8) -> Dict[str, Any]:
    """Keep review tool payloads small before they enter subagent context."""
    if not isinstance(result, dict):
        return {}

    compact = dict(result)
    for key in ("findings", "warnings", "recommendations"):
        values = compact.get(key)
        if isinstance(values, list):
            compact[f"{key}_count"] = len(values)
            compact[key] = limit_items(values, limit)

    summary = compact.get("summary")
    if isinstance(summary, str) and len(summary) > 800:
        compact["summary"] = f"{summary[:800]}..."

    return compact


def build_guidance_from_messages(scenario_key: str, messages: List[str]) -> List[str]:
    """잔여 오류 메시지를 최종 보고서용 보완 지침으로 변환합니다."""
    target_agent_name = scenario_to_agent_name(scenario_key)
    return [
        f"{target_agent_name} 보완 지침: {message} 이 항목이 보완본에 남지 않도록 관련 문서/행/컬럼을 수정하세요."
        for message in messages[:10]
    ]


def limit_items(items: Any, limit: int) -> List[Any]:
    """도구 반환과 구조화 응답이 과도하게 커지지 않도록 목록을 제한합니다."""
    if not isinstance(items, list):
        return []
    if limit <= 0:
        return []
    if len(items) <= limit:
        return items
    sample_count = max(limit - 1, 0)
    remaining_count = len(items) - sample_count
    return [*items[:sample_count], f"... 외 {remaining_count}건 생략"]


def load_subagent_result(run_id: str, scenario_key: str) -> Dict[str, Any]:
    """저장된 원 SubAgent 결과 JSON을 읽습니다."""
    file_path = DATA_ROOT / run_id / canonical_subagent_file_name(scenario_key, scenario_to_agent_name(scenario_key))
    return load_json_dict(file_path)


def load_json_dict(file_path: Path) -> Dict[str, Any]:
    """JSON dict 파일을 안전하게 읽습니다."""
    if not file_path.exists():
        return {}

    last_error = ""
    for encoding in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            payload = json.loads(file_path.read_text(encoding=encoding))
            return payload if isinstance(payload, dict) else {"load_error": "JSON root is not an object"}
        except UnicodeDecodeError as error:
            last_error = f"{encoding}: {error}"
            continue
        except json.JSONDecodeError as error:
            last_error = f"{encoding}: {error}"
            continue
        except OSError as error:
            return {"load_error": str(error)}

    try:
        raw_text = file_path.read_bytes().decode("utf-8", errors="replace")
        payload = json.loads(raw_text)
        return payload if isinstance(payload, dict) else {"load_error": "JSON root is not an object"}
    except (OSError, json.JSONDecodeError) as error:
        return {"load_error": last_error or str(error)}


def scenario_to_agent_name(scenario_key: str) -> str:
    """시나리오 키에 해당하는 원 SubAgent 이름을 반환합니다."""
    names = {
        "basic_quality": "basic-quality-agent",
        "traceability": "traceability-agent",
        "ui_match": "ui-match-agent",
        "coverage": "coverage-agent",
    }
    return names.get(canonical_scenario_key(scenario_key), f"{scenario_key}-agent")


def canonical_scenario_key(value: Any) -> str:
    """시나리오 키 또는 agent 이름을 표준 시나리오 키로 변환합니다."""
    raw_value = str(value or "").strip().lower()
    if "/" in raw_value:
        raw_value = raw_value.split("/")[-1]
    raw_value = raw_value.replace("-", "_")
    aliases = {
        "basic_quality_agent": "basic_quality",
        "traceability_agent": "traceability",
        "ui_match_agent": "ui_match",
        "coverage_agent": "coverage",
        "coverage_review_agent": "coverage",
        "sc_001": "basic_quality",
        "sc_002": "traceability",
        "sc_003": "ui_match",
        "sc_004": "coverage",
    }
    return aliases.get(raw_value, raw_value)


def canonical_subagent_file_name(scenario_key: str, agent_name: str) -> str:
    """서브에이전트 결과 파일명을 한 가지 형태로 고정합니다."""
    scenario = canonical_scenario_key(scenario_key) or canonical_scenario_key(agent_name)
    file_names = {
        "basic_quality": "basic_quality_agent.json",
        "traceability": "traceability_agent.json",
        "ui_match": "ui_match_agent.json",
        "coverage": "coverage_review_agent.json",
    }
    return file_names.get(scenario, f"{sanitize_name(agent_name).replace('-', '_')}.json")


def normalize_subagent_output_payload(
    documents: List[Dict[str, Any]],
    scenario_key: str,
    agent_name: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist a real review payload even when the model passes a tiny tool-result payload."""
    scenario = canonical_scenario_key(scenario_key) or canonical_scenario_key(agent_name)
    if scenario not in {"basic_quality", "traceability", "ui_match", "coverage"}:
        payload = payload if isinstance(payload, dict) else {}
        payload.setdefault("agent_name", sanitize_name(agent_name))
        payload["scenario_key"] = scenario
        return payload

    review_payload = run_review_for_scenario(scenario, documents)
    normalized = dict(review_payload if isinstance(review_payload, dict) else {})
    if not normalized or str(normalized.get("summary", "")).startswith("지원하지 않는"):
        normalized = payload if isinstance(payload, dict) else {}

    normalized["scenario_key"] = scenario
    normalized["agent_name"] = scenario_to_agent_name(scenario)

    if isinstance(payload, dict):
        metadata_keys = ("artifact_path",) if scenario == "coverage" else ("artifact_path", "corrected_document_paths")
        for key in metadata_keys:
            if payload.get(key):
                normalized[key] = payload[key]
        if payload.get("summary") and is_subagent_report_payload(payload):
            normalized["summary"] = payload["summary"]

    return normalized


def is_subagent_report_payload(payload: Dict[str, Any]) -> bool:
    """Return True only for scenario review results, not corrected-document tool results."""
    if not isinstance(payload, dict) or payload.get("corrected") is True:
        return False
    if payload.get("score") is None:
        return False
    if not isinstance(payload.get("summary"), str) or not payload.get("summary"):
        return False
    return any(isinstance(payload.get(key), list) for key in ("findings", "warnings", "recommendations"))


def is_preferred_subagent_payload(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
    """동일 시나리오 중 원본 서브에이전트 결과에 더 가까운 payload를 우선합니다."""
    candidate_name = str(candidate.get("agent_name", ""))
    current_name = str(current.get("agent_name", ""))
    candidate_is_report = is_subagent_report_payload(candidate)
    current_is_report = is_subagent_report_payload(current)
    if candidate_is_report != current_is_report:
        return candidate_is_report

    candidate_scenario = canonical_scenario_key(candidate.get("scenario_key") or candidate_name)
    current_scenario = canonical_scenario_key(current.get("scenario_key") or current_name)
    candidate_name_matches = canonical_scenario_key(candidate_name) == candidate_scenario
    current_name_matches = canonical_scenario_key(current_name) == current_scenario
    if candidate_name_matches != current_name_matches:
        return candidate_name_matches

    # scenario_label/status만 붙은 보고서형 중복보다 원본 subagent payload를 우선합니다.
    candidate_has_report_fields = "scenario_label" in candidate or "status" in candidate
    current_has_report_fields = "scenario_label" in current or "status" in current
    if candidate_has_report_fields != current_has_report_fields:
        return not candidate_has_report_fields

    return len(candidate.get("findings") or []) >= len(current.get("findings") or [])


def make_actions(scenario_key: str, findings: List[str], warnings: List[str]) -> List[str]:
    """findings와 warnings에서 Rule ID를 추출하여 동적으로 구체적인 권고사항을 생성합니다."""
    actions = set()  # 중복 제거를 위해 set 사용
    
    # Rule ID별 구체적인 수정 권고 매핑 (전체 Rule ID 포함)
    rule_recommendations = {
        # 문서 구조
        "G-DOC-001": "필수 문서가 누락되었습니다. 요구사항정의서, 기능정의서, UI설계서를 모두 업로드하세요.",
        "G-SHEET-001": "데이터 시트가 없습니다. 문서에 데이터 행이 있는지 확인하세요.",
        "G-HEADER-001": "헤더를 인식하지 못했습니다. 첫 행에 컬럼명을 입력하고 다시 업로드하세요.",
        "G-HEADER-002": "필수 컬럼이 누락되었습니다. SKILL.md의 필수 컬럼 목록을 확인하고 추가하세요.",
        
        # 값 관련
        "G-VALUE-001": "필수 필드 값이 누락되었습니다. 빈 셀을 찾아 적절한 값을 입력하세요.",
        "G-VALUE-002": "필드 앞뒤에 불필요한 공백이 있습니다. 공백을 제거하세요.",
        "G-VALUE-003": "셀에 탭이나 개행 같은 제어문자가 포함되어 있습니다. 제거하세요.",
        "G-VALUE-004": "필드 값이 너무 길어 가독성이 낮습니다. 불필요한 부분을 삭제하거나 축약하세요.",
        "G-VALUE-005": "필드에 허용되지 않는 특수문자가 포함되어 있습니다. 제거하거나 대체하세요.",
        
        # ID 형식
        "G-ID-REQ-001": "요구사항 ID가 REQ-### 형식이 아닙니다. 예: REQ-001",
        "G-ID-FUNC-001": "기능ID가 REQ-###-F## 형식이 아닙니다. 예: REQ-001-F01",
        "G-ID-UI-001": "화면ID가 UI-### 형식이 아닙니다. 예: UI-001",
        
        # 허용값
        "G-STATUS-001": "상태 값이 허용값 범위를 벗어났습니다. [신규, 추가, 수정, 삭제, 진행중, 완료, 보류] 중 하나를 선택하세요.",
        "G-UI-TYPE-001": "화면유형이 허용값 범위를 벗어났습니다. [화면, 팝업, 영역, 모바일, 배치, 컴포넌트] 중 하나를 선택하세요.",
        "G-PRIORITY-001": "우선순위가 1~5 범위를 벗어났습니다. 1~5의 정수로 입력하세요.",
        
        # 날짜
        "G-DATE-001": "날짜 형식이 YYYY-MM-DD가 아닙니다. 예: 2026-05-03",
        "G-DATE-002": "유효하지 않은 날짜입니다. 존재하는 날짜로 수정하세요.",
        "G-DATE-003": "최종수정일자가 최초요청일자보다 이릅니다. 날짜 순서를 맞춰주세요.",
        "G-DATE-004": "상태가 신규가 아닌데 최종수정일자가 없습니다. 수정 날짜를 입력하세요.",
        
        # 시스템명
        "G-SYSTEM-001": "시스템명이 누락되었습니다. 한글 또는 영문 시스템명을 입력하세요.",
        "G-SYSTEM-002": "시스템명에 허용되지 않는 문자가 있습니다. 한글, 영문, 숫자, 공백만 사용하세요.",
        "G-SYSTEM-003": "시스템명이 너무 길거나 짧습니다. 2~10자 범위로 입력하세요.",
        
        # 오탈자
        "G-TYPO-001": "단독 한글 자모가 감지되었습니다. 제거하거나 수정하세요.",
        "G-TYPO-002": "오탈자 가능성이 있습니다. SKILL.md의 오탈자 사전을 참고하여 수정하세요.",
        "G-TYPO-003": "반복 기호(!!, ??, ~~)가 사용되었습니다. 업무 문서에 부적합하므로 제거하세요.",
        "G-TYPO-004": "이모지나 채팅체 표현이 있습니다. 정식 표현으로 수정하세요.",
        "G-TYPO-005": "유사한 용어가 혼용되었을 가능성이 있습니다. 용어를 통일하세요.",
        
        # 행
        "G-ROW-001": "완전히 빈 행입니다. 데이터가 없으면 행을 삭제하세요.",
        "G-ROW-002": "ID만 있고 필수 정보가 대부분 비어 있습니다. 필수 필드를 모두 채우세요.",
        
        # 요구사항정의서
        "REQ-COL-001": "요구사항정의서의 필수 컬럼이 없습니다. SKILL.md 7.1절을 참고하여 필수 컬럼을 추가하세요.",
        "REQ-ID-001": "요구사항 ID가 REQ-### 형식이 아닙니다.",
        "REQ-ID-002": "요구사항 ID가 중복되었습니다. 같은 ID를 가진 행들을 찾아 ID를 변경하세요.",
        "REQ-NAME-001": "요구사항명이 누락되었습니다. 요구사항의 이름을 입력하세요.",
        "REQ-NAME-002": "요구사항명에 오탈자 가능성이 있습니다. 확인 후 수정하세요.",
        "REQ-OWNER-001": "요청자(요구사항 Owner)가 누락되었습니다. 2~20자 범위의 담당자 이름을 입력하세요.",
        "REQ-DATE-001": "최종수정일자가 최초요청일자보다 이릅니다. 날짜 순서를 맞춰주세요.",
        "REQ-BODY-001": "기능 요구사항이 누락되었습니다. 10자 이상의 구체적인 요구사항을 입력하세요.",
        "REQ-BODY-002": "요구사항 내용이 너무 짧아 구체성이 부족합니다. 최소 10자 이상으로 상세히 작성하세요.",
        "REQ-SCREEN-001": "화면 요구사항이 누락되었습니다. 필요한 화면 사항을 입력하세요.",
        
        # 기능정의서
        "FUNC-COL-001": "기능정의서의 필수 컬럼이 없습니다. SKILL.md 8.1절을 참고하여 필수 컬럼을 추가하세요.",
        "FUNC-REQ-ID-001": "요구사항 ID가 REQ-### 형식이 아닙니다.",
        "FUNC-ID-001": "기능ID가 REQ-###-F## 형식이 아닙니다.",
        "FUNC-ID-002": "기능ID가 중복되었습니다. 같은 기능ID를 가진 행들을 찾아 수정하세요.",
        "FUNC-NAME-001": "기능명이 누락되었습니다. 기능의 이름을 입력하세요.",
        "FUNC-STATUS-001": "상태가 누락되었습니다. [신규, 추가, 수정, 삭제, 진행중, 완료, 보류] 중 하나를 선택하세요.",
        "FUNC-DESC-001": "설명이 누락되었습니다. 기능에 대한 설명을 입력하세요.",
        "FUNC-BODY-001": "기능 내용이 누락되었습니다. 기능의 동작을 상세히 입력하세요.",
        "FUNC-INPUT-001": "입력이 누락되었습니다. 이 기능의 입력값을 입력하세요.",
        "FUNC-OUTPUT-001": "출력이 누락되었습니다. 이 기능의 출력값을 입력하세요.",
        "FUNC-UI-ID-001": "화면ID가 UI-### 형식이 아닙니다.",
        "FUNC-PRIORITY-001": "우선순위가 1~5 범위를 벗어났습니다. 1~5의 정수로 입력하세요.",
        
        # UI설계서
        "UI-COL-001": "UI설계서의 필수 컬럼이 없습니다. SKILL.md 9.1절을 참고하여 필수 컬럼을 추가하세요.",
        "UI-REQ-ID-001": "요구사항 ID가 REQ-### 형식이 아닙니다.",
        "UI-FUNC-ID-001": "기능ID가 REQ-###-F## 형식이 아닙니다.",
        "UI-ID-001": "화면ID가 UI-### 형식이 아닙니다.",
        "UI-NAME-001": "화면명이 누락되었습니다. 화면의 이름을 입력하세요.",
        "UI-TYPE-001": "화면유형이 허용값 범위를 벗어났습니다. [화면, 팝업, 영역, 모바일, 배치, 컴포넌트] 중 하나를 선택하세요.",
        "UI-STATUS-001": "상태가 누락되었습니다. [신규, 추가, 수정, 삭제, 진행중, 완료, 보류] 중 하나를 선택하세요.",
        "UI-ACTION-001": "사용자행위/버튼이 누락되었습니다. 이 화면에서 가능한 버튼이나 행위를 입력하세요.",
        "UI-AUTH-001": "권한이 누락되었습니다. 이 화면에 필요한 권한을 입력하세요.",
        "UI-API-001": "API/서비스 형식이 일반적이지 않습니다. 'Service.method' 형식으로 입력하세요.",
    }
    
    # findings 분석
    for finding in findings:
        rule_match = re.search(r"\[([^\]]+)\]", finding)
        if rule_match:
            rule_id = rule_match.group(1)
            if rule_id in rule_recommendations:
                actions.add(rule_recommendations[rule_id])
    
    # warnings 분석
    for warning in warnings:
        rule_match = re.search(r"\[([^\]]+)\]", warning)
        if rule_match:
            rule_id = rule_match.group(1)
            if rule_id in rule_recommendations:
                actions.add(rule_recommendations[rule_id])
    
    # 최종 권고
    if actions:
        actions.add("위 항목들을 수정한 후 재검사를 수행하세요.")
    else:
        actions.add("점검 결과 개선 필요 사항이 없습니다. 정기 점검을 유지하세요.")
    
    return list(actions)


def _calculate_score(findings: List[str], warnings: List[str]) -> int:
    """문서별 평균과 반복 오류 완화를 적용해 기초 품질 점수를 계산합니다."""
    blocker_rules = {
        "G-DOC-001",
        "G-HEADER-001",
        "REQ-COL-001", "FUNC-COL-001", "UI-COL-001",
    }

    error_rules = {
        "G-SHEET-001",
        "G-HEADER-002",
        "G-VALUE-001", "G-VALUE-003",
        "G-ID-REQ-001", "G-ID-FUNC-001", "G-ID-UI-001",
        "G-STATUS-001", "G-UI-TYPE-001", "G-PRIORITY-001",
        "G-DATE-001", "G-DATE-002", "G-DATE-003",
        "G-SYSTEM-001", "G-SYSTEM-002",
        "REQ-ID-001", "REQ-ID-002", "REQ-NAME-001", "REQ-OWNER-001", "REQ-DATE-001",
        "REQ-BODY-001", "REQ-SCREEN-001",
        "FUNC-REQ-ID-001", "FUNC-ID-001", "FUNC-ID-002", "FUNC-NAME-001", "FUNC-STATUS-001",
        "FUNC-DESC-001", "FUNC-BODY-001", "FUNC-INPUT-001", "FUNC-OUTPUT-001", "FUNC-UI-ID-001", "FUNC-PRIORITY-001",
        "UI-REQ-ID-001", "UI-FUNC-ID-001", "UI-ID-001", "UI-NAME-001", "UI-TYPE-001",
        "UI-STATUS-001", "UI-ACTION-001", "UI-AUTH-001",
    }

    warning_rules = {
        "G-VALUE-002", "G-VALUE-004", "G-VALUE-005",
        "G-DATE-004",
        "G-SYSTEM-003",
        "G-ROW-002",
        "G-TYPO-001", "G-TYPO-002", "G-TYPO-003", "G-TYPO-004",
        "REQ-NAME-002", "REQ-BODY-002",
        "UI-API-001",
    }

    info_rules = {
        "G-ROW-001",
        "G-TYPO-005",
    }

    base_penalties = {
        "blocker": 35.0,
        "error": 8.0,
        "warning": 3.0,
        "info": 1.0,
    }
    repeat_multipliers = [1.0, 0.6, 0.35]
    document_labels = list(DOCUMENT_LABELS.values())
    global_label = "__global__"
    document_scores = {label: 100.0 for label in [*document_labels, global_label]}
    global_score_used = False
    occurrence_counts: Dict[tuple, int] = {}

    def extract_rule_ids(message: str) -> List[str]:
        rule_match = re.search(r"\[([^\]]+)\]", message)
        if not rule_match:
            return []
        return [rule_id.strip() for rule_id in rule_match.group(1).split("/") if rule_id.strip()]

    def severity(rule_id: str) -> Optional[str]:
        if rule_id in blocker_rules:
            return "blocker"
        if rule_id in error_rules:
            return "error"
        if rule_id in warning_rules:
            return "warning"
        if rule_id in info_rules:
            return "info"
        return None

    def primary_rule(rule_ids: List[str]) -> Optional[str]:
        severity_rank = {"blocker": 4, "error": 3, "warning": 2, "info": 1}
        known_rules = [rule_id for rule_id in rule_ids if severity(rule_id)]
        if not known_rules:
            return None
        return max(known_rules, key=lambda rule_id: severity_rank[severity(rule_id)])

    def target_documents(message: str) -> List[str]:
        matched_labels = [label for label in document_labels if label in message]
        return matched_labels or [global_label]

    def apply_penalty(message: str) -> bool:
        rule_id = primary_rule(extract_rule_ids(message))
        if not rule_id:
            return False

        rule_severity = severity(rule_id)
        if not rule_severity:
            return False

        nonlocal_global_target = False
        for document_label in target_documents(message):
            if document_label == global_label:
                nonlocal_global_target = True
            count_key = (document_label, rule_id)
            count = occurrence_counts.get(count_key, 0)
            occurrence_counts[count_key] = count + 1
            multiplier = repeat_multipliers[min(count, len(repeat_multipliers) - 1)]
            document_scores[document_label] -= base_penalties[rule_severity] * multiplier
        return nonlocal_global_target

    for finding in findings:
        global_score_used = apply_penalty(finding) or global_score_used

    for warning in warnings:
        global_score_used = apply_penalty(warning) or global_score_used

    score_labels = [*document_labels, *([global_label] if global_score_used else [])]
    bounded_scores = [max(0.0, min(100.0, document_scores[label])) for label in score_labels]
    return round(sum(bounded_scores) / len(bounded_scores))


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
