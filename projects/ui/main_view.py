"""중앙 메인 화면을 구성하는 파일."""

from collections.abc import Callable
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


from main import run_backend_pipeline
from ui.service_data import (
    INTEGRATED_SERVICE,
    get_all_required_files,
    get_result_view_label,
    get_scenario_order,
)
from ui.side_filter import render_sidebar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBAGENT_DATA_ROOT = PROJECT_ROOT / "data" / "subagents"
STREAM_LOG_LIMIT = 12
DEFAULT_AGENT_STREAM_STATE = {
    "kind": "idle",
    "message": "통합 점검을 실행하면 Main Agent와 서브에이전트 진행 상황이 여기에 표시됩니다.",
    "progress": 0.0,
    "logs": [],
}
CORRECTION_RESULT_TABS = [
    ("basic_quality", "기초 품질 점검 교정 결과", "basic_quality_agent"),
    ("traceability", "문서 연결성 점검 교정 결과", "traceability_agent"),
    ("ui_match", "기능-화면일치점검 교정 결과", "ui_match_agent"),
]
CORRECTION_DOCUMENTS = [
    ("requirement_definition", "요구사항 정의서"),
    ("feature_definition", "기능 정의서"),
    ("ui_design", "UI 설계서"),
]


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


def get_result_run_id(results: dict) -> str:
    """Return the run_id associated with the displayed result."""
    if isinstance(results, dict):
        run_id = results.get("run_id")
        if run_id:
            return str(run_id)

        final_report = results.get("final_report")
        if isinstance(final_report, dict) and final_report.get("run_id"):
            return str(final_report["run_id"])

    last_run = st.session_state.get("last_run", {})
    if isinstance(last_run, dict) and last_run.get("run_id"):
        return str(last_run["run_id"])

    return ""


def corrected_document_path(run_id: str, scenario_key: str, output_prefix: str, document_key: str) -> Path:
    """Build the saved corrected document JSON path."""
    return SUBAGENT_DATA_ROOT / run_id / scenario_key / f"{output_prefix}_output_{document_key}.json"


def traceability_connection_report_path(run_id: str) -> Path:
    """Build the saved traceability connection-map JSON path."""
    return SUBAGENT_DATA_ROOT / run_id / "traceability" / "traceability_agent_connection_map.json"


def corrected_payload_to_dataframe(payload: dict) -> pd.DataFrame:
    """Convert a corrected document JSON payload into a dataframe for display."""
    rows: list[dict] = []
    sheets = payload.get("sheets", []) if isinstance(payload, dict) else []
    if not isinstance(sheets, list):
        return pd.DataFrame()

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue

        sheet_name = str(sheet.get("sheet_name") or "")
        data_rows = sheet.get("data", [])
        if not isinstance(data_rows, list):
            continue

        for index, row in enumerate(data_rows, start=1):
            if not isinstance(row, dict):
                continue

            normalized_row = {
                "sheet_name": sheet_name,
                "row_no": index,
            }
            normalized_row.update(
                {
                    str(key): json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                }
            )
            rows.append(normalized_row)

    return pd.DataFrame(rows)


def get_applied_changes(payload: dict, document_key: str) -> list[dict]:
    """Extract applied correction metadata for one document."""
    metadata = payload.get("correction_metadata", {}) if isinstance(payload, dict) else {}
    applied_changes = metadata.get("applied_changes", []) if isinstance(metadata, dict) else []
    if not isinstance(applied_changes, list):
        return []

    return [
        change
        for change in applied_changes
        if isinstance(change, dict) and str(change.get("document_key") or "") == document_key
    ]


def applied_changes_to_dataframe(applied_changes: list[dict]) -> pd.DataFrame:
    """Convert applied correction metadata into a compact dataframe."""
    rows: list[dict] = []
    for change in applied_changes:
        rows.append(
            {
                "row_index": change.get("row_index"),
                "display_row_no": excel_row_to_display_row(change.get("row_index")),
                "column": change.get("column"),
                "before": stringify_cell_value(change.get("before")),
                "after": stringify_cell_value(change.get("after")),
                "reason": change.get("reason"),
            }
        )
    return pd.DataFrame(rows)


def excel_row_to_display_row(row_index: object) -> int | None:
    """Map original Excel row numbers to the dataframe row_no used by parsed sheets."""
    if not isinstance(row_index, int):
        return None
    return max(row_index - 3, 1)


