"""업로드 문서를 JSON으로 정리하고 Orchestrator에 전달하는 백엔드 진입점."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from agents.orchestrator import run_orchestrator
from ui.service_data import get_scenario_order
from utils.common_method import log

PROJECT_ROOT = Path(__file__).resolve().parent  # projects 루트 경로
INTAKE_DIR = PROJECT_ROOT / "data" / "intake"  # 업로드 문서와 JSON 저장 경로

XML_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",}  # xlsx xml 파싱용 네임스페이스
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"  # workbook relationship 네임스페이스
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"  # package relationship 네임스페이스

# 진입점 함수 
def run_backend_pipeline(
    uploaded_documents: dict[str, dict[str, Any]], # 업로드한 산출물
    user_request: str, # 사용자 추가 요청 사항
    scenario_order: list[str], # 점검 시나리오 순서
) -> dict[str, Any]:
    """업로드 문서를 JSON payload로 만들고 Orchestrator에 전달합니다."""
    
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") # 현재 실행 고유 ID
    run_dir = INTAKE_DIR / run_id  # 실행별 저장 폴더
    run_dir.mkdir(parents=True, exist_ok=True) # 저장 폴더 생성
 
    document_payloads = []  # 업로드 문서별 JSON 정보
    for document_key, document_info in uploaded_documents.items():
        uploaded_file = document_info.get("file")
        
        if uploaded_file is None:
            continue
        document_payloads.append(
            build_document_payload(document_key, document_info, run_dir)
        )

    agent_request = build_agent_request_payload(
        run_id=run_id,
        user_request=user_request,
        scenario_order=scenario_order,
        document_payloads=document_payloads,
    )
    log(f"agent_request : {agent_request}", "info")

    request_path = run_dir / "agent_request.json"  # Orchestrator 전달 전 JSON 파일 경로
    agent_request["request_path"] = str(request_path)  # DeepAgents 프롬프트에서 참고할 intake payload 경로
    write_json_file(request_path, agent_request) # reqeust_path로 json 파일 저장 intake/run_id/agent_request.json
    
    orchestrator_response = run_orchestrator(agent_request)  # 현재는 Orchestrator 스텁 호출
    response_path = run_dir / "orchestrator_response.json"  # Orchestrator 응답 JSON 경로
    write_json_file(response_path, orchestrator_response)

    return {
        "run_id": run_id,
        "agent_request": agent_request,
        "agent_request_path": str(request_path),
        "orchestrator_response": orchestrator_response,
        "orchestrator_response_path": str(response_path),
    }

def build_document_payload(
    document_key: str,
    document_info: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """업로드 문서 하나를 구조화된 JSON 데이터로 변환합니다."""
    uploaded_file = document_info["file"]  # Streamlit 업로드 파일 객체
    file_bytes = uploaded_file.getvalue()  # 업로드 원본 바이트
    file_name = uploaded_file.name  # 원본 파일 이름
    saved_path = save_uploaded_file(run_dir, document_key, file_name, file_bytes)  # 로컬 저장 경로

    return {
        "document_key": document_key,  # 내부 문서 구분 키
        "document_label": document_info["label"],  # 화면 표시용 문서 이름
        "file_name": file_name,  # 원본 파일명
        "file_extension": saved_path.suffix.lower(),  # 파일 확장자
        "mime_type": getattr(uploaded_file, "type", ""),  # 업로드 mime type
        "size_bytes": len(file_bytes),  # 파일 크기
        "sha256": hashlib.sha256(file_bytes).hexdigest(),  # 무결성 확인용 해시
        "saved_path": str(saved_path),  # 로컬 저장 경로
        "content_summary": extract_file_summary(saved_path),  # 파일 내용 요약
    }


def save_uploaded_file(
    run_dir: Path,
    document_key: str,
    file_name: str,
    file_bytes: bytes,
) -> Path:
    """업로드 파일을 실행 전용 폴더에 저장합니다."""
    suffix = Path(file_name).suffix.lower()  # 원본 확장자
    safe_name = sanitize_file_name(Path(file_name).stem)  # 파일명 안전화
    saved_path = run_dir / f"{document_key}__{safe_name}{suffix}"  # 저장 파일명
    saved_path.write_bytes(file_bytes)
    return saved_path


def sanitize_file_name(file_name: str) -> str:
    """저장용 파일명을 안전한 형식으로 정리합니다."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("_")
    return sanitized or "uploaded_file"

