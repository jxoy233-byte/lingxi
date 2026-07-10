<template>
  <div v-if="results && results.length > 0" class="search-results">
    <button class="toggle-button" @click="expanded = !expanded">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        :class="{ rotated: expanded }"
      >
        <polyline points="9 18 15 12 9 6" />
      </svg>
      <span>搜索来源 ({{ results.length }})</span>
    </button>

    <div v-if="expanded" class="results-list">
      <a
        v-for="(result, index) in results"
        :key="index"
        :href="result.url"
        target="_blank"
        rel="noopener noreferrer"
        class="result-item"
      >
        <div class="result-header">
          <span class="result-index">{{ index + 1 }}</span>
          <span class="result-title">{{ result.title || '无标题' }}</span>
        </div>
        <div v-if="result.content" class="result-content">
          {{ truncateContent(result.content, 100) }}
        </div>
        <div class="result-url">{{ result.url }}</div>
      </a>
    </div>
  </div>
</template>

<script>
export default {
  name: 'SearchResults',
  props: {
    results: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      expanded: false
    }
  },
  methods: {
    truncateContent(content, maxLength) {
      if (!content) return ''
      if (content.length <= maxLength) return content
      return content.substring(0, maxLength) + '...'
    }
  }
}
</script>

<style scoped>
.search-results {
  margin: 8px 0;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-secondary);
}

.toggle-button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: background 0.2s;
}

.toggle-button:hover {
  background: var(--bg-hover);
}

.toggle-button svg {
  transition: transform 0.2s;
  color: var(--text-secondary);
  width: 14px;
  height: 14px;
}

.toggle-button svg.rotated {
  transform: rotate(90deg);
}

.results-list {
  border-top: 1px solid var(--border-color);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.result-item {
  display: block;
  padding: 8px 10px;
  border-radius: 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  text-decoration: none;
  color: inherit;
  transition: all 0.2s;
}

.result-item:hover {
  border-color: var(--button-bg);
  background: var(--bg-hover);
}

.result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.result-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--button-bg);
  color: white;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.result-title {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.4;
}

.result-content {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin-bottom: 4px;
}

.result-url {
  font-size: 11px;
  color: var(--button-bg);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
