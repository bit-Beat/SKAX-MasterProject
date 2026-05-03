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
        st.title(INTEGRATED_SERVICE["label"])
        st.caption("프로젝트 산출물을 업로드하면 시나리오대 순차적으로 점검합니다.")