def stringify_cell_value(value: object) -> object:
    """Return readable cell values for dataframe display."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def build_changed_cell_map(applied_changes: list[dict]) -> tuple[dict[int, set[str]], set[int]]:
    """Build row/column lookup data for styling corrected cells."""
    changed_cells: dict[int, set[str]] = {}
    changed_rows: set[int] = set()

    for change in applied_changes:
        display_row_no = excel_row_to_display_row(change.get("row_index"))
        if display_row_no is None:
            continue

        column = str(change.get("column") or "")
        if column == "*":
            changed_rows.add(display_row_no)
            continue

        changed_cells.setdefault(display_row_no, set()).add(column)

    return changed_cells, changed_rows


def style_corrected_cells(dataframe: pd.DataFrame, applied_changes: list[dict]):
    """Color corrected cells in red based on applied_changes metadata."""
    changed_cells, changed_rows = build_changed_cell_map(applied_changes)

    def style_row(row: pd.Series) -> list[str]:
        row_no = row.get("row_no")
        if not isinstance(row_no, int):
            return ["" for _ in row.index]

        row_changed_columns = changed_cells.get(row_no, set())
        whole_row_changed = row_no in changed_rows
        styles: list[str] = []
        for column_name in row.index:
            if column_name in {"sheet_name", "row_no"}:
                styles.append("")
            elif whole_row_changed or str(column_name) in row_changed_columns:
                styles.append("color: #d32f2f; font-weight: 700;")
            else:
                styles.append("")
        return styles

    return dataframe.style.apply(style_row, axis=1)


def load_current_results() -> dict:
    """Load the latest integrated review result for the current Streamlit session."""
    if not st.session_state.get("has_run", False):
        return {}

    orchestrator_response = st.session_state.get("orchestrator_response", {})
    if isinstance(orchestrator_response, dict) and orchestrator_response:
        return orchestrator_response

    last_run = st.session_state.get("last_run", {})
    run_id = last_run.get("run_id", "") if isinstance(last_run, dict) else ""
    if run_id:
        run_report = load_json_dict(SUBAGENT_DATA_ROOT / run_id / "final_report.json")
        if run_report:
            return run_report

    return {}


def parse_run_folder_name(folder_name: str) -> datetime | None:
    """Parse a run folder name in YYYYMMDD_HHMMSS format."""
    try:
        return datetime.strptime(folder_name, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


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


def get_latest_saved_score() -> tuple[int | None, datetime | None]:
    """Read the most recent final report score from the saved subagent runs."""
    for run_folder in list_saved_run_folders():
        run_at = parse_run_folder_name(run_folder.name)
        final_report = load_json_dict(run_folder / "final_report.json")
        if not final_report:
            continue

        overall_score = final_report.get("overall_score")
        if isinstance(overall_score, (int, float)):
            return int(overall_score), run_at

        return calculate_overall_score(final_report), run_at

    return None, None


def count_recent_run_requests(days: int = 7) -> int:
    """Count saved run folders created within the recent N days, including today."""
    if days <= 0 or not SUBAGENT_DATA_ROOT.exists():
        return 0

    today = date.today()
    start_date = today - timedelta(days=days - 1)
    count = 0

    for run_folder in list_saved_run_folders():
        run_at = parse_run_folder_name(run_folder.name)
        if run_at is None:
            continue

        if start_date <= run_at.date() <= today:
            count += 1

    return count


def clamp_stream_progress(value: object) -> float:
    """Normalize a progress-like value to the 0.0~1.0 range."""
    try:
        progress = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(progress, 1.0))


def get_agent_stream_state() -> dict:
    """Return the persisted right-panel Agent progress state."""
    state = st.session_state.get("agent_stream_state")
    if not isinstance(state, dict):
        state = DEFAULT_AGENT_STREAM_STATE.copy()
        state["logs"] = []
        st.session_state.agent_stream_state = state
    return state


def reset_agent_stream_state() -> None:
    """Clear the right-panel Agent progress only when a new run starts."""
    state = DEFAULT_AGENT_STREAM_STATE.copy()
    state["logs"] = []
    st.session_state.agent_stream_state = state


def save_agent_stream_event(event: dict[str, object]) -> dict:
    """Persist one Agent stream event so reruns keep the latest progress visible."""
    state = get_agent_stream_state()
    message = str(event.get("message") or "Agent가 작업을 진행하고 있습니다.")
    kind = str(event.get("kind") or "status")
    previous_progress = clamp_stream_progress(state.get("progress"))
    progress = max(previous_progress, clamp_stream_progress(event.get("progress")))
    logs = state.get("logs", [])
    if not isinstance(logs, list):
        logs = []

    logs.append(message)
    del logs[:-STREAM_LOG_LIMIT]

    state.update(
        {
            "kind": kind,
            "message": message,
            "progress": progress,
            "logs": logs,
        }
    )
    st.session_state.agent_stream_state = state
    return state


def render_agent_stream_state(
    status_placeholder: st.delta_generator.DeltaGenerator,
    progress_bar: st.delta_generator.DeltaGenerator,
    log_placeholder: st.delta_generator.DeltaGenerator,
) -> None:
    """Render the persisted Agent progress state in the right panel."""
    state = get_agent_stream_state()
    message = str(state.get("message") or DEFAULT_AGENT_STREAM_STATE["message"])
    kind = str(state.get("kind") or "status")
    progress = clamp_stream_progress(state.get("progress"))
    logs = state.get("logs", [])
    if not isinstance(logs, list):
        logs = []

    progress_bar.progress(progress, text=message)
    if kind == "success":
        status_placeholder.success(message)
    elif kind == "error":
        status_placeholder.error(message)
    elif kind == "idle":
        status_placeholder.info(message)
    else:
        status_placeholder.info(message)

    if logs:
        log_placeholder.markdown("\n".join(f"- {line}" for line in logs))
    else:
        log_placeholder.caption("아직 실행된 로그가 없습니다.")


def render_completion_dialog() -> None:
    """Show a one-shot Streamlit modal after an integrated check completes."""
    if not st.session_state.get("show_completion_modal", False):
        return

    st.session_state.show_completion_modal = False
    notice = st.session_state.get("post_run_notice", "통합 점검이 완료되었습니다.")
    last_run = st.session_state.get("last_run", {})
    run_id = last_run.get("run_id", "") if isinstance(last_run, dict) else ""

    @st.dialog("통합 점검 완료", width="medium", icon="✔️")
    def _completion_dialog() -> None:
        st.write(notice)
        if run_id:
            st.caption(f"실행 ID: {run_id}")
        if st.button("확인", key="completion_dialog_confirm"):
            st.rerun()

    _completion_dialog()


def build_stream_callback(
    status_placeholder: st.delta_generator.DeltaGenerator,
    progress_bar: st.delta_generator.DeltaGenerator,
    log_placeholder: st.delta_generator.DeltaGenerator,
) -> Callable[[dict[str, object]], None]:
    """Build a UI callback that renders translated Agent events in the right panel."""

    def handle_stream_event(event: dict[str, object]) -> None:
        save_agent_stream_event(event)
        render_agent_stream_state(status_placeholder, progress_bar, log_placeholder)

    return handle_stream_event


def render_main_view() -> None:
    """메인 화면 전체를 순서대로 렌더링합니다."""
    scenario_order = get_scenario_order()  # 통합 실행 시나리오 순서 [basic_quality, traceability, ui_match, coverage]
    results = load_current_results()  # 현재 세션의 최신 통합 점검 결과

    render_sidebar(scenario_order)
    render_header(results, scenario_order)  # 상단 제목과 요약 지표 렌더링
    render_execute_section(scenario_order)  # 통합 점검 실행 영역 렌더링

    if st.session_state.get("has_run", False):
        results = load_current_results()
        render_result_section(results, scenario_order)  # 통합 점검 결과 영역 렌더링


def render_header(results: dict, scenario_order: list[str]) -> None:
    """서비스 제목과 상단 요약 지표를 보여줍니다."""
    latest_score, latest_run_at = get_latest_saved_score()
    fallback_score = calculate_overall_score(results) if results else None
    recent_request_count = count_recent_run_requests(days=7)

    score_value = f"{latest_score} pt" if latest_score is not None else (
        f"{fallback_score} pt" if fallback_score is not None else "미실행"
    )
    score_delta = latest_run_at.strftime("%Y-%m-%d %H:%M:%S") if latest_run_at else None

    st.title("📃 프로젝트 산출물 통합 점검 서비스")
    st.caption("사용자는 산출물을 한 번 업로드하고, 점검 Agent가 각 시나리오를 순차적으로 실행해 품질 이슈와 보완 포인트를 정리합니다.")

    col1, col2, col3 = st.columns(3)

    with col1:
        col1.metric(
            "전체 시나리오",
            f"{len(scenario_order)}개",
            "순차실행",
            border=True,
        )
    with col2:
        col2.metric(
            "최근 점수",
            score_value,
            score_delta,
            border=True,
        )
    with col3:
        col3.metric(
            "최근 7일 요청",
            f"{recent_request_count}건",
            "오늘 포함",
            border=True,
        )


def render_execute_section(scenario_order: list[str]) -> None:
    """파일 업로드와 통합 점검 실행 영역을 그립니다."""
    st.divider()
    st.subheader("통합 점검 실행", divider="gray")
    render_completion_dialog()

    left, right = st.columns([1.35, 1.0])

    with right:
        # 우측은 통합 실행 흐름과 Agent 진행 상황을 안내합니다.
        st.write("🛰 Agent 진행 상황")
        stream_status = st.empty()
        stream_progress = st.progress(0, text=DEFAULT_AGENT_STREAM_STATE["message"])
        stream_log = st.empty()
        render_agent_stream_state(stream_status, stream_progress, stream_log)
        stream_callback = build_stream_callback(stream_status, stream_progress, stream_log)

    with left:
        # 좌측은 사용자가 직접 문서를 올리고 요청을 입력하는 영역입니다.
        requirement_file = st.file_uploader(
            "요구사항 정의서",
            type=["xlsx", "xls"],
            key="requirement_file",
        )
        feature_file = st.file_uploader(
            "기능 정의서",
            type=["xlsx", "xls"],
            key="feature_file",
        )
        ui_file = st.file_uploader(
            "UI 설계서",
            type=["xlsx", "xls"],
            key="ui_file",
        )
        st.text_area("추가 요청", key="extra_request", height=120)

        if st.button("통합 점검 실행", type="primary", use_container_width=True):
            reset_agent_stream_state()
            st.session_state.post_run_notice = ""
            st.session_state.show_completion_modal = False
            st.session_state.run_integrated_check_requested = True
            st.rerun()

        uploaded_documents = {
            "requirement_definition": {
                "label": "요구사항 정의서",
                "file": requirement_file,
            },
            "feature_definition": {
                "label": "기능 정의서",
                "file": feature_file,
            },
            "ui_design": {
                "label": "UI 설계서",
                "file": ui_file,
            },
        }  # 업로드 문서 정보 맵

    result_loading_placeholder = st.empty()
    if st.session_state.get("run_integrated_check_requested", False):
        st.session_state.run_integrated_check_requested = False
        run_integrated_check(
            uploaded_documents,
            scenario_order,
            stream_callback=stream_callback,
            result_loading_placeholder=result_loading_placeholder,
        )  # 통합 점검 실행


def render_result_loading_section() -> None:
    """Show the result section loading state while the integrated result is being prepared."""
    st.divider()
    st.subheader("통합 점검 결과")
    st.markdown(
        """
        <style>
        .integrated-result-loading {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 1rem;
            border: 1px solid rgba(49, 51, 63, 0.2);
            border-radius: 0.5rem;
            background: rgba(240, 242, 246, 0.45);
        }
        .integrated-result-loading__spinner {
            width: 1.25rem;
            height: 1.25rem;
            border: 0.18rem solid rgba(49, 51, 63, 0.18);
            border-top-color: rgb(255, 75, 75);
            border-radius: 50%;
            animation: integrated-result-spin 0.8s linear infinite;
            flex: 0 0 auto;
        }
        @keyframes integrated-result-spin {
            to { transform: rotate(360deg); }
        }
        </style>
        <div class="integrated-result-loading">
            <div class="integrated-result-loading__spinner"></div>
            <div>통합 점검 결과가 로드중입니다. 잠시만 기다려 주세요.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_integrated_check(
    uploaded_documents: dict[str, dict],
    scenario_order: list[str],
    stream_callback: Callable[[dict[str, object]], None] | None = None,
    result_loading_placeholder: st.delta_generator.DeltaGenerator | None = None,
) -> None:
    """업로드 파일을 JSON으로 정리한 뒤 통합 점검 상태를 갱신합니다."""
    uploaded_file_names = [
        document["file"].name for document in uploaded_documents.values() if document["file"] is not None
    ]  # 실제 업로드 파일 이름 목록
    # 업로드 문서 누락 체크
    if len(uploaded_file_names) < 3:
        st.warning("필수 문서를 모두 업로드해야 합니다.")
        return

    result_loading_started = False

    def show_result_loading_if_ready(event: dict[str, object], message: str, kind: str) -> None:
        nonlocal result_loading_started
        if result_loading_started or result_loading_placeholder is None or kind != "success":
            return

        progress = clamp_stream_progress(event.get("progress"))
        report_done_messages = {
            "최종 보고서 작성이 완료되었습니다.",
            "Main Agent가 최종 보고서를 정리했습니다.",
        }
        if progress < 1.0 or message not in report_done_messages:
            return

        result_loading_started = True
        with result_loading_placeholder.container():
            render_result_loading_section()

    def handle_stream_event(event: dict[str, object]) -> None:
        message = str(event.get("message") or "Agent가 작업을 진행하고 있습니다.")
        kind = str(event.get("kind") or "status")

        show_result_loading_if_ready(event, message, kind)
        if stream_callback is not None:
            stream_callback(event)

    # 백엔드 파이프라인 실행
    backend_result = run_backend_pipeline(
        uploaded_documents=uploaded_documents,  # 업로드한 파일 dict
        user_request=st.session_state.extra_request.strip(),  # 추가 요청 사항
        scenario_order=scenario_order,  # 시나리오 순서
        stream_callback=handle_stream_event,
    )

    if stream_callback is not None:
        stream_callback(
            {
                "kind": "success",
                "message": "통합 점검이 완료되었습니다. Agent 실행 결과를 확인할 수 있습니다.",
                "progress": 1.0,
            }
        )

    st.session_state.has_run = True  # 실행 완료 여부 저장
    st.session_state.prepared_payload = backend_result["agent_request"]  # 생성된 JSON payload 저장
    st.session_state.prepared_payload_path = backend_result["agent_request_path"]  # JSON 파일 경로 저장
    st.session_state.orchestrator_response = backend_result["orchestrator_response"]  # Orchestrator 응답 저장
    st.session_state.orchestrator_response_path = backend_result["orchestrator_response_path"]  # 응답 파일 경로 저장
    st.session_state.last_run = {
        "files": uploaded_file_names,  # 최근 업로드 파일 이름
        "request": st.session_state.extra_request.strip(),  # 최근 요청 문구
        "executed_scenarios": list(scenario_order),  # 최근 실행 시나리오 순서
        "completed_count": len(scenario_order),  # 완료한 시나리오 수
        "run_id": backend_result["run_id"],  # 최근 실행 ID
    }

    st.session_state.post_run_notice = "통합 점검이 완료되었습니다. 결과가 갱신되었습니다."
    st.session_state.show_completion_modal = True
    st.rerun()


