"""사이드바 필터 영역을 구성하는 파일."""

import streamlit as st

from ui.service_data import (
    INTEGRATED_SERVICE,
    get_all_required_files,
    get_result_view_label,
    get_result_view_options,
    get_scenario_config,
    get_scenario_order,
)


def render_side_filter() -> None:
    """사이드바에서 결과 보기 방식과 실행 순서를 안내합니다."""
    result_view_options = get_result_view_options()  # 결과 상세 보기 옵션 목록
    current_view = st.session_state.result_view_key  # 현재 선택된 결과 보기 키
    current_index = result_view_options.index(current_view)  # selectbox 기본 선택 위치

    with st.sidebar:
        st.title("산출물 점검 Agent")
        st.caption("업로드 문서를 먼저 JSON으로 정리한 뒤, 모든 시나리오를 순차적으로 점검합니다.")

        st.selectbox(
            "결과 상세 보기",
            result_view_options,
            index=current_index,
            format_func=get_result_view_label,
            key="result_view_key",
        )

        st.radio(
            "결과 보기 기준",
            ["전체 보기", "치명 이슈 우선", "개선 제안 우선"],
            key="focus_mode",
        )

        st.toggle("샘플 결과 사용", key="demo_mode")  # 추후 실제 분석 모드와 분리하기 위한 토글

        st.divider()

        st.subheader("실행 방식")
        st.write(INTEGRATED_SERVICE["label"])
        st.caption(INTEGRATED_SERVICE["description"])

        st.caption("실행 순서")
        for step, scenario_key in enumerate(get_scenario_order(), start=1):
            scenario = get_scenario_config(scenario_key)  # 현재 단계 시나리오 정보
            st.write(f"{step}. {scenario['label']}")

        st.caption("필수 문서")
        for file_name in get_all_required_files():
            st.write(f"- {file_name}")