# =========================================================
# 파일 요약
# =========================================================
def extract_file_summary(file_path: Path) -> dict[str, Any]:
    """파일 확장자에 따라 요약 정보를 추출합니다."""
    suffix = file_path.suffix.lower()

    if suffix == ".xlsx":
        return extract_xlsx_summary(file_path)

    if suffix == ".xls":
        return {
            "parser": "metadata_only",  # xls 는 현재 메타데이터만 처리
            "parser_status": "preview_not_supported",  # 미리보기 미지원 상태
            "note": "현재 환경에는 xls 파서를 위한 외부 라이브러리가 없어 메타데이터만 저장했습니다.",
        }

    return {
        "parser": "metadata_only",  # 비엑셀 형식 처리
        "parser_status": "unsupported_extension",  # 미지원 확장자 상태
        "note": "현재는 xlsx 미리보기 요약만 지원합니다.",
    }


def extract_xlsx_summary(file_path: Path) -> dict[str, Any]:
    """xlsx 파일에서 시트 정보와 데이터를 추출합니다."""
    try:
        with ZipFile(file_path) as workbook_zip:
            shared_strings = load_shared_strings(workbook_zip)  # sharedStrings 조회
            workbook_root = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
            relationship_map = load_workbook_relationships(workbook_zip)  # 시트 경로 매핑

            sheets = []  # 시트별 요약 목록
            for sheet in workbook_root.findall("main:sheets/main:sheet", XML_NS):
                sheet_name = sheet.attrib.get("name", "Sheet")
                relation_id = sheet.attrib.get(f"{{{REL_NS}}}id", "")
                target = relationship_map.get(relation_id, "")
                if not target:
                    continue
                sheet_path = normalize_sheet_path(target)
                sheets.append(
                    extract_sheet_data(
                        workbook_zip,
                        sheet_name,
                        sheet_path,
                        shared_strings,
                    )
                )

        return {
            "parser": "builtin_xlsx_xml",  # 내장 xml 파서 사용
            "parser_status": "success",  # 파싱 성공 상태
            "sheet_count": len(sheets),  # 전체 시트 수
            "sheet_names": [sheet["sheet_name"] for sheet in sheets],  # 시트 이름 목록
            "sheets": sheets,  # 시트별 데이터
        }
    except Exception as error:  # 파싱 실패 시에도 JSON 생성은 유지
        return {
            "parser": "builtin_xlsx_xml",  # 사용한 파서 이름
            "parser_status": "error",  # 파싱 실패 상태
            "error_message": str(error),  # 실패 원인
        }


def load_shared_strings(workbook_zip: ZipFile) -> list[str]:
    """xlsx sharedStrings.xml 에서 문자열 테이블을 읽어옵니다."""
    if "xl/sharedStrings.xml" not in workbook_zip.namelist():
        return []

    shared_root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
    shared_strings = []
    for item in shared_root.findall("main:si", XML_NS):
        parts = [node.text or "" for node in item.findall(".//main:t", XML_NS)]
        shared_strings.append("".join(parts))
    return shared_strings


def load_workbook_relationships(workbook_zip: ZipFile) -> dict[str, str]:
    """workbook.xml.rels 에서 시트 경로 매핑을 읽어옵니다."""
    relationship_root = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
    relationship_map = {}
    
    for relation in relationship_root.findall(f"{{{PKG_REL_NS}}}Relationship"):
        relationship_map[rel.attrib.get("Id")] = rel.attrib.get("Target")
        
    return relationship_map


def normalize_sheet_path(target: str) -> str:
    """relationship target 을 zip 내부 시트 경로로 정규화합니다."""
    normalized = target.lstrip("/")
    if not normalized.startswith("xl/"):
        normalized = f"xl/{normalized}"
    return normalized


def extract_sheet_data(
    workbook_zip: ZipFile,
    sheet_name: str,
    sheet_path: str,
    shared_strings: list[str],
) -> dict[str, Any]:
    """시트에서 파일명, 열 이름, 데이터를 추출합니다."""
    sheet_root = ET.fromstring(workbook_zip.read(sheet_path))

    # 행 데이터를 셀 단위로 추출
    all_rows = list(sheet_root.findall(".//main:sheetData/main:row", XML_NS))

    # 기본값 초기화
    file_name = ""
    columns: list[str] = []
    data_rows: list[dict[str, Any]] = []

    if len(all_rows) < 4:
        return {
            "sheet_name": sheet_name,
            "file_name": file_name,
            "columns": columns,
            "data": data_rows,
            "row_count": 0,
            "note": "행이 부족합니다 (최소 4행 필요)",
        }

    # 1행: 파일 이름
    file_name_row = all_rows[0]
    file_name = extract_row_first_cell(file_name_row, shared_strings)

    # 3행: 열 이름들 (0-indexed: 2)
    columns_row = all_rows[2]
    for cell in columns_row.findall("main:c", XML_NS):
        value = extract_cell_value(cell, shared_strings)
        if value:
            columns.append(value)

    # 열 인덱스를 columns 이름으로 매핑 (A->columns[0], B->columns[1], ...)
    col_index_map = {}
    for idx, col_letter in enumerate(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]):
        if idx < len(columns):
            col_index_map[col_letter] = columns[idx]

    # 4행부터: 실제 데이터 (0-indexed: 3부터)
    for row in all_rows[3:]:
        row_data: dict[str, Any] = {}
        for cell in row.findall("main:c", XML_NS):
            cell_ref = cell.attrib.get("r", "")
            # 열 인덱스 추출 (A, B, C, ...)
            col_letter = "".join(c for c in cell_ref if c.isalpha())
            value = extract_cell_value(cell, shared_strings)
            # columns 이름으로 key 설정
            col_key = col_index_map.get(col_letter, col_letter)
            row_data[col_key] = value

        # 3번째 열(C 열)의 ID Key가 비어있으면 추출 중단
        id_key = row_data.get(columns[2] if len(columns) > 2 else "", "")
        if not id_key:
            break

        # 모든 값이 빈 문자열인 경우 제외
        if any(v for v in row_data.values()):
            data_rows.append(row_data)

    return {
        "sheet_name": sheet_name,  # 시트 이름
        "file_name": file_name,  # 1행: 파일 이름
        "columns": columns,  # 3행: 열 이름들
        "data": data_rows,  # 4행부터: 실제 데이터
        "row_count": len(data_rows),  # 데이터 행 수
    }


