"""Sidebar components for the integrated review app."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from ui.service_data import get_result_view_label


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBAGENT_DATA_ROOT = PROJECT_ROOT / "data" / "subagents"
TEMPLATE_ROOT = PROJECT_ROOT / "db" / "template"
DOCUMENT_TEMPLATES = [
    ("requirement_definition", "요구사항 정의서", "요구사항정의서.xlsx"),
    ("feature_definition", "기능 정의서", "기능정의서.xlsx"),
    ("ui_design", "UI 설계서", "UI설계서.xlsx"),
]
EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render_sidebar(scenario_order: list[str]) -> None:
    """Render the app sidebar."""
    with st.sidebar:
        st.title("📃산출물 점검 Agent")
        st.caption("프로젝트 산출물을 업로드하면 시나리오별 Agent가 품질 이슈와 보완 포인트를 정리합니다.")

        st.divider()
        render_recent_runs()

        st.divider()
        st.markdown("### 산출물 템플릿 다운로드")
        render_template_download_buttons()

        st.divider()
        render_scenario_guide(scenario_order)


def render_side_filter(scenario_order: list[str] | None = None) -> None:
    """Backward-compatible sidebar entrypoint."""
    render_sidebar(scenario_order or ["basic_quality", "traceability", "ui_match", "coverage"])


def render_recent_runs() -> None:
    """Render recent saved run history."""
    st.markdown("### 최근 점검 이력")
    options = build_recent_run_options()
    if not options:
        st.info("저장된 점검 이력이 없습니다.")
        return

    labels = [label for label, _run_id in options]
    selected_label = st.selectbox(
        "최근 실행",
        labels,
        key="sidebar_recent_run",
        label_visibility="collapsed",
    )
    selected_run_id = next((run_id for label, run_id in options if label == selected_label), "")
    if selected_run_id:
        render_recent_run_summary(selected_run_id)


def render_recent_run_summary(run_id: str) -> None:
    """Render a compact summary for one saved run."""
    report = load_json_dict(SUBAGENT_DATA_ROOT / run_id / "final_report.json")
    if not report:
        st.caption("최종 보고서가 아직 저장되지 않았습니다.")
        return

    score = report.get("overall_score")
    blocked = report.get("blocked_scenarios", [])
    st.metric("점수", f"{score}점" if isinstance(score, (int, float)) else "미집계")
    st.caption(f"실행 ID: {run_id}")
    if isinstance(blocked, list) and blocked:
        st.caption(f"보완 필요: {len(blocked)}개")
    else:
        st.caption("보완 필요 시나리오 없음")


def render_template_download_buttons() -> None:
    """Render download buttons for the three upload document templates."""
    for document_key, document_label, file_name in DOCUMENT_TEMPLATES:
        file_path = TEMPLATE_ROOT / file_name
        if not file_path.exists():
            st.button(
                f"{document_label} 템플릿",
                key=f"download_template_missing_{document_key}",
                disabled=True,
                width="stretch",
            )
            st.caption("템플릿 파일을 찾을 수 없습니다.")
            continue

        st.download_button(
            label=f"{document_label} 템플릿",
            data=file_path.read_bytes(),
            file_name=file_path.name,
            mime=EXCEL_MIME_TYPE,
            key=f"download_template_{document_key}",
            type="secondary",
            icon=":material/download:",
            width="stretch",
            on_click="ignore",
        )


def render_scenario_guide(scenario_order: list[str]) -> None:
    """Render compact descriptions for the configured scenarios."""
    st.markdown("### 점검 시나리오 안내")
    scenario_guides = {
        "basic_quality": ("SC-001 기초 품질", "ID 형식, 필수값, 상태, 우선순위, 오탈자를 점검합니다."),
        "traceability": ("SC-002 문서 연결성", "요구사항 -> 기능 -> UI ID 연결 구조를 점검합니다."),
        "ui_match": ("SC-003 기능-화면 일치", "기능 정의와 UI 설계의 행위, 버튼, 입출력 일치성을 점검합니다."),
        "coverage": ("SC-004 기능 완전성", "요구사항 대비 기능/UI 누락, 과잉, 분해 부족을 분석합니다."),
    }
    for scenario_key in scenario_order:
        title, description = scenario_guides.get(
            scenario_key,
            (get_result_view_label(scenario_key), "시나리오 설명이 없습니다."),
        )
        with st.expander(title, expanded=False):
            st.caption(description)


def build_recent_run_options(limit: int = 8) -> list[tuple[str, str]]:
    """Build display labels and run IDs for recent saved runs."""
    options: list[tuple[str, str]] = []
    for run_folder in list_saved_run_folders()[:limit]:
        run_id = run_folder.name
        run_at = parse_run_folder_name(run_id)
        report = load_json_dict(run_folder / "final_report.json")
        score = report.get("overall_score") if isinstance(report, dict) else None
        blocked = report.get("blocked_scenarios", []) if isinstance(report, dict) else []
        score_label = f"{int(score)}점" if isinstance(score, (int, float)) else "점수 없음"
        status_label = "보완 필요" if isinstance(blocked, list) and blocked else "검토 완료"
        time_label = run_at.strftime("%m-%d %H:%M") if run_at else run_id
        options.append((f"{time_label} · {score_label} · {status_label}", run_id))
    return options


def list_saved_run_folders() -> list[Path]:
    """Return saved run folders sorted from newest to oldest."""
    if not SUBAGENT_DATA_ROOT.exists():
        return []

    dated_folders: list[tuple[datetime, Path]] = []
    for child in SUBAGENT_DATA_ROOT.iterdir():
        if not child.is_dir():
            continue

        run_at = parse_run_folder_name(child.name)
        if run_at is None:
            continue

        dated_folders.append((run_at, child))

    dated_folders.sort(key=lambda item: item[0], reverse=True)
    return [folder for _, folder in dated_folders]


def parse_run_folder_name(folder_name: str) -> datetime | None:
    """Parse a run folder name in YYYYMMDD_HHMMSS format."""
    try:
        return datetime.strptime(folder_name, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def load_json_dict(file_path: Path) -> dict:
    """Load a JSON object from disk and return an empty dict on failure."""
    if not file_path.exists():
        return {}

    try:
        with file_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}
