# 第一阶段架构

## 目标边界

当前实现只负责把 hermes-wxauto 的单会话事件可靠地落到本地 SQLite，并完成 bridge 事件。模型和微信发送保留边界，但没有接入到运行路径。

```mermaid
flowchart LR
    W[Windows 微信] --> H[hermes-wxauto bridge-server]
    H -->|GET /events long poll| B[HttpWeChatBridge]
    B --> S[AutoReplyService]
    S -->|POST ack| H
    S --> R[Repository]
    R --> D[(application SQLite)]
    S -->|POST complete| H
    S -. phase 2 .-> C[ContextBuilder]
    C -. phase 2 .-> L[LLMClient]
    L -. structured decision .-> P[PolicyEngine]
    P -. phase 2 .->|only after policy| B
```

依赖方向是：

```text
wechat adapter ─┐
                ├─> AutoReplyService ─> Repository ─> Database
config ---------┘

ContextBuilder / LLMClient / PolicyEngine 是未来模型路径，第一阶段不参与运行。
```

## hermes-wxauto 当前契约

当前上游源码的关键事实：

1. bridge `/events` 返回一个 JSON object，其中 `events` 是会话批次列表。
2. 一个事件有 `batch_id`、兼容性的 `event_id`、`chat_id`、`chat_name`、`status` 和 `messages`。
3. 上游 `ConversationBatch` 的状态从 `frozen` 开始；消费者 ack 后 bridge store 变为 `submitted`，complete 后变为 `completed`。
4. `/events` 只是读取/等待，不负责确认；未完成的 `frozen` 和 `submitted` 批次会从 bridge store 再次返回。
5. 上游 batcher 以 `message_key` 去重，且每个 batch 只属于一个 `chat_name`。

因此本项目适配器不依赖上游的内部 Python import，只依赖 HTTP 和上述 JSON 形状。未来替换微信自动化实现时，只需实现 `WeChatBridge` 协议。

当前本机联调的 hermes-wxauto checkout 额外启用了监听参数 `--no-foreground`。该参数只绕过监听器中的窗口恢复、`activate()` 和真实鼠标点击；发送/打开聊天等其他接口不受影响。后台模式要求微信主窗口已经可见且未最小化，否则监听器会跳过本轮读取而不抢前台。

## 事件处理与恢复

```text
poll
  │
  ├─ 本地 event=completed  -> 跳过（不再 ack，避免把上游 completed 改回 submitted）
  ├─ 本地 event=stored     -> 只重试 complete
  └─ 其他/不存在
       -> ensure_event_received
       -> bridge ack
       -> local event=acknowledged
       -> 一个 SQLite 事务：会话 + 消息幂等写入，local event=stored
       -> bridge complete
       -> local event=completed
```

跨 HTTP 与 SQLite 不可能实现单个原子事务，所以保留 `stored` 状态处理 complete 失败窗口：

- ack 成功、进程退出：bridge 会重发 `submitted`，本地重新接着处理。
- SQLite 保存成功、complete 超时：消息不会重复插入，下一次只重试 complete。
- complete 成功、本地最终状态写入前退出：消息已经可靠保存；bridge 不再返回该事件，留下 `stored` 审计状态，不会重复发送（当前本来就不发送）。

## SQLite 表

- `conversations`：bridge chat identity 与显示名。
- `messages`：收到/发送的消息；`external_message_key` 全局唯一，当前只写 `incoming`。
- `bridge_events`：上游事件原文、bridge 状态、本地处理状态和时间点。
- `decisions`：未来模型原文、解析 action、回复、置信度、理由、策略是否允许发送及最终发送结果。

会话隔离通过 `bridge_chat_id`、事件所属 `conversation_id`、消息所属 `conversation_id` 三层约束保护；事件中的消息 `chat_name` 与事件会话不一致时，整个事务拒绝写入。
