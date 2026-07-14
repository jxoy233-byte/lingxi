# 灵析 Lingxi — Design Guidelines

> 这是 `frontend/src/` 视觉规范的 Figma 等价说明。所有 token / 组件 / 状态都从现行代码（`App.vue` / `components/*.vue`）反向汇总而来，目的是让设计师在 Figma 里建立 1:1 对应的页面、组件库、变量集。
>
> 维护提示：先改文件、再改本文档；本文档不是 source of truth，仅作为 Figma 端的索引。

---

## 0. 项目元信息

| 字段 | 值 |
| --- | --- |
| 产品名 | 灵析（Lingxi） |
| 中文 Slogan | 数据分析智能助手 |
| 品牌色 | `#10A37F`（OpenAI 绿） |
| 字体族 | `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, Fira Sans, Droid Sans, Helvetica Neue, sans-serif` |
| 代码字体 | `'SF Mono', Monaco, Consolas, 'Courier New', monospace` |
| 主语言 | zh-CN（默认 `<html lang="zh-CN">`） |
| Electron appId | `com.chatme.app` |
| productName | `灵析` |
| 默认 favicon | `/favicon.ico` |
| 主服务端口 | 8211（FastAPI） / 18080（MCP） / 5173（Vite dev） |

---

## 1. Tokens（设计变量）

### 1.1 颜色（CSS Variables）

颜色全部以 `--xxx` CSS 变量形式定义在 `App.vue :root`（亮色）和 `.dark-theme`（暗色）块里。Figma 端请建立同名的 Color Variables（Light / Dark 两套 mode）。

#### 1.1.1 表面 / 文字 / 边框

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--bg-primary` | `#FFFFFF` | `#212121` | 主背景（聊天区 / 卡片 / 模态） |
| `--bg-secondary` | `#F0F0F0` | `#2A2A2A` | 次级背景（输入框 / quote / restart-mask 底色 / 思考 header） |
| `--bg-hover` | `#E8E8E8` | `#383838` | hover / active / nav-item active |
| `--text-primary` | `#1A1A1A` | `#ECECEC` | 主要文字 |
| `--text-secondary` | `#6B7280` | `#9CA3AF` | 次级文字（时间 / 副标题 / hint） |
| `--border-color` | `#E5E5E5` | `#363636` | 通用边框 / 分隔线 |
| `--sidebar-bg` | `#F7F7F8` | `#171717` | 侧边栏背景 |
| `--header-bg` | `#FFFFFF` | `#212121` | 头部背景 |

#### 1.1.2 品牌色 / 按钮

| Token | 值 | 用途 |
| --- | --- | --- |
| `--button-bg` | `#10A37F` | 主按钮 / 发送 / 新对话 / link / 进度 active / 工具 running dot |
| `--button-hover` | `#0D8C6D` | 主按钮 hover |
| `--primary-color` | `#3B82F6` | 数据分析产物触发按钮 active / 角标 / 文件 hover 描边 |

#### 1.1.3 消息气泡

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--user-msg-bg` | `#DCDCDC` | `#2D2D2D` | 用户消息气泡背景 |
| `--user-msg-border` | `#C0C0C0` | `#404040` | 用户消息气泡边框 |
| `--ai-msg-bg` | `transparent` | `transparent` | AI 消息无气泡 |

#### 1.1.4 代码块

| Token | Light | Dark |
| --- | --- | --- |
| `--code-block-bg` | `#F7F7F8` | `#141414` |
| `--code-block-border` | `rgba(234, 235, 236, 0.9)` | `rgba(255, 255, 255, 0.1)` |
| `--code-block-shadow` | `0 1px 2px rgba(0,0,0,0.05)` | `0 2px 6px rgba(0,0,0,0.5)` |
| `--code-block-text` | `#1F2937` | `#E5E7EB` |
| `--code-inline-bg` | `rgba(234, 235, 236, 0.6)` | `rgba(255, 255, 255, 0.06)` |
| `--code-inline-color` | `#D6336C` | `#F472B6` |
| `--code-lang-bg` | `rgba(255, 255, 255, 0.8)` | `rgba(0, 0, 0, 0.3)` |
| `--code-lang-border` | `rgba(220, 222, 224, 0.9)` | `rgba(255, 255, 255, 0.08)` |
| `--code-lang-color` | `#6B7280` | `#9CA3AF` |

#### 1.1.5 语义色（非 token，直接 hardcode 在组件里）

