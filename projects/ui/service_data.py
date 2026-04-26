"""통합 점검 시나리오와 샘플 결과를 관리하는 파일."""

SCENARIO_ORDER = [
    "basic_quality",
    "traceability",
    "ui_match",
    "coverage",
]  # 통합 점검 시나리오 실행 순서

DEFAULT_SCENARIO_KEY = SCENARIO_ORDER[0]  # 기본 시나리오 키
DEFAULT_RESULT_VIEW_KEY = "all"  # 기본 결과 보기 키

INTEGRATED_SERVICE = {
    "label": "프로젝트 산출물 통합 점검",  # 서비스 이름
    "description": "한 번 점검을 실행하면 각 시나리오가 순차적으로 실행됩니다.",  # 서비스 설명
    "outputs": ["통합 점검 점수", "시나리오별 이슈", "개선 가이드", "우선순위 제안"],  # 사용자 제공 결과
}  # 통합 서비스 개요


SCENARIOS = {
    "basic_quality": {  # 1단계 기초 품질 점검
        "label": "기초 품질 점검",  # 이름
        "description": "- 형식 오류, 필수 항목 누락, 용어 불일치를 먼저 점검합니다.",  # 설명
        "required_files": ["요구사항 정의서", "기능 정의서", "UI 설계서"],  # 필수 문서
        "checks": [  # 주요 점검 항목
            "ID 형식 규칙",  # 식별자 규칙 확인
            "필수 항목 누락",  # 비어 있는 필수 값 점검
            "용어 표준화 여부",  # 표준 용어 사용 여부
            "기본 체크리스트 통과 여부",  # 기본 품질 기준 충족 여부
        ],
        "outputs": ["점검 점수", "오류 목록", "수정 가이드"],  # 출력 형식
    },
    "traceability": {  # 2단계 문서 연결성 점검
        "label": "문서 연결성 점검",  # 이름
        "description": "- 요구사항, 기능, UI 문서가 같은 흐름으로 연결되는지 확인합니다.",  # 설명
        "required_files": ["요구사항 정의서", "기능 정의서", "UI 설계서"],  # 필수 문서
        "checks": [  # 주요 점검 항목
            "요구사항-기능 연결",  # 요구사항과 기능 연결 확인
            "기능-UI 연결",  # 기능과 UI 연결 확인
            "미연결 ID 탐지",  # 연결되지 않은 식별자 탐지
            "정의 외 항목 탐지",  # 근거 없는 항목 탐지
        ],
        "outputs": ["정합성 커버리지", "미연결 목록", "보정 우선순위"],  # 출력 형식
    },
    "ui_match": {  # 3단계 기능-화면 일치 점검
        "label": "기능-화면 일치 점검",  # 이름
        "description": "- 문서에 정의된 기능이 화면 설계와 맞물리는지 점검합니다.",  # 설명
        "required_files": ["기능 정의서", "UI 설계서"],  # 필수 문서
        "checks": [  # 주요 점검 항목
            "기능과 버튼 대응",  # 기능과 UI 액션 연결 확인
            "목록/상세 흐름 일치",  # 화면 흐름 일관성 확인
            "누락 화면 요소",  # 빠진 UI 요소 탐지
            "불필요 UI 존재 여부",  # 필요 없는 UI 존재 여부
        ],
        "outputs": ["불일치 항목", "개선 제안", "검증 메모"],  # 출력 형식
    },
    "coverage": {  # 4단계 기능 완전성 분석
        "label": "기능 완전성 분석",  # 이름
        "description": "- 요구사항 대비 기능 정의가 충분한지, 누락과 과잉을 함께 분석합니다.",  # 설명
        "required_files": ["요구사항 정의서", "기능 정의서"],  # 필수 문서
        "checks": [  # 주요 점검 항목
            "기능 누락",  # 빠진 기능 점검
            "과잉 기능",  # 필요 이상 기능 점검
            "세부 기능 분해 적절성",  # 기능 분해 수준 확인
            "추가 정의 필요 영역",  # 보완이 필요한 영역 확인
        ],
        "outputs": ["완전성 점수", "Gap 분석", "보완 제안"],  # 출력 형식
    },
}


