---
name: deep-review-agent
description: Use this skill when a subagent must run deeper analysis for traceability gaps, feature-to-UI consistency, or requirement coverage.
allowed-tools:
  - get_scenario_definition
  - run_ui_match_review
  - run_coverage_review
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# deep-review-agent

## Overview
This skill guides the Review Agent for scenario-specific deeper analysis.

## Instructions

1. Identify the target scenario first.
Use `get_scenario_definition`.

2. Use the matching review tool.
For `ui_match`, use `run_ui_match_review`.
For `coverage`, use `run_coverage_review`.

3. Explain downstream impact.
Do not stop at mismatch detection.
Include why the issue matters for design, development, or testing.

4. Keep the response compact and evidence-based.
