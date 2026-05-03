"""중앙 메인 화면을 구성하는 파일."""

import time
import streamlit as st

import json
from pathlib import Path


from main import run_backend_pipeline
from ui.service_data import (
    INTEGRATED_SERVICE,
    get_all_required_files,
    get_all_sample_results,
    get_result_view_label,
    get_sample_result,
    get_scenario_config,
    get_scenario_order,
)

def render_main_view() -> None:
    """메인 화면 전체를 순서대로 렌더링합니다."""
    scenario_order = get_scenario_order()  # 통합 실행 시나리오 순서 [basic_quality, traceability, ui_match, coverage]
    results = get_all_sample_results()  # 샘플 시나리오 결과

    render_header(results, scenario_order) # 상단 제목과 요약 지표 렌더링
    render_execute_section(scenario_order) # 통합 점검 실행 영역 렌더링

    results_path = Path(__file__).resolve().parents[1] / "data" / "subagents" / "final_report.json"
    with results_path.open("r", encoding="utf-8") as f:
        report = json.load(f)
    results = report
    render_result_section(results, scenario_order) # 통합 점검 결과 영역 렌더링


def render_header(results: dict, scenario_order: list[str]) -> None:
    """서비스 제목과 상단 요약 지표를 보여줍니다."""
    overall_score = calculate_overall_score(results)  # 전체 평균 점수
    uploaded_count = len(st.session_state.last_run["files"])  # 최근 업로드 문서 수
    required_count = len(get_all_required_files())  # 전체 필수 문서 수
    score_delta = overall_score - 75  # 임시 기준점 대비 변화량

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
            f"{overall_score}점",
            f"{score_delta:+d}",
            border=True,
        )
    with col3:
        col3.metric(
            "최근 업로드 문서",
            f"{uploaded_count}건",
            f"필수 {required_count}종",
            border=True,
        )

def render_execute_section(scenario_order: list[str]) -> None:
    """파일 업로드와 통합 점검 실행 영역을 그립니다."""
    st.divider()
    st.subheader("통합 점검 실행")

    left, right = st.columns([1.35, 1.0])

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
            run_integrated_check(uploaded_documents, scenario_order) ## 통합 점검 실행

    with right:
        # 우측은 통합 실행 흐름과 필요한 입력 정보를 안내합니다.
        st.info(INTEGRATED_SERVICE["description"])

        st.write("❕ 필수 문서")
        for item in get_all_required_files():
            st.write(f"- {item}")

        st.divider()
        st.write("⏸ 실행 순서")
        for step, scenario_key in enumerate(scenario_order, start=1):
            scenario = get_scenario_config(scenario_key)  # 현재 단계 시나리오 정보
            st.write(f"{step}. {scenario['label']}")
            st.caption(scenario["description"])


def run_integrated_check(uploaded_documents: dict[str, dict], scenario_order: list[str],) -> None:
    """업로드 파일을 JSON으로 정리한 뒤 통합 점검 상태를 갱신합니다."""
    uploaded_file_names = [
        document["file"].name for document in uploaded_documents.values() if document["file"] is not None
    ]  # 실제 업로드 파일 이름 목록
    ## 업로드 문서 누락 체크
    if len(uploaded_file_names) < 3 :
        st.warning("필수 문서를 모두 업로드해야 합니다.")
        return

    total_steps = len(scenario_order) + 2  # JSON 생성 + Orchestrator 준비 + 시나리오 수(4)
    status_text = st.empty()  # 단계 상태 메시지 영역
    progress_bar = st.progress(0, text="통합 점검 준비 중입니다.")  # 실행 진행률 표시

    status_text.info(f"1/{total_steps} 단계 실행 중: 업로드 문서 JSON 생성")

    # 백엔드 파이프라인 실행
    backend_result = run_backend_pipeline(
        uploaded_documents=uploaded_documents, # 업로드한 파일 dict
        user_request=st.session_state.extra_request.strip(), # 추가 요청 사항
        scenario_order=scenario_order, # 시나리오 순서
    )  

    progress_bar.progress(
        1 / total_steps,
        text="업로드 문서 JSON 생성 완료",
    )

    status_text.info(f"2/{total_steps} 단계 실행 중: Orchestrator 요청 준비")
    time.sleep(0.2)
    progress_bar.progress(
        2 / total_steps,
        text="Orchestrator 요청 준비 완료",
    )

    for index, scenario_key in enumerate(scenario_order, start=3):
        scenario = get_scenario_config(scenario_key)  # 현재 실행 시나리오 정보
        status_text.info(f"{index}/{total_steps} 단계 실행 중: {scenario['label']}")
        time.sleep(0.25)  # 현재는 샘플 UI 이므로 짧은 대기만 둡니다.
        progress_bar.progress(
            index / total_steps,
            text=f"{scenario['label']} 완료",
        )

    status_text.success("문서 JSON 생성과 Orchestrator 준비를 마치고, 모든 시나리오 반영을 완료했습니다.")

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

    st.success("통합 점검 결과를 갱신했습니다.")


def render_result_section(results: dict, scenario_order: list[str]) -> None:
    """통합 결과와 시나리오별 상세 결과를 출력합니다."""
    st.divider()
    st.subheader("통합 점검 결과")
    
    tab_summary, tab_scenarios = st.tabs(
        ["통합 요약", "시나리오별 결과"]
    )

    with tab_summary:
        render_summary_tab(results, scenario_order)

    with tab_scenarios:
        render_scenario_results(results, scenario_order)


def render_summary_tab(results: dict, scenario_order: list[str]) -> None:
    """통합 요약 탭에서 우선 확인해야 할 시나리오를 보여줍니다."""


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

    if priority_actions:
        st.markdown("#### 우선순위 액션")
        for index, action in enumerate(priority_actions, start=1):
            st.write(f"{index}. {action}")

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




def calculate_overall_score(results: dict) -> int:
    """전체 시나리오 점수 평균을 정수로 계산합니다."""
    
    total_score = sum(result["score"] for result in results.values())  # 전체 점수 합계
    return round(total_score / len(results))