def render_result_section(results: dict, scenario_order: list[str]) -> None:
    """통합 결과와 시나리오별 상세 결과를 출력합니다."""
    st.divider()
    st.subheader("통합 점검 결과")

    tab_summary, tab_scenarios, tab_basic_quality, tab_traceability, tab_ui_match = st.tabs(
        [
            "통합 요약",
            "시나리오별 결과",
            "기초 품질 점검 교정 결과",
            "문서 연결성 점검 교정 결과",
            "기능-화면일치점검 교정 결과",
        ]
    )

    with tab_summary:
        render_summary_tab(results, scenario_order)

    with tab_scenarios:
        render_scenario_results(results, scenario_order)

    correction_tabs = [tab_basic_quality, tab_traceability, tab_ui_match]
    for tab, (scenario_key, _label, output_prefix) in zip(correction_tabs, CORRECTION_RESULT_TABS):
        with tab:
            render_correction_result_tab(results, scenario_key, output_prefix)


def render_summary_tab(results: dict, scenario_order: list[str]) -> None:
    """통합 요약 탭에서 우선 확인해야 할 시나리오를 보여줍니다."""
    del scenario_order

    final_report = results.get("final_report", results) if isinstance(results, dict) else {}
    if not isinstance(final_report, dict) or not final_report:
        st.info("표시할 통합 요약 결과가 없습니다.")
        return

    summary = str(final_report.get("summary") or "최종 보고서 요약이 없습니다.")
    overall_score = final_report.get("overall_score", 0)
    if not isinstance(overall_score, (int, float)):
        overall_score = 0

    priority_actions = final_report.get("priority_actions", [])
    if not isinstance(priority_actions, list):
        priority_actions = []

    if overall_score >= 85:
        score_status = "양호"
        summary_renderer = st.success
    elif overall_score >= 70:
        score_status = "검토 필요"
        summary_renderer = st.warning
    else:
        score_status = "보완 필요"
        summary_renderer = st.error

    st.markdown("### 통합 점검 요약")
    metric_cols = st.columns([1.0, 1.2])
    with metric_cols[0]:
        st.metric("전체 점수", f"{int(round(overall_score))}점", border=True)
    with metric_cols[1]:
        st.metric("판정", score_status, border=True)

    st.progress(max(0.0, min(float(overall_score) / 100.0, 1.0)))
    summary_renderer(summary)

    render_integrated_summary_sections(final_report)

    st.divider()
    st.markdown("### 우선순위 액션")
    if priority_actions:
        for index, action in enumerate(priority_actions, start=1):
            st.write(f"{index}. {action}")
    else:
        st.info("우선 조치가 필요한 항목이 없습니다.")


