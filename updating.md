## 更新内容

### 后端更新任务
- 更新了对文本和文档文件文件的处理的功能 (文档待办ing)
- 更新了带有搜索引擎功能的graph 
- 更新updated_at字段存放在config的additional_kwargs配置中,这样应该可以解决没有正常显示对话更新时间距离现在的问题（√）
- 对于传入文件数据，对后端的Conversation进行拓展变量来保存，使得前端每次对话进入仍可以显示上传过的文件(todo) ***使用additional_kwargs传入每一段对话的文件显示，如果传入了的话，否则置为None***

### 前端更新任务
- *增加Markdown语法渲染*
- 前端的输入消息框改为 Ctrl + Enter 换行
- 增加对话中直接文本复制功能，类似gpt那样的的对话复制
- 前端文件显示功能对文件预览显示的大小再进行缩小一点
- 前端页面每次进入不同对话时进入chat/{session_id}页面，新页面则回到/chat中
- 在前端网页更新了不同session_id不同对话页之后，对于发送信息完成后不要调用/chat/conversations接口,而是直接调用当前页面的chat/{session_id}/conversation接口


### 共同任务
- 后端接口的获取对话消息变成了/chat/{session_id}/conversation(已更正)
- 增加可以中断消息发送功能（待办...）
