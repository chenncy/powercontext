---
title: Use Handoff Report
description: Open the Server report, select a Workstream, inspect Handoff history, save a Revision, and export Markdown.
---

# Use Handoff Report

Handoff Report presents committed Handoff Revisions and work activity in a Server-owned web page. Use it to inspect
current work across registered Workstreams, save a complete Handoff snapshot, or export the selected report period.

## Before you start

Start the Server:

```bash
powercontext server run
```

Handoff Report is enabled by default at `http://127.0.0.1:8000/handoff-reports`. It uses the Server listener and
authentication settings, but does not require the statistics Dashboard or its scope list. If bearer authentication is
enabled, enter the configured token in the page sign-in form.

The page needs an active Report Project with at least one registered Workstream. Without one, it shows a data-free
template preview and disables search, period filters, editing, and download.

## 1. Create the Report catalog when needed

The web page reads the catalog but does not create it. Use the Python Client or HTTP API to create a Project and
register an existing `scope_id` as a Workstream:

```python
import asyncio

from powercontext.client import PowerContextClient
from powercontext.http import (
    CreateHandoffReportProjectRequest,
    RegisterHandoffReportWorkstreamRequest,
)


async def main() -> None:
    async with PowerContextClient("http://127.0.0.1:8000") as client:
        project = await client.create_handoff_report_project(
            CreateHandoffReportProjectRequest(
                project_key="powercontext",
                title="PowerContext",
                default_locale="en",
                timezone="UTC",
            )
        )
        workstream = await client.register_handoff_report_workstream(
            RegisterHandoffReportWorkstreamRequest(
                project_id=project.project_id,
                scope_id="project:powercontext",
                title="Documentation restructuring",
                kind="feature",
            )
        )
        print(project.project_id, workstream.scope_id)


asyncio.run(main())
```

Reload the page after the calls succeed. The Project and Workstream should become selectable. Registration groups an
existing scope for reporting; it does not move or rewrite that scope's Memory or Handoff data.

## 2. Select a Project and Workstream

Search for a Project by title, ID, or key. After selection, the page loads its Workstreams. Use the horizontal switcher
to choose one; Projects with more than eight Workstreams also show a Workstream search field.

The report displays the current objective, state, disposition, next action, and known omissions. It also shows the
latest Handoff history, newest first. The JSON projection contains at most the latest 20 Revision summaries and marks
when earlier history was truncated.

The page refreshes every five seconds. It pauses while edits are unsaved or a Handoff action is running.

## 3. Save a new Handoff Revision

Select **Edit**, update the five current-snapshot fields as one document, then select **Save Revision**. The Server
prepares and commits the complete document as a new immutable Handoff Revision.

Saving is a write operation. Project and Workstream switching stays paused while the editor is open. The page does not
record receiver acceptance; acknowledgements and Task Outcomes remain read-only entries in the activity timeline.

## 4. Inspect activity by period

Choose the current day, ISO week, calendar month, or a custom date range. Custom end dates include the selected day.
The report compares each request with the preceding period of equal length.

Period filters apply precisely to Activity. When Handoff boundary coverage is unavailable, the snapshot is the current
exact Handoff selection, not a reconstructed historical state at the end of that period.

## 5. Download Markdown

Select **Download Markdown** to export the same Project, Workstream, locale, and period. The browser requests Markdown
from the Server rather than rebuilding it from the rendered page. Downloads enable evidence checks by default and use
the filename `handoff-report.md`.

## Disable Handoff Report

Set the feature flag before restarting the Server:

```bash
export POWERCONTEXT_SERVER_HANDOFF_REPORT_ENABLED=false
powercontext server run
```

Disabling the feature removes `/handoff-reports` and the Report API routes. The Dashboard, HTTP API, MCP, Memory, and
Handoff operations remain independently configured.

For the underlying catalog and Report operations, see [Interfaces](../reference/interfaces.md). For exact Server
settings, see [Configuration](../reference/configuration.md).