| 语义 | Hex | 出现位置 |
| --- | --- | --- |
| Danger（base） | `#EF4444` | 错误边框 / 删除按钮 / 中断 dot / 删除按钮 hover bg |
| Danger（hover） | `#DC2626` | 确认按钮 hover |
| Danger（文字，light bg） | `#B91C1C` | 错误气泡文字（亮色主题） |
| Danger（文字，dark bg） | `#FCA5A5` | 错误气泡文字（暗色主题） |
| Danger-soft-bg（light） | `rgba(239, 68, 68, 0.08)` | 错误气泡背景 |
| Danger-soft-bg（dark） | `rgba(239, 68, 68, 0.12)` | 错误气泡背景（暗） |
| Danger-soft-border（light） | `rgba(239, 68, 68, 0.3)` | 错误气泡边框 |
| Danger-soft-border（dark） | `rgba(239, 68, 68, 0.35)` | 错误气泡边框（暗） |
| Danger-light-bg | `#FEF2F2` | 中断按钮 hover bg |
| Success（base） | `#10A37F` | 续接按钮 / tool-check ✓ |
| Success（hover） | `#059669` | 续接按钮 hover 文字 |
| Success-soft-bg | `#ECFDF5` | 续接按钮 hover bg |
| Warning（local env） | `#D97706` | 工具调用 `env-local` 标签 |
| 文件类型 — text | `#667EEA` | 文本附件左侧 border + icon |
| 文件类型 — pdf | `#FF6B6B` | PDF 附件左侧 border + icon |
| Markdown h1 | `#16A34A` | H1 标题 |
| Markdown h2 | `#22C55E` | H2 标题 |
| Markdown h3 | `#4ADE80` | H3 标题 |
| Markdown h4 | `#86EFAC` | H4 标题 |
| Toolbar overlay | `rgba(0, 0, 0, 0.5)` | iframe / mmd 上的下载/全屏按钮底色 |
| Toolbar overlay hover | `rgba(0, 0, 0, 0.7)` | hover 状态 |
| 遮罩（modal） | `rgba(0, 0, 0, 0.45)` + `backdrop-filter: blur(4px)` | ConfirmDialog |
| 遮罩（settings） | `rgba(0, 0, 0, 0.4)` | SettingsDialog |
| 遮罩（image preview） | `rgba(0, 0, 0, 0.9)` | 全屏图片预览 |
| 遮罩（drag） | `rgba(0, 0, 0, 0.8)` | 拖拽上传 |
| Settings restart mask | `rgba(255, 255, 255, 0.85)` / `rgba(33, 33, 33, 0.85)` | 重启遮罩 |

### 1.2 字体排印

| Token | Size / Weight / Line-height | 用途 |
| --- | --- | --- |
| `display/welcome` | 26 / 600 / — | Welcome h2「你好！我是灵析……」 |
| `h1 (logo)` | 20 / 600 / — | 头部品牌名「灵析」 |
| `h1 (mobile)` | 17 / 600 / — | 头部品牌名（≤600px） |
| `h2` | 16 / 600 / — | Settings section / CheckpointPanel 标题 / Settings h3 |
| `h3 (settings)` | 15 / 600 / -0.01em | SettingsDialog 顶部 |
| `h4 (modal title)` | 16 / 600 / — | ConfirmDialog title / Settings section |
| `body-lg (message)` | 15 / 400 / 1.7 | `.message-text` 正文 |
| `body-md (input)` | 15 / 400 / 1.5 | 输入框 |
| `body-md (button)` | 15 / 500 / — | Send button |
| `body-sm (conv title)` | 14 / 500 / — | 会话标题 / Settings 标签 |
| `body-sm (modal btn)` | 14 / 500 / — | 模态按钮文字 |
| `body-sm (input field)` | 14 / 400 / — | SettingsDialog input |
| `body-sm (quote)` | 13 / 400 / 1.5 | 引用块正文 |
| `caption (label)` | 12 / 500 / — | time / thinking label / field label / modal-desc |
| `micro` | 11 / 500-600 / — | quote label / tool badge / code lang tag / tag |
| `code (block)` | 13.5 / 400 / 1.65 | 代码块正文 |
| `code (inline)` | 0.85em / 400 / — | 行内代码（em 相对父级） |
| `code (tool)` | 11-12 / 400-600 / — | tool-call args / result / name |
| `tag/caps` | 10 / 500 / 0.04em uppercase | SettingsDialog tag |
| Markdown H1 | 1.7em / 1000 / 1.4 | `.message-text :deep(h1)` |
| Markdown H2 | 1.45em / 900 / 1.4 | |
| Markdown H3 | 1.25em / 900 / 1.4 | |
| Markdown H4 | 1.1em / 700 / 1.4 | |
| Markdown H5 | 1em / — / 1.4 | |
| Markdown H6 | 0.9em / — / 1.4 | |

### 1.3 圆角

| 名称 | 半径 | 出现位置 |
| --- | --- | --- |
| `r-xs` | 3px | textarea 滚动条 thumb |
| `r-sm` | 4px | icon button / tag / file-error-badge |
| `r-md` | 5px | action button |
| `r-base` | 6px | sidebar items / toolbar / toggle / checkpoint / tool-call / file-attachment |
| `r-input` | 8px | resume-input textarea / icon button (settings) / file preview btn / `pill-dot` border 实质 |
| `r-input-lg` | 10px | quote block / checkpoint item / streaming dot |
| `r-bubble` | 12px | code block / file attachment / textarea / optimize button / send button / settings modal / pill |
| `r-modal` | 16px | ConfirmDialog / message-content bubble / image-preview-img |

### 1.4 间距 / 尺寸

#### 1.4.1 布局尺寸

| 名称 | 值 |
| --- | --- |
| 视口 | 100vw × 100vh（`overflow: hidden`） |
| Sidebar 宽度（展开） | 260px |
| Sidebar 宽度（折叠） | 60px |
| Header 高度 | 60px（mobile 不变结构，padding 12） |
| Sidebar header 高度 | 60px（12+36+12） |
| Chat area 高度 | 100% − 0（flex column） |
| 输入区 padding | 16px（mobile 12px） |
| 消息列 max-width | 900px |
| 消息列 padding | 32px 16px 16px（mobile 16px 12px 12px） |
| 消息间距（margin-bottom） | 28px |
| 输入栏最大宽度 | 900px（与消息列对齐） |

#### 1.4.2 抽屉 / 面板尺寸

