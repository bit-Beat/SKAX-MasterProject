"""중앙 메인 화면을 구성하는 파일."""

import time
import streamlit as st

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

    render_header(results, scenario_order)
    render_execute_section(scenario_order)
    render_result_section(results, scenario_order)


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

    st.write(f"uploaded_documents : {uploaded_documents}" )
    st.write(f"scenario_order : {scenario_order}" )

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

    render_overall_status(results)
    render_overall_metrics(results)
    render_last_run()

    tab_summary, tab_scenarios, tab_payload = st.tabs(
        ["통합 요약", "시나리오별 결과", "백엔드 JSON"]
    )

    with tab_summary:
        render_summary_tab(results, scenario_order)

    with tab_scenarios:
        render_scenario_results(results, scenario_order)

    with tab_payload:
        render_backend_payload_tab()


def render_overall_status(results: dict) -> None:
    """전체 시나리오 상태를 요약해 상단 메시지로 보여줍니다."""
    status = get_overall_status(results)  # 통합 상태 계산
    message = build_overall_summary(results)  # 통합 요약 문장

    if status == "보완 필요":
        st.error(message)
    elif status == "검토 권장":
        st.warning(message)
    else:
        st.success(message)


def render_overall_metrics(results: dict) -> None:
    """전체 시나리오 기준 핵심 수치를 metric 컴포넌트로 보여줍니다."""
    completed_count = st.session_state.last_run["completed_count"]  # 최근 실제 완료 시나리오 수
    total_critical = sum(len(result["critical"]) for result in results.values())  # 전체 치명 이슈 수
    total_warnings = sum(len(result["warnings"]) for result in results.values())  # 전체 경고 수

    columns = st.columns(4)

    with columns[0]:
        st.metric("통합 점수", f"{calculate_overall_score(results)}점")
    with columns[1]:
        st.metric("보완 필요", f"{count_status(results, '보완 필요')}개")
    with columns[2]:
        st.metric("전체 치명 이슈", f"{total_critical}건")
    with columns[3]:
        st.metric("전체 경고", f"{total_warnings}건", f"완료 {completed_count}개")


def render_last_run() -> None:
    """최근 실행 정보를 펼침 영역에 정리해 보여줍니다."""
    files = st.session_state.last_run["files"]  # 최근 업로드 파일 목록
    executed_scenarios = st.session_state.last_run["executed_scenarios"]  # 최근 실행 시나리오 순서
    run_id = st.session_state.last_run["run_id"]  # 최근 실행 ID

    with st.expander("최근 실행 정보", expanded=False):
        st.write(f"실행 ID: {run_id or '-'}")
        st.write(f"완료 시나리오 수: {st.session_state.last_run['completed_count']}개")
        st.write("실행 순서")
        for step, scenario_key in enumerate(executed_scenarios, start=1):
            scenario = get_scenario_config(scenario_key)  # 최근 실행 단계 정보
            st.write(f"{step}. {scenario['label']}")

        if files:
            st.write("업로드 파일")
            for item in files:
                st.write(f"- {item}")
        else:
            st.write("업로드 파일: 샘플 결과 미리보기 상태")

        st.write("요청 내용")
        st.write(st.session_state.last_run["request"])

        if st.session_state.prepared_payload_path:
            st.caption(f"JSON 저장 경로: {st.session_state.prepared_payload_path}")
        if st.session_state.orchestrator_response_path:
            st.caption(f"Orchestrator 응답 경로: {st.session_state.orchestrator_response_path}")


def render_summary_tab(results: dict, scenario_order: list[str]) -> None:
    """통합 요약 탭에서 우선 확인해야 할 시나리오를 보여줍니다."""
    st.write("실행 순서")
    for step, scenario_key in enumerate(scenario_order, start=1):
        scenario = get_scenario_config(scenario_key)  # 현재 단계 시나리오 정보
        result = get_sample_result(scenario_key)  # 현재 단계 결과
        st.write(f"{step}. {scenario['label']} - {result['status']} ({result['score']}점)")

    st.write("우선 확인 대상")
    for scenario_key in sorted(scenario_order, key=lambda key: results[key]["score"]):
        scenario = get_scenario_config(scenario_key)  # 우선순위 시나리오 정보
        result = results[scenario_key]  # 우선순위 시나리오 결과
        st.write(f"- {scenario['label']}: {result['summary']}")


