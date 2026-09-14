# LogAn 使用教程

LogAn 是一个面向故障（incident）的日志分析工具。你为一次故障建一个 case，上传日志，跑一次分析，
然后在结构化日志、时间线、因果候选和摘要之间来回验证。AI 是可选的：不配置 provider 时整条流水线
照常运行，只是没有模型标注、生成式摘要和对话。

本教程分两部分：第 1 章是 10 分钟上手的 Quick Start；第 2 章起逐页、逐字段说明每一项设置。

> 📷 **截图占位**：本教程里所有需要截图的位置都用这样的引用块标出，标题即建议的截图内容。
> 正文里的界面文字（按钮、字段名）与页面上的英文一致，便于对照。

---

## 1. Quick Start

目标：从零启动 LogAn，接入一个 AI provider，跑完第一次分析并提一个问题。

### 1.1 准备

- Python 3.11 或更高，Node.js 22 或更高。
- 一个可用的 AI 账号（二选一）：GitHub Copilot 订阅，或者公司 AI Platform 的 iB2B 账号。
- 本地开发不需要 SSO；不配置 SSO 时系统用一个内置的本地用户登录。

### 1.2 启动

Windows 上一条命令完成建虚拟环境、装依赖、复制 `.env`、跑数据库迁移、启动 API 和网页：

```bat
scripts\local.bat
```

其他平台手动启动（两个终端）：

```bash
cp .env.example .env
python -m venv .venv
python -m pip install -e ".[dev]"
npm ci
python -m alembic -c apps/api/alembic.ini upgrade head
```

```bash
python -m uvicorn app.main:app --reload --env-file .env --app-dir apps/api --host 127.0.0.1 --port 8000
```

```bash
npm run dev --workspace @logan/web
```

打开 `http://localhost:3000`。

> 📷 **截图占位**：登录页，显示 "Continue to LogAn" 卡片和 **Continue** 按钮。

### 1.3 登录

点 **Continue**。开发模式下会直接以本地用户 `local@logan.invalid` 登录，进入 Cases 页面。

### 1.4 接入一个 AI provider

左侧导航点 **AI Providers**。

以 GitHub Copilot 为例：

1. 点 **Add GitHub Copilot**，Name 保持默认或改成自己认得的名字，点 **Create provider**。
2. 新卡片上点 **Connect GitHub**。对话框会显示一个一次性验证码，点 **Open GitHub** 打开 GitHub 页面，输入验证码并确认。
3. 回到 LogAn，对话框自动变为已连接，卡片显示 **Ready** 和 "GitHub account &lt;你的账号&gt;"。
4. 点 **Test connection**，看到绿色提示即可。

> 📷 **截图占位**：Connect GitHub Copilot 对话框，显示一次性验证码和倒计时。

> 📷 **截图占位**：连接成功后的 provider 卡片，带 **Ready** 徽章和 Test connection 的成功提示。

AI Platform 的接入见 4.2 节，需要管理员先在 `.env` 里配好网关地址。

### 1.5 创建 case 并分析

1. 左侧点 **New Case**，填 Title（必填）。
2. 把日志文件拖进上传区，或点 **Choose files** 选择。支持 `.log .txt .json .jsonl .zip .gz .tar .tgz`。
3. 在 **AI provider / Model / Thinking** 三个下拉框里确认选择（默认已选中第一个可用的 provider）。
4. 点 **Create, upload, and analyze files**。

> 📷 **截图占位**：New Case 表单，上传区已选中文件，下方三个下拉框显示 provider、模型和 thinking。

页面跳到 case 工作区，右侧 **Analysis Progress** 面板逐步显示 Ingest → Merge → … → Summary，
最后状态变为 `completed`。

### 1.6 查看报告

顶部导航切换 **Summary / Timeline / Logs / Graph / RCA**。先看 RCA（Causal Summary），
再用 Evidence 里的引用跳到 Logs 核对原始行。

> 📷 **截图占位**：Causal Summary 页面。

### 1.7 提问