SAMPLE_RESULTS = {
    "basic_quality": {  # 1단계 샘플 결과
        "status": "보완 필요",  # 결과 상태
        "score": 65,  # 점검 점수
        "summary": "기초 점검 단계에서 형식과 누락 항목 이슈가 먼저 감지되었습니다.",  # 결과 요약
        "metrics": {  # 상단 지표
            "치명 오류": "2건",  # 심각한 오류 수
            "필수 누락": "4건",  # 필수 항목 누락 수
            "용어 경고": "5건",  # 용어 관련 경고 수
        },
        "critical": [  # 치명 이슈 목록
            "ID 형식 오류 2건이 발견되었습니다. `A01` 형식이 표준 규칙 `A001`과 맞지 않습니다.",
            "필수 항목 4건이 비어 있습니다. 우선순위, 검증 기준, 담당 조직, 완료 조건을 보완해야 합니다.",
        ],
        "warnings": [  # 경고 목록
            "`조회`, `검색`이 혼용되어 용어 표준화가 필요합니다.",
            "표준 템플릿 기준 컬럼 순서가 달라 자동 비교 시 잡음이 생길 수 있습니다.",
        ],
        "suggestions": [  # 개선 제안 목록
            "업로드 직후 기본 품질 체크리스트를 자동 실행하도록 연결합니다.",
            "용어 사전과 필수 항목 검증을 먼저 통과한 뒤 정합성 점검으로 넘기면 효율이 좋아집니다.",
        ],
    },
    "traceability": {  # 2단계 샘플 결과
        "status": "검토 권장",  # 결과 상태
        "score": 78,  # 점검 점수
        "summary": "문서 연결 구조는 대체로 잡혀 있지만 일부 항목은 추적성이 끊겨 있습니다.",  # 결과 요약
        "metrics": {  # 상단 지표
            "미연결 ID": "3건",  # 연결 누락 수
            "과잉 정의": "1건",  # 불필요 정의 수
            "정합성 커버리지": "78%",  # 연결 비율
        },
        "critical": [  # 치명 이슈 목록
            "요구사항 `A001`에 연결된 기능 정의가 존재하지 않습니다.",
            "UI 설계서의 `D00Z`는 연결 근거가 없는 정의 외 항목입니다.",
        ],
        "warnings": [  # 경고 목록
            "`A002-1`은 UI 화면과 연결되지 않아 설계 누락 가능성이 있습니다.",
            "일부 하위 ID는 부모 요구사항과 설명 연결이 약해 추적이 어렵습니다.",
        ],
        "suggestions": [  # 개선 제안 목록
            "요구사항-기능-UI 간 매핑 표를 기본 산출물로 고정하는 편이 좋습니다.",
            "미연결 항목과 과잉 정의 항목을 상단 요약에 따로 노출하면 보정이 빨라집니다.",
        ],
    },
    "ui_match": {  # 3단계 샘플 결과
        "status": "검토 권장",  # 결과 상태
        "score": 82,  # 점검 점수
        "summary": "기능 정의와 UI 흐름은 대부분 맞지만 핵심 액션 일부가 화면에 드러나지 않습니다.",  # 결과 요약
        "metrics": {  # 상단 지표
            "불일치 기능": "2건",  # 불일치 기능 수
            "UI 누락": "1건",  # 누락된 UI 수
            "검증 커버리지": "100%",  # 검증 범위
        },
        "critical": [  # 치명 이슈 목록
            "`A001-1` 조회 기능이 정의되어 있지만 화면에는 실행 버튼이 없습니다.",
            "목록 조회와 상세 조회 흐름이 같은 영역에 섞여 사용 시나리오가 모호합니다.",
        ],
        "warnings": [  # 경고 목록
            "정렬과 필터 기능은 정의서에 있으나 화면 문구에서 확인되지 않습니다.",
            "빈 결과 화면 처리 방식이 설계서에 없어 해석 차이가 생길 수 있습니다.",
        ],
        "suggestions": [  # 개선 제안 목록
            "기능 정의서의 액션 명칭과 UI 버튼 라벨을 1:1로 맞추는 것이 좋습니다.",
            "조회 흐름을 목록, 상세, 조건 필터로 분리해 화면 구조를 다시 정리하면 좋습니다.",
        ],
    },
    "coverage": {  # 4단계 샘플 결과
        "status": "보완 필요",  # 결과 상태
        "score": 68,  # 점검 점수
        "summary": "요구사항 대비 기능 정의 완전성이 부족해 보완 작업이 필요합니다.",  # 결과 요약
        "metrics": {  # 상단 지표
            "누락 기능": "2건",  # 누락된 기능 수
            "과잉 기능": "1건",  # 과잉 기능 수
            "완전성 점수": "68점",  # 완전성 점수
        },
        "critical": [  # 치명 이슈 목록
            "요구사항에 있는 필터 기능이 기능 정의서에서 누락되었습니다.",
            "삭제 기능은 요구사항 근거 없이 포함되어 범위 과잉으로 보입니다.",
        ],
        "warnings": [  # 경고 목록
            "조회 기능이 너무 넓게 묶여 있어 목록 조회와 상세 조회 분리가 필요합니다.",
            "예외 케이스 정의가 부족해 이후 테스트 기준 수립이 어려울 수 있습니다.",
        ],
        "suggestions": [  # 개선 제안 목록
            "요구사항 문장을 기능 목록으로 직접 분해하는 보완 절차를 두는 편이 좋습니다.",
            "누락 기능과 과잉 기능을 분리한 Gap 리포트를 먼저 보여주면 의사결정이 빨라집니다.",
        ],
    },
}


def get_scenario_order() -> list[str]:
    return list(SCENARIO_ORDER)  # 시나리오 실행 순서 목록 반환


def get_scenario_config(scenario_key: str) -> dict:
    return SCENARIOS[scenario_key]  # 선택한 시나리오 설정 반환


def get_sample_result(scenario_key: str) -> dict:
    return SAMPLE_RESULTS[scenario_key]  # 선택한 시나리오 샘플 결과 반환


def get_all_sample_results() -> dict:
    return {key: SAMPLE_RESULTS[key] for key in SCENARIO_ORDER}  # 순서가 보장된 전체 결과 반환


def get_all_required_files() -> list[str]:
    required_files: list[str] = []  # 통합 실행에 필요한 문서 목록
    for scenario_key in SCENARIO_ORDER:
        for file_name in SCENARIOS[scenario_key]["required_files"]:
            if file_name not in required_files:
                required_files.append(file_name)  # 중복 없이 유지
    return required_files


def get_result_view_options() -> list[str]:
    return [DEFAULT_RESULT_VIEW_KEY] + SCENARIO_ORDER  # 전체 보기 포함 결과 필터 목록


def get_result_view_label(view_key: str) -> str:
    if view_key == DEFAULT_RESULT_VIEW_KEY:
        return "전체 시나리오"  # 전체 결과 보기 이름
    return SCENARIOS[view_key]["label"]  # 개별 시나리오 이름