def render_integrated_summary_sections(final_report: dict) -> None:
    """Render additional integrated summary sections generated from subagent outputs."""
    st.divider()
    render_verdict_cards(final_report.get("verdict_cards", []))

    summary_cols = st.columns([1.0, 1.0])
    with summary_cols[0]:
        render_summary_item_list("핵심 리스크 TOP 3", final_report.get("top_risks", []), empty_text="핵심 리스크가 없습니다.")
    with summary_cols[1]:
        render_traceability_overview(final_report.get("traceability_overview", {}))

    st.divider()
    render_document_fix_points(final_report.get("document_fix_points", []))

    st.divider()
    render_summary_item_list(
        "업무 영향 기능",
        final_report.get("business_impact_features", []),
        empty_text="업무 영향 기능으로 분류된 항목이 없습니다.",
    )


def render_verdict_cards(cards: object) -> None:
    """Render top verdict cards."""
    st.markdown("### 전체 판정 카드")
    if not isinstance(cards, list) or not cards:
        st.info("전체 판정 카드 데이터가 없습니다.")
        return

    columns = st.columns(min(len(cards), 4))
    for column, card in zip(columns, cards[:4]):
        if not isinstance(card, dict):
            continue
        with column:
            st.metric(
                str(card.get("label") or ""),
                str(card.get("value") or ""),
                str(card.get("detail") or ""),
                border=True,
            )