回到 **Workspace**，在 **Analysis Chat** 卡片里选 provider、模型和 thinking（默认沿用刚才分析用的），
输入问题或点一个快捷提问，例如 "What is the most likely root cause?"。回答下方的引用可以点击查看证据。

> 📷 **截图占位**：Analysis Chat 卡片，一问一答，回答带 Evidence references。

到这里 Quick Start 结束。下面是每一项的详细说明。

---

## 2. 安装与配置

### 2.1 三种运行方式

| 方式 | 命令 | 说明 |
| --- | --- | --- |
| Windows 启动脚本 | `scripts\local.bat` | 自动完成依赖、`.env`、迁移和启动。可加 `-ApiOnly`、`-WebOnly`、`-SkipInstall`。端口 3000 或 8000 被占用时会拒绝启动 |
| 手动 | 见 1.2 | API 在 8000，网页在 3000 |
| Docker | `docker compose up --build` | 读取同一份 `.env`，数据库和上传文件放在 `logan-data` 卷里 |

API 启动前会自动执行数据库迁移；Docker 镜像也是先迁移再启动 Uvicorn。

### 2.2 `.env` 配置项

最小配置复制 `.env.example`，完整配置复制 `.env.full.example`。API 通过 `--env-file .env` 读取；
网页只在构建时读取 `NEXT_PUBLIC_API_BASE_URL`。

#### 运行时

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LOGAN_ENV` | `development` | `production` 时启用安全 cookie、要求完整 SSO 和至少 32 位的密钥 |
| `LOGAN_SECRET_KEY` | `change-me` | 会话签名密钥。生产必须换成唯一值 |
| `LOGAN_DATABASE_PATH` | `.logan/logan.db` | SQLite 文件路径，目录不存在时自动创建 |
| `LOGAN_LOCAL_OBJECT_STORE_DIR` | `.logan/object-store` | 上传文件和分析产物的根目录 |
| `LOGAN_MAX_UPLOAD_BYTES` | `314572800`（300 MiB） | 单个文件上限，也是压缩包解压后的上限 |
| `LOGAN_WEB_BASE_URL` | `http://localhost:3000` | 登录完成后跳回的网页地址，必须是浏览器实际访问的地址 |
| `LOGAN_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | 允许调用 API 的网页来源，逗号分隔 |
| `LOGAN_LOG_LEVEL` | `INFO` | 进程日志级别 |

#### SSO

| 配置项 | 说明 |
| --- | --- |
| `LOGAN_SSO_AUTHORIZE_URL` | 留空则开发模式用本地用户登录；填了就必须同时填下面两项 |
| `LOGAN_SSO_TOKEN_URL` | OAuth token 端点 |
| `LOGAN_SSO_CLIENT_ID` | OAuth 客户端 id |
| `LOGAN_SSO_AUTHORIZE_SCOPE` / `LOGAN_SSO_TOKEN_SCOPE` | 默认 `openid profile email` |
| `LOGAN_SSO_TLS_VERIFY` | 默认 `true`，生产不允许关闭 |
| `LOGAN_SSO_TIMEOUT_SECONDS` | 默认 `15` |

SSO 回调地址是 API 的 `/api/auth/sso/callback`，需要在 SSO 应用里登记。

#### AI Platform（部署级）

AI Platform 的网关地址属于部署，用户在界面里只填自己的账号。**没有配好前三项，界面上无法创建
AI Platform provider**，Add 对话框会提示缺少哪些配置。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LOGAN_AI_PLATFORM_CHAT_HOST` | 空 | 补全网关的地址，如 `https://ai.example.com` |
| `LOGAN_AI_PLATFORM_CHAT_URI` | `/v1/api/v1/chat/completions` | 补全路径 |
| `LOGAN_AI_PLATFORM_IB2B_HOST` | 空 | iB2B 换 token 的地址 |
| `LOGAN_AI_PLATFORM_IB2B_URI` | `/dsp/rest-sts/DSP_iB2B/iB2B_tokenTranslator_v2?_action=translate` | 换 token 路径 |
| `LOGAN_AI_PLATFORM_TRUST_TOKEN_HEADER` | `X-XXXX-E2E-Trust-Token` | 携带 JWT 的请求头名 |
| `LOGAN_AI_PLATFORM_TRACKING_PREFIX` | `EFP` | 请求追踪 id 前缀 |
| `LOGAN_AI_PLATFORM_MAX_COMPLETION_TOKENS` | `4096` | 单次回答上限 |
| `LOGAN_AI_PLATFORM_STORE_COMPLETIONS` | `false` | 是否让网关保存对话并附带 metadata |
| `LOGAN_AI_PLATFORM_TOKEN_TTL_SECONDS` | `30` | 换来的 JWT 缓存多久 |
| `LOGAN_AI_PLATFORM_TIMEOUT_SECONDS` | `120` | HTTP 超时 |
| `LOGAN_AI_PLATFORM_CA_BUNDLE` | 空 | 内网证书链时指向公司 CA 文件 |
| `LOGAN_AI_PLATFORM_TLS_VERIFY` | `true` | 生产不允许关闭 |
| `LOGAN_AI_PLATFORM_PROXY_URL` | 空 | 显式代理 |
| `LOGAN_AI_PLATFORM_TRUST_ENV` | `true` | 是否遵循进程的 `HTTP(S)_PROXY` 环境变量 |