def extract_row_first_cell(row: ET.Element, shared_strings: list[str]) -> str:
    """행의 첫 번째 셀 값을 추출합니다."""
    for cell in row.findall("main:c", XML_NS):
        return extract_cell_value(cell, shared_strings)
    return ""


def extract_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """xlsx 셀의 값을 문자열로 추출합니다."""
    cell_type = cell.attrib.get("t", "")  # 셀 타입
    raw_value = cell.findtext("main:v", default="", namespaces=XML_NS)

    if cell_type == "s":
        if raw_value.isdigit() and int(raw_value) < len(shared_strings):
            return shared_strings[int(raw_value)]
        return ""

    if cell_type == "inlineStr":
        text_nodes = [node.text or "" for node in cell.findall(".//main:t", XML_NS)]
        return "".join(text_nodes)

    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"

    if raw_value:
        return raw_value

    formula = cell.findtext("main:f", default="", namespaces=XML_NS)
    return f"={formula}" if formula else ""


def build_agent_request_payload(
    run_id: str,
    user_request: str,
    scenario_order: list[str],
    document_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Orchestrator에 전달할 최종 JSON payload를 생성합니다."""
    return {
        "run_id": run_id,  # 현재 실행 ID
        "created_at": datetime.now().isoformat(timespec="seconds"),  # payload 생성 시각
        "user_request": user_request,  # 사용자 추가 요청
        "scenario_order": scenario_order,  # 순차 실행 시나리오 순서
        "document_count": len(document_payloads),  # 업로드 문서 수
        "documents": document_payloads,  # 문서별 상세 정보
    }


def write_json_file(file_path: Path, payload: dict[str, Any]) -> None:
    """dict payload를 UTF-8 JSON 파일로 저장합니다."""
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

# =========================================================
# File Find & Upload
# =========================================================
class LocalUploadedFile:
    """Adapter that lets local files behave like Streamlit uploads."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self.name = file_path.name
        self.type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    def getvalue(self) -> bytes:
        return self._file_path.read_bytes()

def find_file(paths: list[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"파일을 찾을 수 없음: {paths}")

# =========================================================
# MAIN (핵심 변경)
# =========================================================

def main() -> int:
    requirement_path = find_file([
        PROJECT_ROOT / "db" / "요구사항정의서.xlsx",
        PROJECT_ROOT / "db" / "요구사항정의서.xls",
    ])
    feature_path = find_file([
        PROJECT_ROOT / "db" / "기능정의서.xlsx",
        PROJECT_ROOT / "db" / "기능정의서.xls",
    ])
    ui_path = find_file([
        PROJECT_ROOT / "db" / "ui설계서.xlsx",
        PROJECT_ROOT / "db" / "ui설계서.xls",
        PROJECT_ROOT / "db" / "UI설계서.xlsx",
        PROJECT_ROOT / "db" / "UI설계서.xls",
    ])

    uploaded_documents = {
        "requirement_definition": {
            "label": "요구사항 정의서",
            "file": LocalUploadedFile(requirement_path),
        },
        "feature_definition": {
            "label": "기능 정의서",
            "file": LocalUploadedFile(feature_path),
        },
        "ui_design": {
            "label": "UI 설계서",
            "file": LocalUploadedFile(ui_path),
        },
    }
        
    backend_result = run_backend_pipeline(
        uploaded_documents=uploaded_documents,
        user_request="핵심 이슈를 우선순위 기준으로 보여줘.",
        scenario_order=get_scenario_order(),
    )

    #print(json.dumps(backend_result, ensure_ascii=False, indent=2))

    return 0

if __name__ == "__main__":
    main()