| 面板 | 宽度 | 备注 |
| --- | --- | --- |
| CheckpointPanel | 320px（固定） | 从右侧滑入，z-index 200 |
| WebPreviewPanel | 由父层控制 | z-index 100 |
| FilePreviewPanel | 480px（默认，可拖拽 resize） | z-index 100 |
| DataAnalysisTree popover | 380px × max 520px | 浮动面板，z-index 150 |
| ResumeInputDialog | 400px | modal，z-index 10000 |
| ImagePreviewModal | max 90vw × 90vh | z-index 10000 |
| SettingsDialog | 720 × 580（max 92vw / 88vh） | z-index 1500 |
| ConfirmDialog | max 360（90%） | z-index 1000 |
| Sidebar mobile | 260px（position fixed） | z-index 100 |

#### 1.4.3 组件尺寸

| 元素 | 尺寸 |
| --- | --- |
| Header icon button | 40 × 40 |
| Sidebar toggle | 36 × 36 |
| Sidebar new-chat btn | flex:1, height 36 |
| Conversation item | padding 12, border-radius 6 |
| Action button (AI 消息) | 26 × 26 |
| Action button (header) | 40 × 40 |
| Send / optimize / upload icon | 52 × 52 |
| Send button | padding 0 24, height 52 |
| Textarea | min-height 52 / max-height 200 |
| File list thumbnail | 80 × 80 |
| File attachment（消息内） | 100 × 100 |
| File image grid | 120 × 120 |
| Code lang tag | 11px font / padding 2 8 |
| Code copy button | 28 × 28, top:8 right:8 |
| Tool call header | padding 5 8 |
| Thinking status dot | 7 × 7 |
| Tool running dot | 6 × 6 |
| Streaming dot | 8 × 8 |
| Modal icon wrap | 56 × 56 round |
| Modal icon | 28 × 28 |
| Image preview close | 36 × 36 round |
| Quote bar | width 3px |
| SettingsDialog nav | width 160 |
| SettingsDialog field | padding 8 10 |
| SettingsDialog group | padding 16 18 |
| SettingsDialog footer | padding 12 20 |

#### 1.4.4 spacing scale（取自实际值）

| Token | 值 | 例子 |
| --- | --- | --- |
| `space-0` | 0 | reset |
| `space-1` | 2px | `gap: 2px` settings actions |
| `space-2` | 4px | `gap: 4px` quote content / thinking label / streaming dot / file-error-badge offset |
| `space-3` | 6px | conv title row gap / sidebar btn / toolbar gap / code tag padding-y |
| `space-4` | 8px | header padding-y / file gap / conversation-list padding |
| `space-5` | 10px | quote gap / code-block padding-y / md-toggle bottom |
| `space-6` | 12px | message bubble padding / header padding-x / sidebar header padding / md-block padding |
| `space-7` | 14px | message bubble padding-x / quote text line-height |
| `space-8` | 16px | input-area padding / code-block padding-x / SettingsDialog nav-y |
| `space-10` | 20px | header padding-x / panel-header padding / settings content padding-x |
| `space-12` | 24px | empty-state padding / settings content padding-y / restart-card padding |
| `space-16` | 28px | 消息间距 |
| `space-20` | 32px | messages-column padding-top |
| `space-40` | 60px | welcome-message margin-top |

#### 1.4.5 Gap / 间距速查

- `gap: 1px` action buttons
- `gap: 2px` settings-actions / panel-actions
- `gap: 4px` typing-indicator / quote-label
- `gap: 6px` sidebar-btn / file-item vertical
- `gap: 7px` thinking-header-left
- `gap: 8px` sidebar-header / file-grid / file-attachments
- `gap: 10px` user-files-display / file-image-grid / file-attachments-list
- `gap: 12px` header-actions / error-box / conv-row
- `gap: 16px` quote-block / resume-input-buttons

### 1.5 阴影

| 名称 | 值 | 用途 |
| --- | --- | --- |
| `shadow-code-light` | `0 1px 2px rgba(0,0,0,0.05)` | 代码块（亮） |
| `shadow-code-dark` | `0 2px 6px rgba(0,0,0,0.5)` | 代码块（暗） |
| `shadow-quote` | `0 2px 6px rgba(0,0,0,0.08)` | 浮动引用按钮 |
| `shadow-confirm-hover` | `0 4px 12px rgba(239,68,68,0.35)` | ConfirmDialog 确认按钮 hover |
| `shadow-file-hover` | `0 4px 12px rgba(0,0,0,0.08)` | 文件附件 hover |
| `shadow-panel` | `0 8px 24px rgba(0,0,0,0.12)` | SettingsDialog / DataAnalysisTree panel |
| `shadow-modal-big` | `0 20px 60px rgba(0,0,0,0.25), 0 0 0 1px var(--border-color)` | ConfirmDialog |
| `shadow-mobile-sidebar` | `2px 0 8px rgba(0,0,0,0.15)` | 移动端侧栏 |
| `shadow-flash-tip` | `0 4px 12px rgba(0,0,0,0.15)` | flash tip |
| `shadow-checkpoint-panel` | `-4px 0 12px rgba(0,0,0,0.08)` | CheckpointPanel |
| `shadow-optimize-hover` | `0 2px 8px rgba(16,163,127,0.2)` | 优化按钮 hover |
| `shadow-interrupted-bar` | `0 4px 12px rgba(0,0,0,0.1)` | 中断状态栏 |

### 1.6 Z-index 层级（数字越大越上层）