#### GitHub Copilot（部署级传输设置）

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LOGAN_GITHUB_COPILOT_TIMEOUT_SECONDS` | `120` | 对 github.com 和 Copilot API 的超时 |
| `LOGAN_GITHUB_COPILOT_CA_BUNDLE` | 空 | 公司 CA 文件 |
| `LOGAN_GITHUB_COPILOT_TLS_VERIFY` | `true` | 生产不允许关闭 |
| `LOGAN_GITHUB_COPILOT_PROXY_URL` | 空 | 显式代理 |
| `LOGAN_GITHUB_COPILOT_TRUST_ENV` | `true` | 是否遵循 `HTTP(S)_PROXY` |

API 需要能访问 `github.com`（设备码授权）、`api.github.com`（换 Copilot token）和
`api.githubcopilot.com` 或换 token 时返回的实际 Copilot 地址。

#### 网页

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | 浏览器直接请求的 API 地址；构建期读取，改了要重新构建网页 |

### 2.3 生产环境要求

- 全站 HTTPS（网页、API、SSO、AI 网关）。
- 唯一的 `LOGAN_SECRET_KEY`，至少 32 位。
- 完整的 SSO 三项配置。
- 所有 `*_TLS_VERIFY` 保持 `true`。
- `LOGAN_CORS_ALLOWED_ORIGINS` 只填部署后的网页地址。
- 数据库文件和上传目录限制访问权限。provider 的凭据（AI Platform 密码、GitHub token）按原样存在数据库里，
  数据库文件就是安全边界。
- 每个实例只跑一个 API 进程，分析任务在进程内执行。

---

## 3. 登录与导航

### 3.1 登录页

| 元素 | 说明 |
| --- | --- |
| **Continue** | 跳到 API 的登录端点。开发模式直接用本地用户建会话；配置了 SSO 则跳到 SSO 登录页 |

登录后 API 发一个 HTTP-only 的会话 cookie，7 天有效。

> 📷 **截图占位**：登录页。

### 3.2 左侧导航

| 项 | 去向 |
| --- | --- |
| **New Case** | 新建 case 表单 |
| **All Cases** | case 列表，带筛选 |
| **AI Providers** | 你自己的 AI provider 管理页 |
| **Cases** 分组 | 最近 30 个 case 的快捷入口，圆点颜色对应状态 |
| 底部头像区 | 当前用户；右侧图标 **Sign out** 注销 |

左上角箭头可以把侧栏折叠成图标。

> 📷 **截图占位**：展开的侧栏。

### 3.3 All Cases 列表

| 元素 | 说明 |
| --- | --- |
| **Status** 筛选 | Created / Uploading / Analyzing / Completed / Failed / Cancelled |
| **Product** 筛选 | 按 case 的 Product 字段精确过滤 |
| 列表列 | Status、Product、Service、Incident start |

只看得到自己创建的 case。

---

## 4. AI Providers

每个用户维护自己的 provider，别人看不到也用不了。一个 provider 记录三样东西：凭据、它提供哪些模型、
默认模型和默认 thinking。

> 📷 **截图占位**：AI Providers 页面空状态，顶部两个按钮 **Add AI Platform** 和 **Add GitHub Copilot**。

### 4.1 页面结构

| 元素 | 说明 |
| --- | --- |
| **Add AI Platform** | 打开新建对话框，类型预选 AI Platform |
| **Add GitHub Copilot** | 打开新建对话框，类型预选 GitHub Copilot |
| 蓝色提示条 | 只在部署没配 AI Platform 网关地址时出现，说明缺哪些 `.env` 项 |
| provider 卡片 | 每个 provider 一张，见 4.5 |
| **How providers are used** | 说明 provider 在分析和对话中如何被使用 |

### 4.2 添加 AI Platform

点 **Add AI Platform**，对话框字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| Provider type | 是 | AI Platform / GitHub Copilot 切换；创建后不能改 |
| **Name** | 是 | 显示名，同一用户下不能重名，最长 80 字符 |
| **Username** | 是 | iB2B 用户名 |
| **Password** | 是 | iB2B 密码。每次调用前先用它换一个短期 JWT，JWT 只在内存里缓存 |
| **Usercase** | 是 | iB2B usercase，同时作为请求里的 `user` 字段 |
| **Models** | 是 | 见 4.4 |
| **Default model** | 是 | 见 4.4 |
| **Default thinking level** | 是 | 见 4.4 |

Username、Password、Usercase 三者要么都填要么都不填，只填一部分会被拒绝。
编辑时 Password 留空表示不改；占位文字显示 "Unchanged"。

> 📷 **截图占位**：Add AI provider 对话框，AI Platform 类型，Credentials 三个字段。

### 4.3 添加 GitHub Copilot 并授权

1. 点 **Add GitHub Copilot**，填 Name，其余按需调整，点 **Create provider**。此时卡片显示 **Not connected**。
2. 卡片上点 **Connect GitHub**。

对话框流程：

| 阶段 | 显示 | 你要做的 |
| --- | --- | --- |
| Contacting GitHub… | 正在向 github.com 申请设备码 | 等待一两秒 |
| 显示验证码 | 一个 `XXXX-XXXX` 格式的一次性码、**Copy code**、**Open GitHub**、倒计时 "code valid for m:ss" | 点 **Open GitHub**（新标签页），输入验证码并确认授权 |
| 授权成功 | 绿色提示 "GitHub Copilot is connected as &lt;账号&gt;" | 点 **Done** |
| 失败 | 红色提示和 **Try again** | 常见原因见第 10 章 |

授权走的是 GitHub 官方设备码流程，用的是 Copilot 插件的客户端 id。LogAn 服务端拿到 GitHub token 后
存进数据库，浏览器只看到验证码。企业托管账号可能需要先在 GitHub 标签页里过一遍公司 SSO。

已连接的 provider 卡片按钮变为 **Reconnect GitHub**，token 失效时用它重新授权。

> 📷 **截图占位**：Connect GitHub Copilot 对话框的三个阶段各一张。

### 4.4 模型列表、默认模型、默认 thinking

这三项决定分析和对话时下拉框里能选什么、默认选什么。

**Models**：这个 provider 提供的模型 id 列表。
- 新建时预填该类型的目录清单（见附录 A）。
- 输入框里输入一个 id 回车即可加入自定义模型；点 chip 上的 × 移除。
- **Reset to the catalog list (N models)** 一键恢复成目录清单。目录更新后，已有的 provider 不会自动跟着变，用这个按钮同步。
- id 只允许字母、数字和 `. _ : / -`，最多 32 个。

**Default model**：从 Models 里选一个，作为新分析和对话的预选值。目录默认：AI Platform 是 `gpt-5.4`，
GitHub Copilot 是 `gpt-5.6-terra`。

**Default thinking level**：Low / Medium / High / Extra high / Max，对应 `low / medium / high / xhigh / max`。
默认 High。AI Platform 以 `reasoning_effort` 发送，Copilot 以 `reasoning.effort` 发送。

> 📷 **截图占位**：Models 输入框（多个 chip，默认模型高亮）、Reset 按钮、两个默认值下拉框。

### 4.5 provider 卡片

| 元素 | 说明 |
| --- | --- |
| 徽章 | provider 类型；**Ready** 表示凭据齐全可用，**Not connected** 表示还没有凭据 |
| Credentials | AI Platform 显示 "iB2B credentials for &lt;用户名&gt;"；Copilot 显示 "GitHub account &lt;账号&gt;"；没有凭据显示 "None stored yet" |
| Default model | 默认模型和默认 thinking |
| Models | 全部模型 chip，默认模型实心高亮 |
| **Connect GitHub / Reconnect GitHub** | 仅 Copilot |
| **Test connection** | 用默认模型、Low thinking 发一条极短请求。成功显示绿色提示，失败显示红色提示和原因。凭据未配齐时按钮不可用 |
| **Edit** | 打开编辑对话框，字段同新建；类型不可改 |
| **Delete** | 删除 provider 及其凭据。用过该 provider 的历史分析仍然保留，只是不再关联 |

> 📷 **截图占位**：一张 AI Platform 卡片和一张已连接的 Copilot 卡片。

### 4.6 provider 在哪里被使用

- **发起分析**：New Case 表单和工作区的 Analyze evidence 区都有 provider / Model / Thinking 三个下拉框，
  可以选 **No AI (deterministic pipeline)** 跳过模型。选了 provider 的分析会用它做模板标注和因果摘要。
- **对话**：每次提问都可以重新选。默认沿用该分析用的 provider、模型和 thinking；没有的话选第一个 Ready 的 provider。
- 未连接（Not connected）的 provider 在下拉框里显示但不可选。

---

## 5. 创建 Case

左侧 **New Case**。

> 📷 **截图占位**：New Case 页面整体。

### 5.1 Case details

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| **Title** | 是 | 案件标题 |
| **Issue description** | 否 | 现象描述，会作为上下文的一部分（经脱敏、截断）送给模型 |
| **Product** | 否 | 产品名，可在 All Cases 里按它筛选 |
| **Service** | 否 | 服务名 |
| **Environment** | 否 | 环境，如 prod / staging |
| **Incident start / Incident end** | 否 | 故障时间窗口，按浏览器本地时区输入，保存为 UTC |

### 5.2 上传区

| 元素 | 说明 |
| --- | --- |
| 拖放区 / **Choose files** | 可多选。接受 `.log .txt .json .jsonl .zip .gz .tar .tgz` |
| 已选文件 chip | 文件名和大小 |
| 限制 | 每个文件至少 1 字节，默认最大 300 MiB；压缩包解压后的总量也受同一上限约束 |

上传过程中页面会显示每个文件的准备、上传、校验进度。

### 5.3 AI 选择

| 下拉框 | 说明 |
| --- | --- |
| **AI provider** | **No AI (deterministic pipeline)** 或任一 Ready 的 provider |
| **Model** | 所选 provider 的模型列表 |
| **Thinking** | Low / Medium / High / Extra high / Max |

没有配置任何 provider 时，这里会提示并附带去 AI Providers 页面的链接。

### 5.4 两个提交按钮

| 按钮 | 行为 |
| --- | --- |
| **Create case** | 只保存 case，不上传不分析 |
| **Create, upload, and analyze files** | 创建 case，上传所选文件，按上面的选择发起第一次分析。没选文件时不可用 |

---

## 6. Case 工作区

点侧栏里的 case 或创建后自动进入。布局左宽右窄。

> 📷 **截图占位**：工作区整体。

### 6.1 顶部 Case analysis 导航

有至少一次分析后出现，切换 **Workspace / Summary / Timeline / Logs / Graph / RCA**。报告链接绑定的是
最新一次分析的 id。

### 6.2 Incident Overview 卡片

| 元素 | 说明 |
| --- | --- |
| case key、状态徽章 | case 状态和最新分析状态 |
| 标题、描述、元数据 chip | Product / Service / Environment / Incident start |
| **Open latest report** | 最新分析完成后出现，跳到 Summary |
| **Edit case** | 展开编辑表单 |

### 6.3 Edit Case 表单

字段同 5.1。**Save case** 保存；**Cancel** 收起；**Delete case** 需要确认，删除后 case 不再可见，
已上传的文件不会自动删除。

### 6.4 Analysis Chat 卡片

见第 9 章。

### 6.5 Analyze evidence 卡片

再次上传并发起新的分析。每次都是一个独立的 run，只针对这次新上传的文件。

| 元素 | 说明 |
| --- | --- |
| 上传区 | 同 5.2 |
| 上传进度 | 每个文件一条进度条，显示百分比和字节数 |
| AI 选择 | 同 5.3 |
| **Upload and analyze files** | 没选文件时不可用 |

### 6.6 右侧 Analysis Progress

| 元素 | 说明 |
| --- | --- |
| 标题 | "Run #N - 状态" |
| 指标 | Files / Raw lines / Templates / Windows |
| 步骤列表 | Ingest, Merge, Redact, Template, Sample, Classify, Annotate, Broadcast, Temporal, Graph, Summary；每步显示 pending / processing / completed / failed / skipped |
| Started / Completed | 时间 |
| **Open report** | 完成后出现 |
| **Terminate** | 进行中的分析可终止 |

不选 AI 时 Annotate 一步显示 `skipped`。

> 📷 **截图占位**：分析进行中的进度面板。

### 6.7 Selected evidence

在 Chat 或报告里点一个证据引用后，这里显示它的 Log id、Template、Line、Timestamp，并可跳到 Logs 页。

### 6.8 Case 与 Run 详情

Case 卡片列出状态和全部元数据。Run 卡片列出编号、状态、当前步骤、起止时间和 **AI model** 一行，
格式为 "provider 名 · 模型 · thinking"，不选 AI 时显示 "None (deterministic)"。失败时显示脱敏后的错误。

### 6.9 Analysis Runs 历史

每次分析一项。点击切换右侧详情跟踪的 run；**Summary** 打开该 run 的报告；进行中的可 **Terminate**。

---

## 7. 分析运行

### 7.1 流水线

每次分析按固定顺序执行：

1. `ingest_paths` 读取文件，解开压缩包
2. `merge_entries` 合并多行日志
3. `preprocess_redact` 解析并脱敏（密码、token、密钥等在进入模板和模型之前被掩码）
4. `template_extraction` 提取日志模板
5. `representative_sampling` 每个模板取至多 3 条代表行
6. `heuristic_annotation` 规则分类，保证没有模型也能出结果
7. `ai_platform_annotation` 用所选 provider 标注至多 64 个出现最多的模板（步骤名沿用历史名称，Copilot 同样走这一步）
8. `broadcast_annotations` 把模板标注铺到每一行
9. `temporal_aggregation` 按时间窗聚合
10. `causal_graph` 计算因果候选
11. `causal_summary` 生成摘要；有 provider 时生成文字，模型输出不合法则回退为结构化摘要

之后 `finalizing` 写入产物。模型只收到脱敏后的有限样本和证据包，不会收到原始文件。

### 7.2 状态

case 状态：`created` `uploading` `analyzing` `completed` `failed` `cancelled`。
run 状态：`queued` `processing` `completed` `failed` `cancelled`。

API 重启时进行中的 run 会被标为 `failed` 并附说明，不会一直卡在 processing。

### 7.3 模型调用失败怎么办

单个模板标注失败不会让整次分析失败，该模板退回规则分类结果；摘要生成失败退回结构化摘要。
因此 provider 配置错误时分析仍会 `completed`，只是 Annotate 的效果和 RCA 的文字会缺失。
排查请用 provider 卡片的 **Test connection**。

---

## 8. 报告页面

五个报告页共享顶部的运行版本栏：

| 元素 | 说明 |
| --- | --- |
| **Version** 下拉框 | 在同一 case 的多次分析之间切换 |
| Completed | 完成时间 |
| Model | 该次分析用的 provider、模型和 thinking |

> 📷 **截图占位**：报告页顶部的版本栏。

### 8.1 Summary（Data Summary）

| 元素 | 说明 |
| --- | --- |
| 指标 | Raw lines、Visible templates、Review reduction（相对原始行数需要人工看的条目减少比例） |
| **Scope** | **Attention signals**：只看被标为异常信号（error、availability、latency、saturation、traffic）的模板；**All templates**：全部模板。不选 AI 时请用 All |
| 列表 | 每个模板的代表内容、出现次数、时间范围、服务、分类、严重度、置信度 |

> 📷 **截图占位**：Summary 页面。

### 8.2 Timeline（Temporal View）

| 元素 | 说明 |
| --- | --- |
| **Group by** | Signal / Service / Fault category / Template |
| 堆叠柱图 | 每个时间窗的日志数；窗口大小按故障时长自动选择（10 秒到 15 分钟） |
| 点击柱子 | 在下方加载该时间窗内的日志 |

没有时间戳的行不参与时间线。

> 📷 **截图占位**：Timeline 页面，点开一个时间窗。

### 8.3 Logs（Tabular Logs）

| 元素 | 说明 |
| --- | --- |
| **Search** | 在消息、模板文本和标注出的实体值里搜索，回车执行 |
| 表格 | 脱敏后的消息、文件、行号（多行日志显示多个行号）、模板、信号、分类 |

从其他页面点证据引用会跳到这里，并按该证据所属的模板过滤，方便看同类行。

> 📷 **截图占位**：Logs 页面。

### 8.4 Graph（Causal Graph）

| 元素 | 说明 |
| --- | --- |
| 图 | 节点是模板，节点越大排名越靠前；红圈是根因候选；虚线边表示待验证 |
| 点击节点或边 | 显示该节点或边的详情 |
| 边表 | 全部关联，含置信度、滞后时间、支持窗口数 |

图里的边是时间关联，是验证顺序的建议，不是证明。图为空表示异常事件或关联不够。

> 📷 **截图占位**：Graph 页面。

### 8.5 RCA（Causal Summary）

| 区块 | 说明 |
| --- | --- |
| 内部诊断叙述 | 给工程师看的 |
| 客户可见的更新 | 措辞安全的对外版本 |
| 置信度与不确定性 | |
| **Evidence** | 证据引用，点击查看或跳到 Logs |
| 候选结论 | 每条附理由、引用和置信度，全部标注需要验证 |
| **Next actions** | 建议的验证步骤，含优先级和负责角色 |

不选 AI 或模型输出不合法时，显示结构化的证据摘要而不是生成文字。

> 📷 **截图占位**：RCA 页面。

---

## 9. Analysis Chat

在工作区，case 至少有一次分析后出现，针对最近一次 `completed` 的分析回答。

> 📷 **截图占位**：Chat 卡片空状态，显示四个快捷提问和三个下拉框。

| 元素 | 说明 |
| --- | --- |
| 副标题 | "Answers about run #N" |
| 快捷提问 | Summarize what changed and why it matters / What is the most likely root cause? / Show the strongest evidence / Draft a customer-safe update |
| **AI provider / Model / Thinking** | 每次提问前可改。默认是这次分析用的选择；分析没用 AI 时默认第一个 Ready 的 provider |
| 输入框 | Enter 发送，Shift+Enter 换行 |
| **Ask / Cancel** | 发送；流式回答期间可取消 |
| 回答下方标签 | "provider 名 · 模型 · thinking"，失败时也会标出用的是哪个 |
| Evidence references | 点击在右侧 Selected evidence 显示详情 |

模型收到的是压缩后的分析上下文：你的问题（最多 1000 字符）、因果摘要（2500 字符）、最多 5 条证据和
最多 5 条严重度最高的模板。对话记录只保留在当前页面，刷新即清空。

---

## 10. 常见问题

**Add AI Platform 提示 endpoints are not configured。**
管理员在 `.env` 设置 `LOGAN_AI_PLATFORM_CHAT_HOST`、`LOGAN_AI_PLATFORM_IB2B_HOST`、`LOGAN_AI_PLATFORM_IB2B_URI` 后重启 API。

**Test connection 报 iB2B token exchange failed。**
用户名、密码或 usercase 不对，或 API 到 iB2B 地址不通。内网证书问题设置 `LOGAN_AI_PLATFORM_CA_BUNDLE`。

**Connect GitHub 的验证码过期。**
验证码约 15 分钟有效，点 **Try again** 重新申请。企业账号先在 GitHub 标签页完成公司 SSO 再输验证码。

**Copilot 报 401 或提示 reconnect GitHub。**
GitHub 授权已失效，卡片上点 **Reconnect GitHub**。

**Copilot 报 model is not available / not supported。**
该模型对你的订阅不可用，或目录里的 id 与 Copilot 实际不一致。在 provider 的 **Edit** 里改成正确的 id 或换一个默认模型。

**分析完成了但 Annotate 效果像没用 AI，RCA 没有生成文字。**
模型调用失败会静默回退（见 7.3）。先 **Test connection**，再检查 `.env` 的代理和证书设置。

**上传返回 500，日志里是 "No such file or directory"。**
旧版本在 Windows 上路径超过 260 字符时会这样，当前版本已处理。若仍出现，把 `LOGAN_LOCAL_OBJECT_STORE_DIR` 改到更浅的目录。

**浏览器报 CORS 或 401。**
用 `http://localhost:3000` 访问，并保持 `LOGAN_WEB_BASE_URL`、`LOGAN_CORS_ALLOWED_ORIGINS`、`NEXT_PUBLIC_API_BASE_URL` 与实际地址一致。

