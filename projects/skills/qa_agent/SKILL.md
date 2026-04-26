---
name: qa-agent
description: Use this skill when a subagent must identify clarification questions, parsing risks, or ambiguous document structure before or during a review.
allowed-tools:
  - get_document_catalog
  - get_document_preview
  - get_scenario_definition
  - persist_subagent_output
metadata:
  author: skax-master-project
  version: "0.1"
---

# qa-agent

## Overview
This skill helps the QA Agent identify what should be clarified with the user or analyst.

## Instructions

1. Check parser status and row counts first.
Use `get_document_catalog`.

2. Inspect sample rows only when needed.
Use `get_document_preview` for column ambiguity or sparse rows.

3. Ask concrete questions.
Avoid generic uncertainty.
Each question should point to one missing or unclear area.

4. Keep the result concise.
Return the minimum set of questions needed to unblock review quality.
