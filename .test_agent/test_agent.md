# 灵析 AI 对话测试 Agent 指南
让 Codex/Claude agent 立刻能驱动 http://localhost:5173/ 跑多轮对话测试。
---
## 0. 硬约束
- MCP 单调用 ≤280s; 单 batch ≤12 轮 (超过必卡)
- IAB 同会话 22+ 轮 → R2 后必然 timeout, 必须分多 batch 重开会话
- localhost 调用必须从浏览器侧发起, sandbox EPERM 不允许直连
---
## 1. 工具链
首选: Codex IAB 浏览器 (经 `mcp__node_repl__js` 调 Playwright API)。
备选: 本地 Chrome + CDP (`chrome --remote-debugging-port=9222`) 避 IAB R2 卡死。
---
## 2. 已验证脚本
路径 `/Users/jx/Documents/Codex/2026-07-13/da/work/`:
- `test_runner_v3.mjs`: getTab, sendAndWait, extractConversation, newChat
- `long_chat_helpers.mjs`: sendOne, snap, getFullAi, loadState/saveState
---
## 3. DOM 节点
| 节点 | selector | 备注 |
|------|----------|------|
| 输入框 | `textarea` | placeholder*=输入消息 |
| 发送按钮 | `button.send-btn` | class 最稳 (Vue 控 disabled) |
| AI 消息 | `.ai-message > .message-text` | 提取用 .message-text, 避 thinking 标签 |
| 用户消息 | `.user-message` | — |
| 思考中 | `.thinking-label` | 含 "正在思考" |
| 中断按钮 | `button:has-text(中断当前对话)` | 流式生成时显示 |
| 回溯 | `button[title=回溯到此对话]` | AI 消息上 |
| 复制 | `button[title=复制]` | AI/用户消息上 |
---
## 4. 后端 SSE 协议
- 端点 `POST /chat/<sid>/invoke`, body `{message, ...}`
- 流顺序: `init → reasoning → content* → tool_call_name? → tool_call_result? → done`
- 其他: `POST /chat/improve_input` (改写, bug: 不改), `POST /chat/<sid>/version/<cid>` (跳检查点)
---
## 5. 5 个必踩陷阱
1. **同会话 22+ 轮 IAB 卡死** — R1 OK, R2 起全 timeout. 解决: ≤12 轮/batch, 重开会话
2. **send-btn 反应延迟** — `await waitForTimeout(500)` + `click({force: true})` 跳过 disabled 校验
3. **URL 漂移** — 新会话 URL 从 `/` → `/<hash>` 是正常, 不是切换 bug
4. **完成判定** — 不要用"中断按钮消失", 用"AI 文本长度稳定 1.5-2.5s"
5. **MCP 边界丢 Vue 状态** — 每 batch 必须 `getTab()` + `evaluate()` 重读 DOM
---
## 6. 单 batch 完整流程
```js
var fs = await import("node:fs");
var rv = await import(".../work/test_runner_v3.mjs");
var hl = await import(".../work/long_chat_helpers.mjs");
var { ROUNDS } = await import(".../your/rounds.mjs");
var tab = await rv.getTab();
await rv.newChat(tab);
await tab.playwright.waitForTimeout(2500);
var startSessionUrl = await tab.playwright.evaluate(() => location.href);
async function sendR(tab, message, maxWait) {
  if (!maxWait) maxWait = 22000;
  var ta = tab.playwright.locator("textarea").first();
  var sb = tab.playwright.locator("button.send-btn").first();
  await ta.fill(""); await tab.playwright.waitForTimeout(200);
  await ta.fill(message); await tab.playwright.waitForTimeout(500);
  var base = await tab.playwright.evaluate(() => document.querySelectorAll(".ai-message").length);
  await sb.click({force: true});
  var t0 = Date.now();
  var lastLen = 0, stableSince = 0;
  while (Date.now() - t0 < maxWait) {
    await tab.playwright.waitForTimeout(700);
    var cnt = await tab.playwright.evaluate(() => document.querySelectorAll(".ai-message").length);
    if (cnt > base) {
      var cur = await tab.playwright.evaluate(() => {
        var ai = document.querySelectorAll(".ai-message");
        var last = ai[ai.length-1];
        if (!last) return 0;
        var t = last.querySelectorAll(".message-text");
        return t.length > 0 ? Array.from(t).map(e => e.innerText.trim()).join("\n").length : last.innerText.length;
      });
      if (cur > 8 && cur === lastLen) {
        if (stableSince === 0) stableSince = Date.now();
        if (Date.now() - stableSince >= 1500) return {ok: true, cnt, len: cur, elapsedMs: Date.now()-t0};
      } else { stableSince = 0; lastLen = cur; }
    }
  }
  return {ok: false, cnt, len: lastLen, reason: "timeout", elapsedMs: Date.now()-t0};
}
var t0 = Date.now();
var results = [];
for (var i = 0; i < ROUNDS.length; i++) {
  if (Date.now() - t0 > 230000) { console.log("BUDGET BREAK"); break; }
  var sr = await sendR(tab, ROUNDS[i].msg);
  var pv = sr.cnt > 0 ? await hl.getFullAi(tab, sr.cnt - 1) : "";
  results.push({round: i+1, topic: ROUNDS[i].topic, msg: ROUNDS[i].msg.slice(0,80),
    ok: sr.ok, elapsedMs: sr.elapsedMs, finalLen: sr.len,
    reason: sr.reason || null, preview: (pv||"").slice(0, 350)});
  console.log("R"+(i+1)+" "+(sr.ok?"OK":"TO")+" "+sr.elapsedMs+"ms len="+sr.len);
}
var endSessionUrl = await tab.playwright.evaluate(() => location.href);
fs.writeFileSync(".../results.json", JSON.stringify({
  suite: "your_suite_name",
  session_url: startSessionUrl, end_session_url: endSessionUrl,
  session_unchanged: endSessionUrl === startSessionUrl,
  started_at: new Date().toISOString(),
  rounds: results
}, null, 2));
```
---
## 7. 对话测试的范围、主题与执行规范
### 7.1 对话范围（每 batch 8-12 轮必须包含）
| 维度 | 数量 | 必选 | 例 |
|------|------|------|----|
| 单轮能力 | 2-3 | ✓ | "你好"/"123*456"/"翻译成英文" |
| 领域核心能力 | 4-5 | ✓ | "写 SQL..."/"写 Python..."/"算方差" |
| **记忆检查点** | 1-2 | ✓ | "刚才推荐的书名？"/"我叫什么？" |
| 边界压力 | 1 | ✓ | 500 字解释 / 中英混合 / 超长输入 |
| 多步推理 | 0-1 |   | "先 X 再 Y, 然后 Z, 总结" |
| 工具调用 | 0-1 |   | "上传 CSV 并分析" / "跑 Python" |
| 抗噪/纠正 | 0-1 |   | 故意写错前提让 AI 纠错 |
每 5-7 轮插一个记忆检查点, 用于区分 IAB 状态丢失 vs LLM 真实问题。
### 7.2 主题选取（针对数据分析助手）
真实业务场景优先于抽象问题:
- **业务诊断类** (推荐): "我是奶茶店主/外卖运营/电商运营, ..." — 让 AI 拆解问题
- **数据处理类**: 清洗/聚合/透视/异常检测
- **代码生成类**: SQL/Pandas/sklearn, 必须能跑
- **可视化类**: matplotlib/plotly 图表建议 + 代码
- **统计推断类**: 假设检验/A/B 测试/样本量
- **业务分析类**: 增长归因/留存分析/RFM
主题要 *具体* 不要抽象; 业务场景设定能提高 AI 的回答质量, 便于判断。
### 7.3 执行规范
1. **每 batch 新开会话** (接受非同一 session 折中, 见陷阱 1)
2. **轮间强制间隔**: 每轮至少留 500ms 让 Vue 反应
3. **检测顺序**: 先 R1 (cold start 验证), 再批量跑; R1 超时直接放弃该 batch
4. **超时分级**: 简单问题 ≤10s, 含代码 ≤20s, 复杂推理 ≤30s
5. **失败记录**: 即便 ok=false, 也要保存 preview (实际 AI 已生成的部分内容)
6. **可复现**: 每 batch 记录 session_url + start/end 时间, 用于事后分析
### 7.4 主题组合示例 (可直接复用)
**主题 A: 数据分析助理日常** (12 轮)
- R1 自我介绍 → R2 拉取数据建议 → R3 SQL 生成 → R4 SQL 解释 → R5 异常检测 → R6 假设检验 → R7 写 Python → R8 跑出可视化建议 → R9 看板指标 → R10 告警规则 → R11 A/B 样本量 → R12 总结
**主题 B: 业务侧运营优化** (10 轮)
- R1 场景设定 (5 家奶茶店店主) → R2 关键问题 → R3 复购分析框架 → R4 3 个落地动作 → R5 ROI 估算 → R6 季节归因 → R7 RFM 分群 → R8 SQL (复购率) → R9 异动检测 → R10 总结
**主题 C: 多语言/记忆压力** (10 轮)
- R1 中文问候 → R2 英文自我介绍 → R3 中文问答 → R4 英文翻译 → R5 中文 SQL → R6 记忆检查 → R7 英文记忆检查 → R8 中文长文 → R9 英文总结 → R10 中文总结
---
## 8. 报告生成
```python
import json
data = json.load(open("results.json"))
rounds = data["rounds"]
ok_n = sum(1 for r in rounds if r.get("ok"))
md = ["# 测试报告", f"> 会话: {data['session_url']}", f"> 轮次: {len(rounds)} | OK: {ok_n}",
       "", "| R | 主题 | 状态 | 长度 | 预览 |", "|---|------|------|------|------|"]
for r in rounds:
    flag = "OK" if r.get("ok") else "TO"
    pv = (r.get("preview") or "").replace(chr(10), " ").strip()[:60]
    md.append(f"| R{r['round']} | {r['topic']} | {flag} | {r['finalLen']}ch | {pv} |")
open("outputs/report.md", "w").write("\n".join(md))
```
---
## 9. 已确认的真实后端缺陷
1.跨多轮记忆上限：19+ 轮 R12/R17 失败（已用 3 轮隔离测试对照, 结论：IAB 状态丢失而非 LLM 真实缺陷）
2.优化输入无效：`POST /chat/improve_input` 返回的 `improved_text` 与原文完全相同
3。业务复杂题卡死：复杂业务题（T08 类）触发 20+ 分钟无限工具调用循环
4.IAB 路由状态不稳：新会话 URL 在 R1 后从 `/` 跳到 `/<hash>`，可丢失前端历史
---
