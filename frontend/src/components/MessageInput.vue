<template>
  <div class="input-area">
    <div class="input-wrapper">
      <textarea
        v-model="inputText"
        @keydown.enter.exact.prevent="handleSend"
        placeholder="输入消息... (Enter发送，Shift+Enter换行)"
        rows="1"
        ref="textarea"
      ></textarea>
      <button
        @click="handleSend"
        :disabled="!inputText.trim() || isLoading"
        class="send-btn"
      >
        发送
      </button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'MessageInput',
  props: {
    isLoading: {
      type: Boolean,
      default: false
    }
  },
  emits: ['send'],
  data() {
    return {
      inputText: ''
    }
  },
  methods: {
    handleSend() {
      if (!this.inputText.trim() || this.isLoading) return

      this.$emit('send', this.inputText.trim())
      this.inputText = ''
    }
  }
}
</script>

<style scoped>
.input-area {
  padding: 20px;
  background-color: var(--bg-primary);
  border-top: 1px solid var(--border-color);
}

.input-wrapper {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-wrapper textarea {
  flex: 1;
  min-height: 52px;
  max-height: 200px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
}

.input-wrapper textarea:focus {
  border-color: var(--button-bg);
}

.send-btn {
  height: 52px;
  padding: 0 24px;
  border: none;
  background: var(--button-bg);
  color: white;
  border-radius: 12px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 500;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: var(--button-hover);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
