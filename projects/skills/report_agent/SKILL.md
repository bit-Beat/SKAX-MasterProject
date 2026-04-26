---
name: report-agent
description: Use this skill when a subagent must synthesize scenario-level outputs into a single final deliverable inspection report.
allowed-tools:
  - get_document_catalog
  - get_document_preview
  - get_scenario_definition
metadata:
  author: skax-master-project
  version: "0.1"
---

# report-agent

## Overview
This skill helps the Report Agent create the final structured report.

## Instructions

1. Prefer parent-provided scenario outputs.
Use previously delegated results as the main evidence source.

2. Use document tools only when summary context is missing.
Do not re-run the whole analysis unless necessary.

3. Produce a decision-ready report.
Make the overall score, blocked scenarios, and priority actions obvious.

4. Keep the final summary short.
The next action for the user should be easy to spot.