def render_summary_item_list(title: str, items: object, empty_text: str) -> None:
    """Render a compact ordered list for a summary section."""
    st.markdown(f"### {title}")
    if not isinstance(items, list) or not items:
        st.info(empty_text)
        return

    for index, item in enumerate(items, start=1):
        st.write(f"{index}. {item}")


def render_traceability_overview(overview: object) -> None:
    """Render requirement-feature-UI connection overview."""
    st.markdown("### 연결성 현황")
    if not isinstance(overview, dict) or not overview:
        st.info("연결성 현황 데이터가 없습니다.")
        return

    metric_cols = st.columns(2)
    with metric_cols[0]:
        st.metric("요구사항 -> 기능", f"{overview.get('requirement_to_feature_coverage_rate', 0)}%", border=True)
        st.metric("연결 보완", f"{overview.get('traceability_changes_count', 0)}건", border=True)
    with metric_cols[1]:
        st.metric("기능 -> UI", f"{overview.get('feature_to_ui_coverage_rate', 0)}%", border=True)
        st.metric("정의되지 않은 ID", f"{overview.get('orphan_reference_count', 0)}건", border=True)


def render_document_fix_points(document_fix_points: object) -> None:
    """Render grouped document-level fix points."""
    st.markdown("### 문서별 수정 포인트")
    if not isinstance(document_fix_points, list) or not document_fix_points:
        st.info("문서별 수정 포인트가 없습니다.")
        return

    tabs = st.tabs([
        str(item.get("document_label") or "문서")
        for item in document_fix_points
        if isinstance(item, dict)
    ])
    for tab, item in zip(tabs, document_fix_points):
        if not isinstance(item, dict):
            continue
        points = item.get("points", [])
        with tab:
            if isinstance(points, list) and points:
                for index, point in enumerate(points, start=1):
                    st.write(f"{index}. {point}")
            else:
                st.info("수정 포인트가 없습니다.")


