---
name: improvement-agent
description: Use this skill when a subagent must convert scenario findings and warnings into prioritized, actionable improvement items.
allowed-tools:
  - get_scenario_definition
  - build_improvement_actions
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# improvement-agent

## Overview
This skill helps the Improvement Agent translate review output into next actions.

## Instructions

1. Confirm the scenario context.
Use `get_scenario_definition`.

2. Generate actions from evidence.
Use `build_improvement_actions` with the actual findings and warnings from prior subagent work.

3. Prioritize.
Keep the response centered on what should be fixed first.

4. Avoid repeating the same issue in multiple phrasings.