**SSO 登录后跳错地址。**
`LOGAN_WEB_BASE_URL` 必须是浏览器看到的网页地址。

**文件上传被拒。**
每个文件至少 1 字节，默认最大 300 MiB，压缩包解压后总量同样受限。调整 `LOGAN_MAX_UPLOAD_BYTES`。

---

## 附录 A：目录里的模型

**AI Platform**：`gpt-5.4`（默认）、`gpt-5.6-luna`、`gpt-5.6-sol`、`gpt-5.6-terra`。

**GitHub Copilot**（与 Copilot 模型选择器一致，默认 `gpt-5.6-terra`）：

| 显示名 | id |
| --- | --- |
| Sonnet 4 / Haiku 4.5 | `claude-sonnet-4` / `claude-haiku-4.5` |
| Fable 5 / Fable 5.1 | `claude-fable-5` / `claude-fable-5.1` |
| Opus 4.7 / 4.8 / 5 | `claude-opus-4.7` / `claude-opus-4.8` / `claude-opus-5` |
| Sonnet 5 | `claude-sonnet-5` |
| Gemini 3.7 Flash / 3.8 Flash | `gemini-3.7-flash` / `gemini-3.8-flash` |
| GPT-5.4 / GPT-5.4 mini / GPT-5 mini | `gpt-5.4` / `gpt-5.4-mini` / `gpt-5-mini` |
| GPT-5.6 Luna / Sol / Terra | `gpt-5.6-luna` / `gpt-5.6-sol` / `gpt-5.6-terra` |
| GPT-6 Astra | `gpt-6-astra` |
| MAI-Code-1.1-Flash | `mai-code-1.1-flash` |

id 不对时在 provider 的模型列表里改即可，不需要改代码。

## 附录 B：Thinking 等级

| 界面 | 值 |
| --- | --- |
| Low | `low` |
| Medium | `medium` |
| High | `high`（默认） |
| Extra high | `xhigh` |
| Max | `max` |

## 附录 C：相关 API

界面用到的接口都在 `/api` 下，完整清单见 [API](api.md)，交互式文档在 API 的 `/docs`。
provider 相关：`/api/llm-providers`、`/api/llm-providers/catalog`、`/api/llm-providers/{id}/test`、
`/api/llm-providers/{id}/github-device/start` 和 `/check`。发起分析和对话分别是
`POST /api/cases/{case_id}/analysis-runs` 和 `POST /api/chat/stream`，都接受 `provider_id`、`model`、`reasoning_effort`。