def render_scenario_results(results: dict, scenario_order: list[str]) -> None:
    """시나리오별 결과 탭에서 각 시나리오의 상세 결과를 보여줍니다."""
    final_report = results.get("final_report", results) if isinstance(results, dict) else {}
    scenario_results = final_report.get("scenario_results", []) if isinstance(final_report, dict) else []
    report_order = final_report.get("scenario_order") or scenario_order
    blocked_scenarios = set(final_report.get("blocked_scenarios", []))
    overall_score = final_report.get("overall_score", 0)
    summary = final_report.get("summary", "최종 보고서 요약이 없습니다.")
    priority_actions = final_report.get("priority_actions", [])
    scenario_labels = {
        "basic_quality": "기초 품질 점검",
        "traceability": "문서 연결성 점검",
        "ui_match": "기능-화면 일치 점검",
        "coverage": "기능 완전성 분석",
    }

    if not scenario_results:
        st.info("표시할 최종 보고서의 시나리오 결과가 없습니다.")
        st.json(final_report)
        return

    st.markdown("### 최종 보고서")
    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric("전체 점수", f"{overall_score}점", border=True)
    with metric_cols[1]:
        st.metric("보완 필요", f"{len(blocked_scenarios)}개", border=True)
    with metric_cols[2]:
        st.metric("점검 시나리오", f"{len(scenario_results)}개", border=True)

    if overall_score <= 75:
        st.error(f"기준 미달: 전체 점수가 {overall_score}점으로 기준 75점 이하입니다.")
    st.success(summary)

    st.divider()
    st.markdown("### 시나리오별 상세 결과")

    results_by_key = {
        scenario.get("scenario_key"): scenario
        for scenario in scenario_results
        if isinstance(scenario, dict)
    }
    ordered_keys = [key for key in report_order if key in results_by_key]
    ordered_keys.extend(
        scenario.get("scenario_key")
        for scenario in scenario_results
        if isinstance(scenario, dict) and scenario.get("scenario_key") not in ordered_keys
    )

    for scenario_key in ordered_keys:
        scenario = results_by_key.get(scenario_key)
        if not scenario:
            continue

        label = scenario_labels.get(scenario_key, scenario.get("scenario_label") or get_result_view_label(scenario_key))
        status = scenario.get("status", "상태 없음")
        score = scenario.get("score", 0)
        scenario_summary = scenario.get("summary", "요약 정보가 없습니다.")
        findings = scenario.get("findings", []) or []
        warnings = scenario.get("warnings", []) or []
        recommendations = scenario.get("recommendations", []) or []

        if status == "통과":
            status_badge = "[통과]"
        elif status == "검토 권장":
            status_badge = "[검토]"
        else:
            status_badge = "[보완]"

        with st.expander(
            f"{status_badge} {label} · {score}점 · {status}",
            expanded=False,
        ):
            top_cols = st.columns(4)
            with top_cols[0]:
                st.metric("시나리오", label, border=True)
            with top_cols[1]:
                st.metric("점수", f"{score}점", "기준 미달" if score <= 75 else None, border=True)
            with top_cols[2]:
                st.metric("Findings", f"{len(findings)}건", border=True)
            with top_cols[3]:
                st.metric("Warnings", f"{len(warnings)}건", border=True)

            if score <= 75:
                st.error(f"기준 미달: {label} 점수가 {score}점으로 기준 75점 이하입니다.")
            st.write(scenario_summary)

            detail_tabs = st.tabs(["오류/이슈", "경고", "개선 권고"])

            with detail_tabs[0]:
                if findings:
                    for finding in findings:
                        st.write(f"- {finding}")
                else:
                    st.success("주요 이슈가 없습니다.")

            with detail_tabs[1]:
                if warnings:
                    for warning in warnings:
                        st.write(f"- {warning}")
                else:
                    st.info("경고가 없습니다.")

            with detail_tabs[2]:
                if recommendations:
                    for recommendation in recommendations:
                        st.write(f"- {recommendation}")
                else:
                    st.info("개선 권고가 없습니다.")


def render_correction_result_tab(results: dict, scenario_key: str, output_prefix: str) -> None:
    """Render corrected document outputs for one scenario."""
    run_id = get_result_run_id(results)
    if not run_id:
        st.info("교정 결과를 조회할 실행 ID가 없습니다.")
        return

    if scenario_key == "traceability":
        render_traceability_connection_result(run_id)
        return

    document_tabs = st.tabs([label for _document_key, label in CORRECTION_DOCUMENTS])
    for document_tab, (document_key, document_label) in zip(document_tabs, CORRECTION_DOCUMENTS):
        with document_tab:
            render_corrected_document_dataframe(
                run_id=run_id,
                scenario_key=scenario_key,
                output_prefix=output_prefix,
                document_key=document_key,
                document_label=document_label,
            )