| 层 | 值 | 用途 |
| --- | --- | --- |
| 基础 | 0 / auto | 内容层 |
| 中断状态栏 | 50 | `.interrupted-bar` |
| 中断遮罩 / 网页预览遮罩 / 文件预览遮罩 / checkpoint 遮罩 | 99 | `.xxx-overlay` |
| FilePreviewPanel / WebPreviewPanel | 100 | 右侧抽屉 |
| DataAnalysisTree popover | 150 | 必须 > FilePreview |
| CheckpointPanel | 200 | 必须 > DataAnalysisTree |
| Sidebar（mobile） | 100 | |
| ConfirmDialog overlay | 1000 | |
| Quote floating button | 1000 | |
| Settings overlay | 1500 | |
| Flash tip | 2000 | `body` 直接 append |
| ResumeInputDialog | 10000 | |
| ImagePreviewModal | 10000 | |

### 1.7 动画 / 过渡

| 名称 | 曲线 / 时长 | 用途 |
| --- | --- | --- |
| `easeInOutCubic` | cubic(0.65, 0, 0.35, 1) / 800ms | entry 平滑入场 |
| `easeOutCubic` | cubic(0.33, 1, 0.68, 1) / 150ms | 流式 locked-follow |
| `linear` | / 600ms | ramp 阶段 P1 |
| `easeOutCubic` | / 250ms | ramp 阶段 P2 |
| `blinking-dot` | 1.2s ease-in-out infinite | 侧栏流式 dot / 工具 running dot |
| `typing` | 1.4s infinite ease-in-out | MessageList 输入指示器（3 个 dot 0.2/0.4s 错位） |
| `live-pulse` | 1.2s ease-in-out infinite | thinking active dot |
| `pulse-text` | 2s ease-in-out infinite | "AI酱 正在思考中…" 文本 |
| `spin` | 1s linear infinite | loading spinner |
| `bounce` | 1s infinite | drag-overlay 上传箭头 |
| `fadeIn` | 0.2-0.3s | image preview / loading-message |
| `scaleIn` | 0.2s scale(0.9→1) | image-preview-content |
| `modal-enter` | 0.2s scale(0.92) translateY(8px→0) | ConfirmDialog |
| `slide-enter` | 0.3s ease translateX(100%→0) | CheckpointPanel / FilePreviewPanel / WebPreviewPanel |
| `da-fade` | 0.15s opacity + translateY(-4px→0) | DataAnalysisTree panel |
| `flash-in` | 0.2s ease-out translateY(6px→0) | SettingsDialog flash tip |

### 1.8 滚动条

- 全局 webkit：width 8px / thumb `var(--border-color)` / hover `var(--text-secondary)`
- 侧栏：默认 `::-webkit-scrollbar { width: 0 }`，溢出时挂 `.has-overflow` 显示 6px 细条
- textarea：6px 细条 + 自定义颜色
- 文件列表横滚：6px 高
- hover 表态统一加 `transition: background 0.15-0.2s`

---

## 2. 主题

### 2.1 切换

- 入口：`localStorage.getItem('chatme-theme')`，`dark` / 其他 → `light`
- 写入：`<App class="app-container dark-theme">` 切换 `.dark-theme` 类
- 实时生效：Settings → Appearance → 选 Light/Dark

### 2.2 Theme pill（设置）

- 尺寸：flex:1, padding 10 14, border-radius 8
- pill-dot：12 × 12 round，light = `#FFFFFF`，dark = `#1F2937`
- 选中态：border-color = `--text-primary`，bg = `--bg-hover`

### 2.3 字号 / 颜色对照速查

| 区域 | Light | Dark |
| --- | --- | --- |
| App 底色 | 白 | `#212121` |
| Sidebar 底色 | `#F7F7F8` | `#171717` |
| Header 底色 | 白 | `#212121` |
| 主文字 | `#1A1A1A` | `#ECECEC` |
| 次文字 | `#6B7280` | `#9CA3AF` |
| 边框 | `#E5E5E5` | `#363636` |
| 用户气泡 | `#DCDCDC` / `#C0C0C0` | `#2D2D2D` / `#404040` |
| 代码块底 | `#F7F7F8` | `#141414` |
| 代码块文字 | `#1F2937` | `#E5E7EB` |
| 行内代码底 | rgba(234,235,236,0.6) | rgba(255,255,255,0.06) |
| 行内代码文字 | `#D6336C` | `#F472B6` |

---

## 3. 布局 / Frame 结构

### 3.1 主 Frame：`App.vue`

```
┌─────────────────────────────────────────────────────────────┐
│ App (100vw × 100vh)                                          │
│  └── Main Layout (display:flex, height:100%)                │
│      ├── Sidebar (260 / 60 collapsed)                        │
│      ├── ChatArea (flex:1)                                   │
│      │   ├── ChatHeader (60h)                                │
│      │   ├── MessageList (flex:1)                            │
│      │   └── MessageInput (auto)                             │
│      ├── CheckpointPanel (right, fixed 320)                  │
│      ├── WebPreviewPanel (right, fixed)                      │
│      ├── FilePreviewPanel (right, fixed 480)                 │
│      ├── ConfirmDialog × 2 (overlay)                         │
│      ├── ResumeInputDialog (overlay)                         │
│      ├── SettingsDialog (overlay)                            │
│      └── ImagePreviewModal (overlay)                         │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 响应式

| 断点 | 行为 |
| --- | --- |
| ≤ 600px | ① 侧边栏 `position:fixed; left:-260px`，toggle 触发 `mobile-open`，遮罩点击关闭 ② 头部 hamburger 显示 ③ h1 字号 17px ④ padding 收紧（input 12, messages 16 12 12, header 0 12） ⑤ welcome margin-top 60 ⑥ 文件列表 max-width 100% |

---

## 4. 组件库（13 个 + 一些原子）

每个组件给：用途 / 关键尺寸 / 主要状态 / 关键交互。

### 4.1 Sidebar

- Frame：`260 × 100vh`，暗：`bg=#F7F7F8/#171717`
- Header（固定 60h）：左 toggle `36 × 36`，右 `+ 新对话` `flex:1 / 36h / 14px 500 / bg=button-bg / border-radius 6`
- 折叠：width 60px（toggle 仍可见，new-chat 隐藏，conv-list 隐藏）
- Conversation list：height `calc(100vh - 60px)` / padding 8
- Empty state：「暂无历史对话」centered 14px secondary，padding 20

