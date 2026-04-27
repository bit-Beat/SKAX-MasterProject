"""Streamlit 세션 상태의 기본값을 관리하는 파일."""

from copy import deepcopy

import streamlit as st

from ui.service_data import DEFAULT_RESULT_VIEW_KEY, get_scenario_order


DEFAULT_SESSION_STATE = {
    "result_view_key": DEFAULT_RESULT_VIEW_KEY,  # 결과 상세 보기 기준
    "focus_mode": "전체 보기",  # 결과를 어떤 기준으로 볼지 정하는 옵션
    #"demo_mode": True,  # 샘플 결과 사용 여부
    "extra_request": "핵심 이슈를 우선순위 기준으로 보여줘.",  # 사용자 추가 요청 문구
    "has_run": False,  # 점검 실행 여부
    
    "prepared_payload": {},  # 업로드 문서를 정리한 JSON payload
    "prepared_payload_path": "",  # JSON payload 저장 경로
    "orchestrator_response": {},  # Orchestrator 응답 JSON
    "orchestrator_response_path": "",  # Orchestrator 응답 저장 경로
    
    "last_run": {  # 최근 실행 정보 묶음
        "files": [],  # 최근 업로드 파일 이름 목록
        "request": "샘플 결과 미리보기",  # 최근 요청 문구
        "executed_scenarios": get_scenario_order(),  # 최근 실행 시나리오 순서
        "completed_count": 0,  # 최근 완료한 시나리오 수
        "run_id": "",  # 최근 실행 ID
    },
}


def init_session_state() -> None:
    """세션에 없는 상태값만 기본값으로 채웁니다."""
    for key, value in DEFAULT_SESSION_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(value)  # 가변 객체 공유를 막기 위해 복사본 저장