def render_traceability_connection_result(run_id: str) -> None:
    """Render traceability-specific connection status instead of generic cell corrections."""
    file_path = traceability_connection_report_path(run_id)
    payload = load_json_dict(file_path)
    if not payload:
        st.info("문서 연결성 점검 전용 연결 리포트가 아직 없습니다. 통합 점검을 다시 실행하면 생성됩니다.")
        st.caption(str(file_path))
        return

    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    st.markdown("### 문서 연결성 점검 교정 결과")
    st.caption("요구사항 정의서, 기능 정의서, UI 설계서의 ID가 요구사항 -> 기능 -> UI 순서로 이어지는지 확인합니다.")

    metric_cols = st.columns(4)
    with metric_cols[0]:
        st.metric("요구사항 -> 기능", f"{summary.get('requirement_to_feature_coverage_rate', 0)}%", border=True)
    with metric_cols[1]:
        st.metric("기능 누락", f"{summary.get('missing_requirement_to_feature_count', 0)}건", border=True)
    with metric_cols[2]:
        st.metric("기능 -> UI", f"{summary.get('feature_to_ui_coverage_rate', 0)}%", border=True)
    with metric_cols[3]:
        st.metric("UI 누락", f"{summary.get('missing_feature_to_ui_count', 0)}건", border=True)

    connection_tabs = st.tabs(["요구사항 -> 기능", "기능 -> UI", "정의되지 않은 ID", "연결 보완 내역"])

    with connection_tabs[0]:
        render_requirement_feature_links(payload)

    with connection_tabs[1]:
        render_feature_ui_links(payload)

    with connection_tabs[2]:
        render_orphan_traceability_references(payload)

    with connection_tabs[3]:
        render_traceability_changes(payload)

    st.caption(str(file_path))


def render_requirement_feature_links(payload: dict) -> None:
    """Render requirement-to-feature link coverage."""
    dataframe = requirement_feature_links_to_dataframe(payload.get("requirement_to_feature", []))
    if dataframe.empty:
        st.info("요구사항 -> 기능 연결 데이터를 찾을 수 없습니다.")
        return

    missing_count = int((dataframe["연결 상태"] == "기능 누락").sum()) if "연결 상태" in dataframe else 0
    if missing_count:
        st.warning(f"기능 정의서로 연결되지 않은 요구사항이 {missing_count}건 있습니다.")
    else:
        st.success("모든 요구사항이 기능 정의서와 연결되어 있습니다.")

    st.dataframe(style_traceability_status(dataframe), width="stretch", height=420, hide_index=True)


def render_feature_ui_links(payload: dict) -> None:
    """Render feature-to-UI link coverage."""
    dataframe = feature_ui_links_to_dataframe(payload.get("feature_to_ui", []))
    if dataframe.empty:
        st.info("기능 -> UI 연결 데이터를 찾을 수 없습니다.")
        return

    missing_count = int((dataframe["연결 상태"] == "UI 누락").sum()) if "연결 상태" in dataframe else 0
    if missing_count:
        st.warning(f"UI 설계서로 연결되지 않은 기능이 {missing_count}건 있습니다.")
    else:
        st.success("모든 기능이 UI 설계서와 연결되어 있습니다.")

    st.dataframe(style_traceability_status(dataframe), width="stretch", height=420, hide_index=True)


def render_orphan_traceability_references(payload: dict) -> None:
    """Render undefined or orphan ID references."""
    orphan_references = payload.get("orphan_references", {})
    if not isinstance(orphan_references, dict):
        orphan_references = {}

    labels = {
        "feature_requirement_ids_not_in_requirements": "기능 정의서가 참조하지만 요구사항 정의서에 없는 요구사항 ID",
        "ui_requirement_ids_not_in_requirements": "UI 설계서가 참조하지만 요구사항 정의서에 없는 요구사항 ID",
        "ui_feature_ids_not_in_features": "UI 설계서가 참조하지만 기능 정의서에 없는 기능ID",
        "ui_screen_ids_not_in_features": "UI 설계서에만 존재하는 화면ID",
    }
    rows: list[dict] = []
    for key, label in labels.items():
        values = orphan_references.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            rows.append({"구분": label, "ID": value})

    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        st.success("정의되지 않은 ID 참조나 고아 ID 후보가 없습니다.")
        return

    st.warning(f"정의되지 않은 ID 참조 또는 고아 ID 후보가 {len(dataframe)}건 있습니다.")
    st.dataframe(dataframe, width="stretch", height=300, hide_index=True)


def render_traceability_changes(payload: dict) -> None:
    """Render rows added by the traceability correction step."""
    changes = payload.get("traceability_changes", [])
    dataframe = traceability_changes_to_dataframe(changes)
    if dataframe.empty:
        st.info("문서 연결성 점검에서 자동으로 추가한 연결 보완 후보가 없습니다.")
        return

    st.success(f"연결 보완 후보 {len(dataframe)}건을 생성했습니다.")
    st.dataframe(dataframe, width="stretch", height=360, hide_index=True)


def requirement_feature_links_to_dataframe(records: object) -> pd.DataFrame:
    """Convert requirement-to-feature links into user-facing columns."""
    rows: list[dict] = []
    if not isinstance(records, list):
        return pd.DataFrame()
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.append({
            "연결 상태": record.get("status_label"),
            "요구사항 ID": record.get("requirement_id"),
            "요구사항명": record.get("requirement_name"),
            "연결 기능 수": record.get("feature_count"),
            "기능ID": join_display_values(record.get("feature_ids")),
            "기능명": join_display_values(record.get("feature_names")),
            "화면ID": join_display_values(record.get("screen_ids")),
            "조치": record.get("action"),
        })
    return pd.DataFrame(rows)


def feature_ui_links_to_dataframe(records: object) -> pd.DataFrame:
    """Convert feature-to-UI links into user-facing columns."""
    rows: list[dict] = []
    if not isinstance(records, list):
        return pd.DataFrame()
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.append({
            "연결 상태": record.get("status_label"),
            "요구사항 ID": record.get("requirement_id"),
            "기능ID": record.get("feature_id"),
            "기능명": record.get("feature_name"),
            "기능 화면ID": record.get("screen_id"),
            "UI 매칭 수": record.get("ui_match_count"),
            "UI 화면ID": join_display_values(record.get("ui_screen_ids")),
            "UI 화면명": join_display_values(record.get("ui_names")),
            "조치": record.get("action"),
        })
    return pd.DataFrame(rows)


