---
name: guide-agent
description: Use this skill when a subagent needs to explain scenario criteria, required documents, and pre-check readiness before validation starts.
allowed-tools:
  - get_document_catalog
  - get_document_preview
  - get_scenario_definition
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# guide-agent

## Overview
This skill helps the Guide Agent summarize what should be checked before a scenario review begins.

## Instructions

1. Load the scenario definition.
Use `get_scenario_definition` to identify required files and checks.

2. Review current document readiness.
Use `get_document_catalog` and, if needed, `get_document_preview`.

3. Summarize only the essentials.
Return short guidance focused on missing inputs, readiness, and the checklist.

4. Persist only when asked.
If the parent workflow wants a saved artifact, use `persist_subagent_output`.
