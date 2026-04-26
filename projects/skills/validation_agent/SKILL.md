---
name: validation-agent
description: Use this skill when a subagent must run rule-based validation for basic quality or ID-based traceability checks.
allowed-tools:
  - get_scenario_definition
  - run_basic_quality_review
  - run_traceability_review
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# validation-agent

## Overview
This skill guides the Validation Agent for deterministic checks.

## Instructions

1. Confirm the scenario first.
Use `get_scenario_definition`.

2. Use the matching validation tool.
For `basic_quality`, use `run_basic_quality_review`.
For `traceability`, use `run_traceability_review`.

3. Prefer evidence over speculation.
Return findings that are directly grounded in the tool output.

4. If the workflow requires storage, persist the structured result with `persist_subagent_output`.