#### ConversationItem

```
┌────────────────────────────────────────┐
│ ● 标题文字……              ×│
│   刚刚 / N分钟前 / N小时前 / N天前 / 日期 │
└────────────────────────────────────────┘
```
- padding 12, border-radius 6, gap 4
- hover / active → bg `var(--bg-hover)`
- streaming：标题前 8×8 dot，`#10A37F`，`@keyframes blink 1.2s`（opacity 0.3↔1）
- 标题：14px 500, max 10 字 + `...`, 双击进入编辑（input 框 + 绿色边框）
- 时间：12px secondary，1min / 1h / 1d 自动切换，「刚刚」起
- 删除 X：24 × 24，默认 opacity 0，hover 时 opacity 1，hover 时变 `--text-primary`

### 4.2 ChatHeader

- Frame：60h / bg = header-bg / bottom 1px border
- 左侧：hamburger（mobile 36×36，`var(--bg-hover)` bg）+ `灵析` 标题 20px 600
- 右侧（12px gap）：DataAnalysisTree slot（仅当前有 session）/ refresh / checkpoint / settings
- 所有 icon btn：40 × 40 / border-radius 8 / `var(--bg-hover)` bg / hover 变 `--button-bg`（opacity 0.8）
- refresh icon：`<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>`
- checkpoint icon：clock（圆 + 12 / 12 / 16）
- settings icon：齿轮
- active 动画：refresh 按下时 SVG `rotate(360deg)` / 0.6s ease

### 4.3 MessageList

- Frame：flex:1 / overflow-y auto / `flex` column 居中
- 列宽 max 900px / padding 32 16 16
- Welcome：「你好！我是灵析——数据分析智能助手」h2 26px 600 + 「有什么我可以帮助你的吗？」secondary，margin-top 120
- Loading：底部一行 12px gap / typing indicator（3 个 7×7 dot，gap 4，1.4s + 错位）+ 「AI酱 正在思考中...」文本（13px secondary，pulse-text 2s）
- 中断时：dot + 文字都变 `#EF4444`，文字「思考已中断」

### 4.4 MessageItem

通用：
- 单条：flex column / margin-bottom 28px / width 100%
- user：`align-items: flex-end`，wrapper max-width 68%
- ai：`align-items: flex-start`，wrapper width 100%
- 间距：消息之间 28px

#### 4.4.1 用户消息（普通）
- 气泡：`bg=--user-msg-bg`，`border=1px --user-msg-border`，`padding 10 14`，`border-radius 16`
- 文字：15px line-height 1.7，white-space pre-wrap
- 内容 > 5 行：自动折叠（显示前 5 行 + `...`，底部 60px 渐变），底部展开按钮 12px secondary
- 气泡左侧复制按钮：26×26，hover 才显（opacity 0→1），复制成功后图标变 ✓

#### 4.4.2 用户消息（含 `<quote>...</quote>`）
- 解析后拆 quote 块（左侧 3px 绿 bar + label + markdown 渲染，max-height 120px 可滚动）
- + 正文（同上）

#### 4.4.3 用户消息（仅文件）
- 气泡隐藏（`display: none`）
- 图片网格：120×120 缩略图 + border-radius 12，gap 10
- 附件：水平卡片（180–300 × auto，padding 12 16，border-radius 12，icon 36×36 + 名称 14px 500 + 大小 12px secondary），左侧 3px 类型色条（text=`#667EEA`, pdf=`#FF6B6B`, other=secondary）

#### 4.4.4 AI 消息

文字容器：
- 文字：15px line-height 1.7
- 链接：`--button-bg`，hover 加下划线 + `--button-hover`
- Markdown h1-h6：见 §1.2
- 引用 blockquote：左 4px `--button-bg`，padding 12 16，bg `--bg-secondary`
- 代码块：见 §1.1.4
- 行内代码：见 §1.1.4
- 表格：`border-collapse: collapse`，th bg `--bg-secondary` 700，tr 偶数行 `--bg-secondary`
- img：max-width 100%，max-height 150px（`.markdown-image`）
- blockquote / pre / table：`overflow-x: auto`

思考过程区块：
- 容器：border 1px `--border-color` / border-radius 8 / font-size 13
- active：border `color-mix(--button-bg 40%, --border-color)`
- interrupted：border `#EF4444`
- header：`bg=--bg-secondary`，padding 7 10，左 dot 7×7（active 时绿 + live-pulse / interrupted 时红 / 默认灰 0.5 透明），中 label「正在思考... / 思考过程 / 思考已中断」，tool badge（圆角 10 / 11px / 绿 + 12% 绿底 + 20% 绿边），右 chevron（默认折叠）
- body：border-top 1px / bg `--bg-primary` / padding 8 10
- 工具调用：每个 item `border-radius 6`，未完成 opacity 0.75，完成 1.0；header 5 8 padding / bg `--bg-secondary` / 12px tool 名 / `:: local` amber-600 / `:: sandbox` 无标签；args/result 11px mono + word-break / max-height 80/200 + 内部滚动
- reasoning-text：12px secondary，opacity 0.8，max-height 200 + 内部滚动

