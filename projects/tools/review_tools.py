"""DeepAgents에서 사용하는 최소 review tool 모음."""

from __future__ import annotations

import json
import re
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
        if isinstance(payload, dict):
            payload.setdefault("agent_name", sanitize_name(agent_name))
        file_path = DATA_ROOT / run_id / canonical_subagent_file_name(scenario_key, agent_name)
        if file_path.exists():
            try:
                existing_payload = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing_payload = {}
            if isinstance(existing_payload, dict) and is_preferred_subagent_payload(payload, existing_payload):
                save_json(file_path, payload)
            return str(file_path)
        save_json(file_path, payload)
        return str(file_path)

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
            loaded_by_scenario[key]
            for key in ["basic_quality", "traceability", "ui_match", "coverage"]
            if key in loaded_by_scenario
        )

        return {"run_id": run_id, "outputs": outputs}

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


def is_preferred_subagent_payload(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
    """동일 시나리오 중 원본 서브에이전트 결과에 더 가까운 payload를 우선합니다."""
    candidate_name = str(candidate.get("agent_name", ""))
    current_name = str(current.get("agent_name", ""))
    candidate_is_canonical = "-" not in candidate_name
    current_is_canonical = "-" not in current_name
    if candidate_is_canonical != current_is_canonical:
        return candidate_is_canonical

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
