# ChatMe Frontend

基于 Vue3 的智能对话前端界面

## 功能特性

✅ **完整功能实现**：
- GPT风格的简约界面设计
- **左AI右用户的对话布局**（AI消息在左侧，用户消息在右侧）
- 深色/浅色主题切换（自动保存用户偏好）
- 实时流式对话响应（SSE）
- 对话历史管理（侧边栏）
- **双击编辑对话标题**（双击标题可编辑）
- **智能时间显示**（实时计算相对时间：分钟、小时、天数）
- **自动生成标题**（取对话前5个字）
- 新建、查看、删除对话
- 自动滚动到最新消息
- **组件化架构**（解耦合，易扩展）
- 响应式布局

## 快速开始

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

前端将运行在 `http://localhost:5173`

### 3. 构建生产版本

```bash
npm run build
```

## 使用说明

1. **启动后端服务**：确保后端服务已在 `http://127.0.0.1:8211` 运行
   ```bash
   cd ../src
   python main.py
   ```

2. **访问应用**：打开浏览器访问 `http://localhost:5173`

3. **开始对话**：
   - 点击"+ 新对话"创建新会话
   - 在输入框输入消息，按Enter发送
   - Shift+Enter可以换行
   - AI回复会实时流式显示

4. **管理对话**：
   - 左侧边栏显示历史对话列表
   - 点击对话项可切换到该会话
   - 悬停在对话上会显示删除按钮
   - 点击"×"删除对话

5. **切换主题**：
   - 点击右上角的主题切换按钮（☀️/🌙）
   - 主题偏好会自动保存到浏览器

## 技术栈

- **Vue 3** - 渐进式JavaScript框架
- **Vite** - 下一代前端构建工具
- **原生JavaScript** - 无额外UI库依赖
- **CSS Variables** - 主题切换实现

## 项目结构

```
frontend/
├── index.html              # HTML入口
├── package.json            # 项目依赖
├── vite.config.js          # Vite配置（包含API代理）
└── src/
    ├── main.js             # 应用入口
    ├── App.vue             # 主应用组件
    └── components/         # 组件目录
        ├── Sidebar.vue           # 侧边栏（对话列表）
        ├── ConversationItem.vue  # 单个对话项
        ├── ChatHeader.vue        # 聊天头部
        ├── MessageList.vue       # 消息列表容器
        ├── MessageItem.vue       # 单条消息
        └── MessageInput.vue      # 消息输入框
```

## 组件说明

- **App.vue**: 主应用容器，管理全局状态和数据流
- **Sidebar.vue**: 侧边栏组件，显示对话列表
- **ConversationItem.vue**: 单个对话项，支持双击编辑标题、显示相对时间
- **ChatHeader.vue**: 聊天区域头部，包含主题切换按钮
- **MessageList.vue**: 消息列表容器，管理消息滚动
- **MessageItem.vue**: 单条消息组件，区分AI和用户消息
- **MessageInput.vue**: 消息输入框，支持Enter发送

## API接口说明

前端通过Vite代理连接到后端API（`/chat/*` -> `http://127.0.0.1:8211/chat/*`）：

- `POST /chat/` - 发送消息（流式响应）
- `GET /chat/conversations` - 获取对话列表
- `GET /chat/{session_id}` - 获取对话详情
- `DELETE /chat/{session_id}/clear` - 删除对话

## 注意事项

- 确保后端Redis服务正常运行（端口6388）
- 确保`.env`文件配置正确（OpenAI API密钥等）
- 首次对话时会自动创建session_id
- 对话历史存储在Redis中，刷新页面不会丢失