def render_scenario_results(results: dict, scenario_order: list[str]) -> None:
    """선택된 보기 기준에 맞춰 시나리오별 결과를 순차적으로 보여줍니다."""
    result_view_key = st.session_state.result_view_key  # 결과 상세 보기 필터

    if result_view_key == "all":
        target_keys = scenario_order
    else:
        target_keys = [result_view_key]
        st.caption(f"현재 결과 상세 보기: {get_result_view_label(result_view_key)}")

    for step, scenario_key in enumerate(scenario_order, start=1):
        if scenario_key not in target_keys:
            continue
        render_single_scenario_result(step, scenario_key, results[scenario_key])


def render_single_scenario_result(step: int, scenario_key: str, result: dict) -> None:
    """시나리오 하나의 결과를 단계 순서에 맞춰 렌더링합니다."""
    scenario = get_scenario_config(scenario_key)  # 현재 시나리오 정보
    focus_mode = st.session_state.focus_mode  # 결과 보기 기준

    with st.expander(
        f"{step}단계. {scenario['label']} | {result['status']} | {result['score']}점",
        expanded=True,
    ):
        st.caption(scenario["description"])

        metric_items = list(result["metrics"].items())  # 현재 단계 지표 목록
        metric_columns = st.columns(len(metric_items))
        for column, (label, value) in zip(metric_columns, metric_items):
            with column:
                st.metric(label, value)

        if focus_mode in ["전체 보기", "치명 이슈 우선"]:
            st.write("치명 이슈")
            for item in result["critical"]:
                st.error(item)

        if focus_mode == "전체 보기":
            st.write("경고")
            for item in result["warnings"]:
                st.warning(item)

        st.write("개선 제안")
        for item in result["suggestions"]:
            if focus_mode == "치명 이슈 우선":
                st.info(item)
            else:
                st.success(item)


def render_backend_payload_tab() -> None:
    """백엔드에서 생성한 문서 JSON과 Orchestrator 응답을 보여줍니다."""
    if not st.session_state.prepared_payload:
        st.info("아직 생성된 문서 JSON payload가 없습니다.")
        return

    st.write("Agent 요청 JSON")
    st.json(st.session_state.prepared_payload, expanded=False)
    st.caption(f"저장 경로: {st.session_state.prepared_payload_path}")

    if st.session_state.orchestrator_response:
        st.write("Orchestrator 응답")
        st.json(st.session_state.orchestrator_response, expanded=False)
        st.caption(f"응답 경로: {st.session_state.orchestrator_response_path}")

def calculate_overall_score(results: dict) -> int:
    """전체 시나리오 점수 평균을 정수로 계산합니다."""
    total_score = sum(result["score"] for result in results.values())  # 전체 점수 합계
    return round(total_score / len(results))


def count_status(results: dict, status: str) -> int:
    """특정 상태를 가진 시나리오 수를 계산합니다."""
    return sum(1 for result in results.values() if result["status"] == status)


def get_overall_status(results: dict) -> str:
    """전체 결과를 대표하는 상태를 계산합니다."""
    if count_status(results, "보완 필요") > 0:
        return "보완 필요"
    if count_status(results, "검토 권장") > 0:
        return "검토 권장"
    return "정상"


def build_overall_summary(results: dict) -> str:
    """통합 결과 요약 문장을 생성합니다."""
    overall_score = calculate_overall_score(results)  # 전체 평균 점수
    needs_fix = count_status(results, "보완 필요")  # 보완 필요 수
    needs_review = count_status(results, "검토 권장")  # 검토 권장 수
    return (
        f"통합 점수는 {overall_score}점이며, "
        f"보완 필요 {needs_fix}개 시나리오와 검토 권장 {needs_review}개 시나리오가 확인되었습니다."
    )