def traceability_changes_to_dataframe(changes: object) -> pd.DataFrame:
    """Convert traceability candidate additions into readable rows."""
    rows: list[dict] = []
    if not isinstance(changes, list):
        return pd.DataFrame()
    for change in changes:
        if not isinstance(change, dict):
            continue
        after = change.get("after", {})
        rows.append({
            "산출물": change.get("document_label"),
            "변경 유형": change.get("change_type"),
            "추가 행": change.get("row_index"),
            "요구사항 ID": find_value_by_keyword(after, ["요구사항 id", "요구사항id"]),
            "기능ID": find_value_by_keyword(after, ["기능id", "기능 id"]),
            "화면ID": find_value_by_keyword(after, ["화면id", "화면 id"]),
            "명칭": find_value_by_keyword(after, ["기능명", "화면명", "요구사항명"]),
            "비고": find_value_by_keyword(after, ["비고", "note"]),
        })
    return pd.DataFrame(rows)


def style_traceability_status(dataframe: pd.DataFrame):
    """Color missing traceability rows so they stand out."""
    def style_row(row: pd.Series) -> list[str]:
        status = str(row.get("연결 상태") or "")
        color = ""
        if "누락" in status:
            color = "color: #d32f2f; font-weight: 700;"
        elif "보완" in status:
            color = "color: #b45309; font-weight: 700;"
        elif "연결됨" in status:
            color = "color: #1b5e20; font-weight: 600;"
        return [color if column_name == "연결 상태" else "" for column_name in row.index]

    return dataframe.style.apply(style_row, axis=1)


def join_display_values(values: object) -> str:
    """Join list values into a compact display string."""
    if isinstance(values, list):
        return ", ".join(str(value) for value in values if str(value).strip())
    return str(values or "")


def find_value_by_keyword(row: object, keywords: list[str]) -> str:
    """Find a value from a dict by fuzzy column-name keywords."""
    if not isinstance(row, dict):
        return ""
    normalized_keywords = [normalize_display_text(keyword) for keyword in keywords]
    for key, value in row.items():
        normalized_key = normalize_display_text(key)
        if any(keyword in normalized_key for keyword in normalized_keywords):
            return stringify_cell_value(value) or ""
    return ""


def normalize_display_text(value: object) -> str:
    """Normalize display text for lightweight fuzzy matching."""
    return str(value or "").replace(" ", "").replace("_", "").lower()


def render_corrected_document_dataframe(
    run_id: str,
    scenario_key: str,
    output_prefix: str,
    document_key: str,
    document_label: str,
) -> None:
    """Load one corrected document JSON and display its rows with st.dataframe."""
    file_path = corrected_document_path(run_id, scenario_key, output_prefix, document_key)
    payload = load_json_dict(file_path)
    if not payload:
        st.info(f"{document_label} 교정 결과 파일이 없습니다.")
        st.caption(str(file_path))
        return

    dataframe = corrected_payload_to_dataframe(payload)
    if dataframe.empty:
        st.info(f"{document_label} 교정 결과에 표시할 행 데이터가 없습니다.")
        st.caption(str(file_path))
        return

    metadata = payload.get("correction_metadata", {})
    applied_changes = get_applied_changes(payload, document_key)
    remaining_warnings = metadata.get("remaining_warnings", []) if isinstance(metadata, dict) else []

    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric("행 수", f"{len(dataframe)}건", border=True)
    with metric_cols[1]:
        st.metric("적용 변경", f"{len(applied_changes) if isinstance(applied_changes, list) else 0}건", border=True)
    with metric_cols[2]:
        st.metric("잔여 경고", f"{len(remaining_warnings) if isinstance(remaining_warnings, list) else 0}건", border=True)

    st.dataframe(
        style_corrected_cells(dataframe, applied_changes),
        width="stretch",
        height=420,
        hide_index=True,
    )

    if applied_changes:
        with st.expander("교정 변경 내역", expanded=False):
            st.dataframe(
                applied_changes_to_dataframe(applied_changes),
                width="stretch",
                height=240,
                hide_index=True,
            )
    st.caption(str(file_path))


def calculate_overall_score(results: dict) -> int:
    """전체 시나리오 점수 평균을 정수로 계산합니다."""
    if not isinstance(results, dict) or not results:
        return 0

    final_report = results.get("final_report", results)
    if isinstance(final_report, dict):
        overall_score = final_report.get("overall_score")
        if isinstance(overall_score, int):
            return overall_score

        scenario_results = final_report.get("scenario_results", [])
        if isinstance(scenario_results, list):
            scores = [
                scenario.get("score")
                for scenario in scenario_results
                if isinstance(scenario, dict) and isinstance(scenario.get("score"), (int, float))
            ]
            if scores:
                return round(sum(scores) / len(scores))

    scores = [
        result.get("score")
        for result in results.values()
        if isinstance(result, dict) and isinstance(result.get("score"), (int, float))
    ]
    return round(sum(scores) / len(scores)) if scores else 0
