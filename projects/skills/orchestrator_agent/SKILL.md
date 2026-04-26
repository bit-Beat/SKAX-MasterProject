---
name: orchestrator-agent
description: Use this skill when the main DeepAgent must coordinate project deliverable inspection scenarios in sequence, delegate detailed work to subagents, and synthesize a final report.
allowed-tools:
  - get_document_catalog
  - get_document_preview
  - get_scenario_definition
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# orchestrator-agent

## Overview
This skill guides the main LangChain DeepAgent that acts as the Orchestrator for deliverable inspection.

## Instructions

1. Start with the current document state.
Use `get_document_catalog` first.
If a document looks ambiguous, use `get_document_preview`.

2. Execute scenarios in sequence.
Follow the scenario order provided in the task.
Do not skip ahead unless the task explicitly allows it.

3. Delegate detailed work to subagents.
Use role-based subagents instead of doing all detailed reasoning in the parent context.
`validation-agent` handles `basic_quality` and `traceability`.
`review-agent` handles `ui_match` and `coverage`.

4. Keep the parent context compact.
Ask subagents for focused results and synthesize only what is needed for the next step.

5. Finish with a final report.
After scenario-level reviews are complete, request a consolidated report and return the final structured response.