操作按钮组（AI 消息下方）：
- 默认隐藏（opacity 0），hover wrapper 时 opacity 1
- 按钮 26×26 / 13×13 SVG / gap 1px
- 按钮种类：interrupt（红，仅流式中）/ restore（仅非流式）/ restream（仅非首个 AI 消息 + 最新一条）/ copy / resume（中断时）
- 流式 + 非中断 → 显示 interrupt；非流式 → 显示 restore / restream / copy（+resume 仅中断）

引用浮动按钮：
- 选区上方居中（`top: rect.top + scrollY - 38`），absolute / z-index 1000
- bg `--bg-secondary` / border-radius 6 / 12px 500 / 内联 SVG 引用图标 + 「引用」
- hover：bg `--bg-hover`，border `--button-bg`，color `--button-bg`，上移 1px

### 4.5 MessageInput

整体：
- Frame：底部 padding 16 / border-top 1px

引用块（v-if quote）：
- max-width 900 / margin 0 auto 10 / 10px gap / `bg=--bg-secondary` / border-radius 10
- 左 3px 绿 bar / 内容 padding 8 4 8 0
- label：11px 600 / letter-spacing 0.02em / 绿 / 引用 SVG + 「引用」
- text：13px / line-clamp 5 / markdown 渲染
- 关闭 X：22×22，hover bg `--bg-hover`

文件列表（横向）：
- max-width 900 / padding 4 0 / overflow-x auto / height 自适应
- 缩略图：80×80 / 圆角 8 / 2px border（hover 变 `--primary-color`，uploading 变绿 + opacity 0.7，error 变红）
- 删除按钮：右上 4 4 / 24×24 / 黑 0.6 透明 / hover 变红 + scale 1.1
- 文件名：11px / 居中 / max 12 字截断

输入栏：
- max-width 900 / gap 12 / flex row align-end
- upload 按钮：52×52 / 透明 bg / hover 变 `--text-primary`
- optimize 按钮：52×52 / 1px border / pulse 动画（优化中） / hover 上移 + 绿阴影
- textarea：min/max 52/200 / padding 14 16 / border-radius 12 / bg `--bg-secondary`
- 发送按钮：52h / padding 0 24 / 15px 500 / bg `--button-bg` / 圆角 12

拖拽遮罩：
- 整页 fixed / rgba(0,0,0,0.8)
- 中间 SVG + 「释放文件以上传」（18px 500，bounce 1s）

### 4.6 ChatHeader refresh / DataAnalysisTree / 其它头部图标

见 §4.2；refresh 图标与 DataAnalysisTree 的 reload 按钮共用 SVG path：`M20.49 15a9 9 0 1 1-2.12-9.36L23 10`。

### 4.7 CheckpointPanel

- Frame：right:0 fixed / width 320 / bg `--bg-primary` / 1px left border / z-index 200 / shadow `-4px 0 12px rgba(0,0,0,0.08)`
- Header：padding 20 / h3「历史记录」16px 600 / close 32×32 round 6
- Content：flex:1 / overflow-y / padding 12
- Empty：center 48×48 时钟 + 「暂无历史记录」14px
- Item：flex row / 12px gap / padding 12 / bg `--bg-secondary` / 1px border / 圆角 10 / cursor pointer
  - 32×32 round icon 容器 / `--button-bg` 时钟
  - info：「对话 N」14px 500 + preview 12px secondary ellipsis
  - restore btn：28×28 / hover bg `--button-bg` 文字白
  - hover：`bg-hover`，border 变绿，translateX(-2px)

### 4.8 ConfirmDialog

- Overlay：fixed / rgba(0,0,0,0.45) + blur(4px) / z-index 1000
- Container：max 360 / 90% width / border-radius 16 / shadow modal-big / padding 28 24 20 / flex column center
- Icon wrap：56×56 round / `rgba(239,68,68,0.1)` / `28×28` SVG / 颜色 `#EF4444`
- Title：16px 600 / Message：14px secondary / line-height 1.6
- Footer：flex 1 1 / gap 10 / margin-top 4
  - btn-cancel：`--bg-secondary` / border / hover `--bg-hover`
  - btn-confirm：`#EF4444` / 文字白 / hover `#DC2626` + 上移 + 红阴影
- 进入动画：scale(0.92) translateY(8px) → 1, 0.2s

### 4.9 DataAnalysisTree

- Trigger：40×40 / border-radius 8 / `var(--bg-hover)` / active 时 bg `--primary-color` 文字白
- 角标：top 2 right 2 / min 16×16 / 圆角 8 / 10px / bg `--primary-color` / active 时 `rgba(255,255,255,0.35)`
- Panel：absolute top calc(100%+6px) right 0 / 380 × max 520 / border-radius 8 / 1px border / shadow panel / z-index 150
- Header：padding 10 12 / bg `--bg-secondary` / border-bottom / title「📁 数据分析产物」13px 500
- Reload / close icon-btn：24×24 / hover `--bg-hover`
- Empty：「暂无文件」13px secondary / 24 padding

### 4.10 DataTreeNode（递归）

- 缩进：每级 16px / 12px font-size
- 节点：flex row / padding 4 8 / hover `--bg-hover` / 文件右侧 chevron 表示展开

### 4.11 FilePreviewModal

