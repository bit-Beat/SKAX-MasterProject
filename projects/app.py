import streamlit as st

from ui.init_stat import init_session_state
from ui.main_view import render_main_view
from ui.side_filter import render_side_filter


st.set_page_config(
    page_title="SKAX 산출물 통합 점검 Agent",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    init_session_state()
    render_side_filter()
    render_main_view()


if __name__ == "__main__":
    main()
