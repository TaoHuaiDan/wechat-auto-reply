# Windows 微信本地自动回复系统（第一阶段）

这是一个 Windows 11 上运行的本地常驻 Python 服务。当前阶段只验证最底层链路：

```text
微信新消息
  -> hermes-wxauto bridge-server
  -> 本项目 HTTP bridge client
  -> ack
  -> 本项目 SQLite 事务保存
  -> complete
```

本阶段不会调用 Qwen，不会调用 bridge 的 `/send`，也不会自动发送任何微信消息。

## 已核对的 hermes-wxauto 接口

实现依据是 `doingSthing/hermes-wxauto` 当前 `main` 分支源码，而不是预设的接口名称：

- `src/my_wxauto/bridge_server.py` 提供 `GET /health`、`GET /events`、`POST /events/{batch_id}/ack`、`POST /events/{batch_id}/complete` 和 `POST /send`。
- `src/my_wxauto/hermes_sidecar.py` 使用 long-poll `/events`，并在处理开始时 ack、处理完成后 complete。
- `src/my_wxauto/bridge_events.py` 的事件是一个会话一个 `ConversationBatch`；事件同时带 `event_id` 和 `batch_id`，消息带 `message_key`。
- `src/my_wxauto/bridge_store.py` 会把 `frozen`/`submitted` 的未完成批次持久化，所以 `/events` 返回后必须显式 complete，否则重启或轮询重试时仍可能再次看到它。
- `src/my_wxauto/listener.py` 的 `listen_conversation_batches` 已经按会话批处理，并支持 `mark_submitted_on_callback`；本项目不复制其 Windows UI 逻辑，只消费 bridge HTTP 接口。

上游项目地址：[doingSthing/hermes-wxauto](https://github.com/doingSthing/hermes-wxauto)。

## 安装

在 PowerShell 中进入本项目目录：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
Copy-Item .\config.example.yaml .\config.yaml
```

另开一个目录安装并运行当前的 hermes-wxauto。它需要 Windows 微信已经登录：

```powershell
git clone https://github.com/doingSthing/hermes-wxauto.git ..\hermes-wxauto
Set-Location ..\hermes-wxauto
git apply ..\auto_wechat\patches\hermes-wxauto-no-foreground.patch
python -m pip install -e ".[dev]"
hermes-wxauto --bridge-server `
  --bridge-host 127.0.0.1 `
  --bridge-port 8765 `
  --store-path .\.wxauto-bridge.sqlite3 `
  --bridge-queue-size 1000 `
  --listen-max-chats 5 `
  --no-foreground
```

本地联调使用的 `--no-foreground` 只影响监听器：它禁止监听过程恢复、激活或置前微信，也不会移动真实鼠标；普通的打开聊天和发送消息接口仍保持原行为。启用后，如果微信被完全隐藏到托盘或最小化，监听器不会擅自恢复窗口，需先手动让微信保持可见。

bridge 的 SQLite 和本项目的 SQLite 必须是两个文件。bridge 的 `--store-path` 只由 hermes-wxauto 使用；本项目使用 `data/auto-reply.sqlite3`。

先确认 bridge 健康：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

## 启动本项目

在本项目目录的另一个 PowerShell 窗口：

```powershell
.\.venv\Scripts\Activate.ps1
python -m wechat_auto_reply --config .\config.yaml
```

服务会阻塞在 `/events?timeout=30&limit=1`，空闲时不会在应用层高频忙轮询。bridge 自己的 Windows UI listener 仍按其 `listen_interval` 工作，这是 hermes-wxauto 内部实现。

日志位置：

- 控制台：启动、bridge 健康、ack、保存、complete、异常重试。
- `data/logs/auto-reply.log`：滚动文件日志。
- `data/auto-reply.sqlite3`：会话、消息、bridge 事件生命周期和未来决策审计表。

## 真实微信验证步骤

1. 登录 Windows 微信，不要关闭微信主窗口。
2. 启动 hermes-wxauto bridge-server，并确认 `/health` 返回 `status=ok`。
3. 启动本项目，确认日志出现 `hermes-wxauto bridge healthy`。
4. 用另一账号向一个明确的联系人发送一条文本，例如 `phase1-test-001`。
5. 本项目日志应依次出现同一个 `event_id` 的 `event acknowledged`、`event saved`、`event completed`；日志明确标注 `phase 1`，不会发送回复。
6. 用 SQLite 查询验证：

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/auto-reply.sqlite3'); print(c.execute('select chat_name, count(*) from messages join conversations using(conversation_id) group by chat_name').fetchall()); print(c.execute('select event_id, local_status, message_count from bridge_events order by received_at').fetchall())"
```

7. 发送第二条消息，确认新消息有新的 `message_key`/`event_id`；同一事件重试不会增加第二条相同消息。
8. 如果要验证 crash-recovery，可在日志显示 ack 后、complete 前暂时停止本项目，再重启；本项目会从 bridge 的 `submitted` 事件恢复，SQLite 中消息仍只保存一次，随后完成该事件。

当前仓库的自动化测试不需要启动微信或 Windows UI：

```powershell
python -m pytest
```

## 当前限制

- bridge/server 必须单独运行；本项目不负责启动微信或 hermes-wxauto。
- 当前只保存 bridge 收到的消息，不读取旧聊天记录，不实现联系人长期记忆、人格学习、检索或管理 API。
- `llm` 配置、OpenAI-compatible client、prompt/parser/policy 边界已经放好，但服务不会创建模型请求。
- 数据库保存的是本项目自己的审计数据；bridge 的原始事件状态仍由 bridge 自己的 SQLite 管理。
