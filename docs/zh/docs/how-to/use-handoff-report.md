---
title: 使用 Handoff Report
description: 打开 Server 报告，选择 Workstream，检查 Handoff history，保存 Revision，并导出 Markdown。
---

# 使用 Handoff Report

Handoff Report 在 Server 托管的网页中展示 committed Handoff Revision 和工作 activity。使用该页面可以检查已注册
Workstream 的当前工作、保存完整 Handoff snapshot，或导出所选报告周期。

## 开始之前

启动 Server：

```bash
powercontext server run
```

Handoff Report 默认启用，地址是 `http://127.0.0.1:8000/handoff-reports`。它使用 Server 的 listener 和鉴权设置，
但不要求启用统计 Dashboard 或配置其 scope list。启用 Bearer 鉴权后，在页面登录表单中输入配置的 token。

页面需要一个 active Report Project，并且其中至少注册了一个 Workstream。没有这些数据时，页面会显示无数据模板预览，
并禁用搜索、周期筛选、编辑和下载。

## 1. 按需创建 Report catalog

网页只读取 catalog，不负责创建。使用 Python Client 或 HTTP API 创建 Project，并把一个现有 `scope_id` 注册为
Workstream：

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
                default_locale="zh-CN",
                timezone="Asia/Shanghai",
            )
        )
        workstream = await client.register_handoff_report_workstream(
            RegisterHandoffReportWorkstreamRequest(
                project_id=project.project_id,
                scope_id="project:powercontext",
                title="文档重构",
                kind="feature",
            )
        )
        print(project.project_id, workstream.scope_id)


asyncio.run(main())
```

调用成功后重新加载页面，Project 和 Workstream 应出现在选择器中。注册操作只把现有 scope 纳入报告分组，不会移动或
改写该 scope 的 Memory、Handoff 数据。

## 2. 选择 Project 和 Workstream

可以按 Project title、ID 或 key 搜索。选择 Project 后，页面加载对应 Workstream。通过横向切换区选择一个 Workstream；
Project 包含超过 8 个 Workstream 时，页面还会提供 Workstream 搜索框。

报告显示当前 objective、state、disposition、next action 和 known omissions，并按最新优先展示 Handoff history。JSON
projection 最多包含最近 20 个 Revision 摘要，并标明更早的 history 是否被截断。

页面每 5 秒自动刷新。存在未保存编辑或正在执行 Handoff action 时，自动刷新会暂停。

## 3. 保存新的 Handoff Revision

选择 **编辑**，将五个 current snapshot 字段作为一份完整文档修改，再选择 **保存新版本**。Server 会 prepare 并
commit 完整内容，创建新的不可变 Handoff Revision。

保存属于写操作。编辑器打开时，Project 和 Workstream 切换保持暂停。页面不记录接收方是否接受；Acknowledgement 和
Task Outcome 只作为只读记录显示在 activity timeline 中。

## 4. 按周期检查 activity

选择本日、ISO 本周、自然月或自定义日期范围。自定义结束日期包含所选当天。每次请求都会与之前相同长度的周期比较。

周期筛选会精确作用于 Activity。Handoff boundary coverage 不可用时，snapshot 表示当前精确 Handoff selection，
不是根据周期结束时间重建的历史状态。

## 5. 下载 Markdown

选择 **下载 Markdown**，导出相同 Project、Workstream、locale 和 period。浏览器直接向 Server 请求 Markdown，
不会根据已渲染页面重新拼接。下载默认启用 evidence check，文件名为 `handoff-report.md`。

## 关闭 Handoff Report

重启 Server 前设置功能开关：

```bash
export POWERCONTEXT_SERVER_HANDOFF_REPORT_ENABLED=false
powercontext server run
```

关闭后不会注册 `/handoff-reports` 和 Report API route。Dashboard、HTTP API、MCP、Memory 和 Handoff operation
仍可独立配置。

底层 catalog 和 Report operation 见[接口](../reference/interfaces.md)，精确 Server 设置见
[配置](../reference/configuration.md)。
