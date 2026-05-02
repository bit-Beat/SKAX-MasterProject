---
name: ui-match-agent
description: Use this skill when SC-003 feature-to-screen consistency must be reviewed from actual feature and UI documents.
allowed-tools:
  - get_scenario_definition
  - run_ui_match_review
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# ui-match-agent

## Overview
This skill guides the SC-003 기능-화면 심층 검토 Agent.

## Instructions

1. Confirm the scenario first.
Use `get_scenario_definition` for `ui_match`.

2. Run only the matching review tool.
Use `run_ui_match_review`.

3. Compare from the user's flow perspective.
Review feature-to-screen links, screen IDs, feature names, UI wording, and missing interaction risks.

4. Stay evidence-based.
Do not invent behavior that is not present in the uploaded documents or tool output.

5. Persist only when requested.
If the parent workflow wants a saved artifact, use `persist_subagent_output`.
