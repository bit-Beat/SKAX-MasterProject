---
name: traceability-agent
description: Use this skill when SC-002 traceability and structural consistency must be checked through ID-based mappings.
allowed-tools:
  - get_scenario_definition
  - run_traceability_review
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# traceability-agent

## Overview
This skill guides the SC-002 구조 정합성 점검 Agent.

## Instructions

1. Confirm the scenario first.
Use `get_scenario_definition` for `traceability`.

2. Run only the matching review tool.
Use `run_traceability_review`.

3. Prioritize ID connectivity.
Check requirement-to-feature and feature-to-UI mappings, missing IDs, orphaned IDs, and broken links.
Prefer structural evidence over semantic UI interpretation.

4. Avoid abstract quality scoring.
Report concrete mapping gaps and structural inconsistency only.

5. Persist only when requested.
If the parent workflow wants a saved artifact, use `persist_subagent_output`.