仅用于图片全屏预览：
- Overlay：fixed / rgba(0,0,0,0.9) / z-index 10000 / padding 40 / flex center / fadeIn 0.2s
- Close：36×36 round / rgba(255,255,255,0.1) / hover 0.2 / top -40 right 0
- Img：max 100% × 90vh / object-fit contain / border-radius 8 / scaleIn 0.2s

### 4.12 FilePreviewPanel（右侧抽屉）

- Frame：right slide / 默认 480 / 可拖拽（resize handle 左侧 1px）
- Toolbar：flex row between / 文件信息 + 工具按钮（icon 15×15 / 28×28 round 6 / bg transparent / hover `--bg-hover`）
- Tabs：「原文 / 渲染效果」+ zoom（Mermaid：`− / percent / + / ↺`）
- 内容：图片 / iframe（HTML）/ markdown 渲染 / 文本 / 编辑 textarea

### 4.13 WebPreviewPanel（右侧抽屉）

- 类似 FilePreviewPanel，承载外链 iframe 预览
- Overlay（点击空白关闭）：z-index 99

### 4.14 SettingsDialog

- Overlay：rgba(0,0,0,0.4) / z-index 1500
- Modal：720 × 580（max 92vw/88vh）/ border-radius 12 / shadow panel / flex column
- Header：padding 14 20 / h3「Settings」15px 600 letter-spacing -0.01em / 28×28 close
- Body：flex row / Nav 160px（padding 8 / 2px gap / item 8 12 / 13.5px hover active） + Content padding 24 28
- Footer：flex row between / 12 20 padding / btn-text / btn-primary（主按钮 = `bg=--text-primary, color=--bg-primary`）
- Section：h4 16px 600 / desc 12.5px secondary line-height 1.5
- Group：1px border / 16 18 padding / 14 margin-bottom
- Field：gap 6 / label 12px 500 secondary / input border-radius 6 padding 8 10 / placeholder 0.7 opacity
- Tag：10px uppercase 0.04em / 1px border / 1 6 padding / 圆角 4
- Restart mask：absolute inset 0 / `rgba(255,255,255,0.85)` 或 `rgba(33,33,33,0.85)` / 28×28 spinner（border-top `var(--text-primary)`）+ 「Restarting backend」+ 进度秒数
- flash-tip：fixed bottom 24 left 50% / translateX(-50%) / bg `--text-primary` text `--bg-primary` / 圆角 6 / 13px / z-index 2000 / flash-in 0.2s

---

## 5. 图标系统

全部使用 **inline SVG**，尺寸 13–28px（按容器），统一规范：
- `xmlns="http://www.w3.org/2000/svg"`
- `fill="none"` / `stroke="currentColor"` / `stroke-width="2"` / `stroke-linecap="round"` / `stroke-linejoin="round"`
- 24×24 viewBox，组件级尺寸靠 width/height 控制
- 颜色：跟随父级 `color`（多数为 `--text-secondary`，hover 时 `--button-bg` 或 `--text-primary`）

常用图标清单（path / viewBox 24）：

| 图标 | path |
| --- | --- |
| Hamburger | `<line x1=3 y1=6 x2=21 y2=6/>×3` |
| Refresh（旋转） | `<polyline 23 4 23 10 17 10/>` + `<path M20.49 15a9 9 0 1 1-2.12-9.36L23 10>` |
| Clock | `<circle r=10>` + `<polyline 12 6 12 12 16 14>` |
| Gear | 标准 settings 齿轮（带中心圆 12/12/3） |
| Trash (modal) | `<path M3 6h18 M8 6V4h8v2 M19 6l-1 14H6L5 6/>` + `<line 10 11 14 11/>` |
| X (close) | `<line 18 6 6 18/>` + `<line 6 6 18 18/>` |
| Quote | `<path M9.983 3v7.391 ... M15 ...>` 双引号 |
| Paper clip | `<path M21.44 11.05l-9.19 9.19 ...>` 链状回环 |
| Sparkle | `<circle 12/12/3>` + 八向射线 |
| Stop (interrupt) | `<rect 3 3 18 18 rx 2/>` |
| Replay (restream) | `<path 21 2v6h-6/>` + `<path 12 9 .../>` + `<path 3 22v-6h6/>` + `<path 12 15 .../>` |
| Copy | `<rect 9 9 13 13 rx 2 ry 2/>` + `<path 5 15H4 ...>` |
| Check | `<polyline 20 6 9 17 4 12/>` |
| Play (resume) | `<polygon 5 3 19 12 5 21 5 3/>` |
| Restore (checkpoint) | `<polyline 1 4 1 10 7 10/>` + `<path 3.51 15a9 9 ...>` |
| Optimizer (双圆 + 八向) | `<circle 12 12 3>` + 16 条线 |
| Folder | `<path M3 3h18v4H3z/> × 3` |
| Document | `<path M14 2H6a2 2 ...>` + `<polyline 14 2 14 8 20 8/>` |
| Image | `<rect 3 3 18 18 rx 2 ry 2/>` + `<circle 8.5 8.5 1.5/>` + `<polyline 21 15 16 10 5 21/>` |
| Code (tool) | wrench（path） |
| Upload | `<path 21 15v4 .../>` + `<polyline 17 8 12 3 7 8/>` + `<line 12 3 12 15/>` |
| Drag (拖拽) | `<path 21 15v4 .../>` + `<polyline 17 8 12 3 7 8/>` |
| Download | `<path 21 15v4 .../>` + `<polyline 7 10 12 15 17 10/>` + `<line 12 15 12 3/>` |
| Fullscreen | 4 个角的 `<path>` |
| Eye (show/hide) | 标准眼睛 SVG（实际用文字 Show/Hide 替代） |
| Back (cancel edit) | `<line 19 12 5 12/>` + `<polyline 12 19 5 12 12 5/>` |

