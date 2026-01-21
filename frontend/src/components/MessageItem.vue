<template>
  <div :class="['message', message.role === 'user' ? 'user-message' : 'ai-message']">
    <div class="message-avatar">
      <span v-if="message.role === 'user'">👤</span>
      <span v-else>🤖</span>
    </div>
    <div class="message-content">
      <div class="message-text">{{ message.content }}</div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'MessageItem',
  props: {
    message: {
      type: Object,
      required: true
    }
  }
}
</script>

<style scoped>
.message {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  width: 100%;
}

.user-message {
  flex-direction: row-reverse;
}

.ai-message {
  justify-content: flex-start;
}


.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.message-content {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 12px;
}

.ai-message .message-content {
  background-color: var(--ai-msg-bg);
  border: 1px solid var(--border-color);
}

.user-message .message-content {
  margin-left: auto;
  background-color: var(--user-msg-bg);
}

.message-text {
  line-height: 1.6;
  white-space: pre-wrap;
  word-wrap: break-word;
}
</style>
