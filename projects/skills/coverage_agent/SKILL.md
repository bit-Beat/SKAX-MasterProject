---
name: coverage-agent
description: Use this skill when SC-004 requirement coverage must be reviewed against feature definitions.
allowed-tools:
  - get_scenario_definition
  - run_coverage_review
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# coverage-agent

## Overview
This skill guides the SC-004 요구사항 커버리지 검토 Agent.

## Instructions

1. Confirm the scenario first.
Use `get_scenario_definition` for `coverage`.

2. Run only the matching review tool.
Use `run_coverage_review`.

3. Focus on coverage gaps.
Find missing requirement mappings, under-specified feature decomposition, and possible over/under scope.

4. Avoid implementation guesses.
Analyze only within the requirement-to-feature mapping evidence.

5. Persist only when requested.
If the parent workflow wants a saved artifact, use `persist_subagent_output`.
