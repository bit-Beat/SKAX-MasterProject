### SKAX-MasterProject
🎯 SKAX AI MasterProject : 프로젝트 개발 산출물 점검/개선 Agent

### Version
 - Python Ver.3.11
 - DeepAgents Ver. 
 
### config 파일 설정
 1. config.ini 파일에는 Azure Open AI API 세팅 값들을 입력 **개발을 위해 주어진 API Key로 사용**

### Streamlit 실행
 1. streamlit run app.py


# 디렉토리 구조
/testcodeagent [dir]
 ├ ** app.py **
 ├ README.md
 ├ config.ini
 ├ ui/ [dir]
 │	├ 
 │
 ├ agents/ [dir]
 │	├ orchestrator.py
 │
 ├ data/ [dir]
 │
 ├ skills/ [dir]
 │	├ 
 │
 ├ tools/ [dir]
 ├ db/ [dir]
 ├ utils/ [dir]
 │	├ common_method.py
 │	└ config_loader.py
 
# 파일 설명
[/testcodeagent]
 - app.py : 최종 실행 파일 (사용자의 요청 입력을 orchestrator 에게 전달 후 결과를 출력)
 - config.ini : LLM_MODEL 정보 등 공통 설정값 세팅 파일
 
[/testcodeagent/agents/]
 - orchestratr.py : Main Agent 하위 subagent의 역할을 조정하고 관리하는 에이전트
  
[/testcodeagent/data/]
 - 각 Agent가 생성하는 Data가 있을 경우 해당 경로에 저장 예정(ex. reqdiff_agent가 file 을 생성하면 /testcodeagent/data/reqdiff/code.raw와 같은 파일 생성)
 
[/testcodeagent/skills/]
 
 
[/testcodeagent/tools/]
 - agent가 사용할 tool을 해당 경로에 생성 예정 ※ 해당 폴더에서는 다른 Agent도 같은 툴을 사용할 경우가 있을 수 있으므로, 모든 Agent가 공유할 수 있도록 따로 폴더 생성 필요 없음.

[/testcodeagent/utils/]
 - common_method.py : 모든 파일에서 공통적으로 사용할 수 있는 유틸리티 기능들을 작성
 - config_loader.py : config.ini 파일을 읽어와서 리턴해주는 함수.
 
[/testcodeagent/db/]
 - Agent가 필요한 사전 파일들을 저장할 로컬 저장소 (ex. ppt패치내역, table정의서, 자바소스 등)
 
 