数据资产 panel 头部 reload 按钮也用 `M20.49 15...` 这个 path。

---

## 6. 交互模式速查

| 场景 | 规则 |
| --- | --- |
| Hover 显示按钮 | AI 消息 `.action-buttons` 默认 opacity 0，`.ai-wrapper:hover` 时 1 |
| Hover 显示删除 | ConversationItem `.delete-btn` opacity 0，`:hover` 时 1 |
| 复制反馈 | 图标 swap（copy → check），2s 后还原 |
| 流式滚动 | entry 800ms easeInOut → ramp（linear 600ms → easeOut 250ms） → locked 150ms follow；wheel/touch 在 ramp 启动 100ms 后才视为打断 |
| 错误气泡保护 | App.vue `_sessionHadError` Set 控制 messages refresh 跳过 |
| 流式切走 | snapshot 引用同源，SSE 增量写 snapshot；切回 loadConversation 直接走 snapshot 分支 |
| 文件上传 | 拖拽 → window dragenter/over/drop 全局监听 → MessageInput `.drag-overlay` 浮层 |
| Interrupt | interrupt 按钮 → POST `/chat/{sid}/interrupt`；SSE 收到 `interrupt` 事件 → UI 进入中断态 |
| Resume | 中断后显示 `继续` 按钮 → 弹窗输入续接消息（可选）→ POST `/chat/{sid}/invoke_interrupted/{msg}` |
| Restream | 仅最新 AI 消息可点；backtrack API + message_stream SSE |
| Restore | CheckpointPanel 选节点 → ConfirmDialog → backtrack + 静默刷新 |
| 主题切换 | localStorage 写入，dark-theme class toggle，App 全局 CSS 变量同步 |

---

## 7. 响应式 / 移动端

| 元素 | Mobile (≤600px) 调整 |
| --- | --- |
| Sidebar | position fixed / left -260px / z-index 100 / shadow |
| Header | padding 0 12 / h1 17px |
| Hamburger | display flex（桌面隐藏） |
| Messages column | padding 16 12 12 |
| Welcome margin-top | 60 |
| Input area | padding 12 |
| Input wrapper | max-width 100% / gap 8 |
| File list | max-width 100% / margin-bottom 8 |
| Sidebar mobile-open | left 0 + shadow |
| Sidebar overlay | 半透明黑 0.5，点击关闭 |

---

## 8. 资产 / 资源

| 资源 | 路径 / 来源 |
| --- | --- |
| favicon | `/favicon.ico` |
| logo 文字 | 仅「灵析」文本（无图形 logo） |
| App 图标 | `frontend/build/icon.{icns,ico,png}`（打包用，不出现在 UI） |
| highlight.js theme | atom-one-dark（`MessageItem.vue` 引入） |
| KaTeX | `katex/dist/katex.min.css` |
| mermaid | 默认主题，flowchart `{ htmlLabels, curve: 'basis', useMaxWidth: false }` |
| DOMPurify | `frontend/src/utils/sanitize.js`（v-html 注入前过滤） |

---

## 9. Figma 端建议

1. **页面结构（Pages）**
   - 🎨 Cover / Tokens / Themes / Components / Screens / States / Archive
2. **Variables**
   - 颜色：按 §1.1 建 Collection「Colors」，Mode「Light」「Dark」
   - 数字：spacing / radius / size 按 §1.3 / §1.4 建「Numbers」Collection
   - 字符串：font-family、z-index 可文本化
3. **Components**：把 §4 每个组件做成 Component Set，Variants 用 `state`（default / hover / active / disabled / streaming / loading / error）和 `theme`（light / dark）两个轴
4. **Auto Layout**：所有用 flex 的容器在 Figma 里用 Auto Layout，gap、padding 严格对齐 §1.4
5. **Style Connect**：所有阴影 / 圆角 / 颜色全部用 Effect / Corner Radius / Fill Style Connect 到 Variables，避免硬编码
6. **图层命名**：与组件 / 关键 class 保持一致（`.thinking-section` / `.message-content` / `.quote-block-bar` 等），便于 review
7. **Dark mode**：Figma 用 Variables 的 Dark mode 一次切完；不要复制一份 frame
8. **文档组件**：Header / Sidebar / Modal / Panel / Button / Icon button / Bubble / Tool call / Markdown block 各做 1 个组件，所有用到的地方 Instance
9. **文本样式**：建「Display / H1 / H2 / H3 / Body / Body Lg / Caption / Micro / Code」几个 Text Style
10. **Change log**：本文档随 PR 走 git，组件库跟着 PR 走 Figma

---

## 10. 自检 Checklist

新组件 / 新页面设计前过一遍：
- [ ] 颜色全部走 §1.1 token，无硬编码
- [ ] 圆角优先从 §1.3 选最接近的
- [ ] 间距用 §1.4 spacing scale
- [ ] 字号用 §1.2 文本样式
- [ ] 阴影用 §1.5
- [ ] Z-index 在 §1.6 范围
- [ ] 暗色模式肉眼检查（特别注意 hover / active / disabled / error / loading 五态）
- [ ] ≤600px 断点布局存在 fallback
- [ ] 动画使用 §1.7 标准曲线
- [ ] Icon 走 §5 路径，不要新造
- [ ] 与 `frontend/src/components/` 中至少 1 个真实用例对齐（不允许凭空设计）