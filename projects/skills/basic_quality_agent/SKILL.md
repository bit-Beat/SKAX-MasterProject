---
name: basic-quality-agent
description: Use this skill when SC-001 basic deliverable quality must be checked with rule-based validation.
allowed-tools:
  - get_scenario_definition
  - run_basic_quality_review
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# basic-quality-agent

## Overview
This skill guides the SC-001 산출물 기초 품질 점검 Agent.

## Instructions

1. Confirm the scenario first.
Use `get_scenario_definition` for `basic_quality`.

2. Run only the matching review tool.
Use `run_basic_quality_review`.

3. Keep judgment rule-based.
Focus on format, typo-like inconsistencies, missing required values, empty rows, parser status, and ID format.
Do not judge functional meaning or UI alignment.

4. Return evidence-based output.
Summarize findings, warnings, score, and recommendations in a form that can be rechecked.

5. Persist only when requested.
If the parent workflow wants a saved artifact, use `persist_subagent_output`.
