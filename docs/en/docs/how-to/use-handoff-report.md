---
title: Use Handoff Report
description: Open the Server report, select a scope, inspect Handoff history, save a Revision, and export Markdown.
---

# Use Handoff Report

Handoff Report presents committed Handoff Revisions and work activity in a Server-owned web page. Use it to inspect
current work by scope, save a complete Handoff snapshot, or export the selected report period.

## Before you start

Start the Server:

```bash
powercontext server run
```

Handoff Report is enabled by default at `http://127.0.0.1:8000/handoff-reports`. It uses the Server listener and
authentication settings, but does not require the statistics Dashboard or its scope list. If bearer authentication is
enabled, enter the configured token in the page sign-in form.

The page discovers scopes that contain at least one committed Handoff. Without one, it shows a data-free template
preview and disables search, period filters, editing, and download.

## 1. Commit a Handoff in the target scope

Create a durable Handoff milestone in the scope you want to report. In Codex, follow
[Hand off work in Codex](handoff-with-codex.md) and keep the exact scope and Handoff Revision from the result.

Reload Handoff Report after the commit succeeds. The page calls `list_handoff_report_known_scopes` and should include
the scope. Committing a Handoff makes the scope discoverable; no Report Project or Workstream registration is required.

## 2. Select a scope

Search by `scope_id`, then select the scope. The page requests its report with `scope_id` and shows the current
objective, state, disposition, next action, and known omissions.

The report also shows the latest Handoff history, newest first. The JSON projection contains at most the latest 20
Revision summaries and marks when earlier history was truncated. `project_id` remains in the HTTP request only for wire
compatibility; it is deprecated and ignored when the Server generates a scope report.

The page refreshes every five seconds. It pauses while edits are unsaved or a Handoff action is running.

## 3. Save a new Handoff Revision

Select **Edit**, update the five current-snapshot fields as one document, then select **Save Revision**. The Server
prepares and commits the complete document as a new immutable Handoff Revision.

Saving is a write operation. Scope switching stays paused while the editor is open. The page does not record receiver
acceptance; acknowledgements and Task Outcomes remain read-only entries in the activity timeline.

## 4. Inspect activity by period

Choose the current day, ISO week, calendar month, or a custom date range. Custom end dates include the selected day.
The report compares each request with the preceding period of equal length.

Period filters apply precisely to Activity. When Handoff boundary coverage is unavailable, the snapshot is the current
exact Handoff selection, not a reconstructed historical state at the end of that period.

## 5. Download Markdown

Select **Download Markdown** to export the same scope, locale, and period. The browser requests Markdown from the
Server rather than rebuilding it from the rendered page. Downloads enable evidence checks by default and use the
filename `handoff-report.md`.

## Disable Handoff Report

Set the feature flag before restarting the Server:

```bash
export POWERCONTEXT_SERVER_HANDOFF_REPORT_ENABLED=false
powercontext server run
```

Disabling the feature removes `/handoff-reports` and the Report API routes. The Dashboard, HTTP API, MCP, Memory, and
Handoff operations remain independently configured.

For scope discovery and Report operations, see [Interfaces](../reference/interfaces.md). For exact Server settings,
see [Configuration](../reference/configuration.md).
