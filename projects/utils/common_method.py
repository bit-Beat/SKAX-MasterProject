
""" 공통 함수 """

from pathlib import Path
import json
from typing import Any, Dict

def log(message: str, level: str = "PRINT") -> None:
    """사용자 입력 로그 출력 함수"""
    level = level.upper()

    prefix_map = {
        "INFO": "\n[ℹ️INFO]",
        "WARNING": "\n[⚠️WARNING]",
        "ERROR": "\n[❌ERROR]",
        "DEBUG": "\n[🐛DEBUG]",
        "PRINT": "→"
    }

    prefix = prefix_map.get(level, "")

    print(f"{prefix} {message}")
    if level != "PRINT":
        print("─" * 20)  

def pretty_trace(message):
    """DeepAgents 실행 결과(messages)를 사람이 읽기 쉬운 형태로 정리하여 출력하는 함수."""
    step = 1

    if not isinstance(message, dict):
        WARNING_MESSAGE("Not Dict Type!")
        return 

    if "messages" not in message.keys():
        WARNING_MESSAGE("DeepAgent 메시지 결과 값 전달 바랍니다.")
        return

    messages = message['messages']
    
    for msg in messages:
        msg_type = msg.__class__.__name__

        if msg_type == "HumanMessage":
            log(f"[STEP {step}]🧑 USER INPUT", "info")
            log(f" {msg.content}")
            
        elif msg_type == "AIMessage":
            if msg.tool_calls:
                log(f"[STEP {step}]🤖 AI AGENT", "info")

                for tc in msg.tool_calls:
                    tool_name = tc.get("name")
                    args = tc.get("args", {})

                    if tool_name == "task":
                        subagent = args.get("subagent_type", "UNKNOWN")
                        desc = args.get("description", "")
                        log(f" SubAgent 호출: {subagent}")
                        log(f" Args: {desc}")
                    else:
                        log(f" Tool: {tool_name}")
                        log(f" Args: {args}")
            else:
                log(f"[STEP {step}]🚀 FINAL RESPONSE", "info")
                log(f" {msg.content}")
                

        elif msg_type == "ToolMessage":
            if msg.name == "task":
                log(f"[STEP {step}]🛠 SUBAGENT RESULT", "info")
                log(f" Result: {msg.content}")
            else:
                log(f"[STEP {step}]🛠 TOOL RESULT", "info")
                log(f" Toolname : {msg}")
                log(f" Result: {msg.content}")
        step += 1

def save_json(file_path: Path, payload: Dict[str, Any]) -> None:
    """UTF-8 JSON 파일로 저장합니다."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")