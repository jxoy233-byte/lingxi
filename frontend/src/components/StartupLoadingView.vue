<!--
  StartupLoadingView.vue

  v0.3.x 启动期 waiting 浮层。

  复用 NotFoundView 的像素鹿视觉（16x18 SVG 像素鹿 + 椭圆阴影 + 浮动像素尘埃），
  但场景从「找不到会话 → 跳回主页」反转成「正在等待后端启动 → 准备进入主界面」。

  触发时机：
    - cold start + autoEnter=true：App.vue _autoBootstrap() 启动 → 显示本浮层
    - cold start + autoEnter=false：BootstrapView classic 形态显示（不走本浮层）
    - warm start + autoEnter=true：**仍然显示**本浮层（用户启动 app 时期待「loading」反馈，
      不应该直接跳进主界面给用户带来「闪一下」的突兀感）

  与 NotFoundView 的区别：
    - 进度条方向：NotFoundView 是「10s 倒计时 → 0% → 跳主页」（缩短）；
      StartupLoadingView 是「顺向增长进度条（0% → 100%）」+ 等待秒数
      （增长），表达「正在等待」语义
    - 点击行为：NotFoundView 是「点击立即跳主页」；
      StartupLoadingView 不响应点击（启动流程不应被用户中断，如需中断走主进程 kill）
    - z-index：1500（介于 BootstrapView 1000 和 NotFoundView 1800 之间；
      启动期不与 NotFoundView 共存，因为会话 URL 在初始化后才解析）

  视觉元素复用 NotFoundView 的 .pixel-deer / .pixel-deer-shadow / .pixel-particle 三个
  keyframes（deer-hop 跳跃、deer-shadow-pulse 阴影同步、pixel-float 尘埃升起）。
-->
<template>
  <div class="startup-loading-overlay">
    <div class="startup-loading-card">
      <!-- 像素鹿舞台：复用 NotFoundView 同款 16x18 SVG（鹿朝右 + 跳跃动画） -->
      <div class="pixel-deer-stage" aria-hidden="true">
        <div class="pixel-deer-shadow"></div>
        <div class="pixel-deer-wrap">
          <svg class="pixel-deer" viewBox="0 0 16 18" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
            <!-- 鹿角 5 行：顶尖 2 + 中分枝 + 主体收束（与 NotFoundView 完全一致） -->
            <rect x="8" y="0" width="1" height="1" fill="#f5e6c8"/>
            <rect x="11" y="0" width="1" height="1" fill="#f5e6c8"/>
            <rect x="7" y="1" width="1" height="1" fill="#f5e6c8"/>
            <rect x="8" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="12" y="1" width="1" height="1" fill="#f5e6c8"/>
            <rect x="6" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="13" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="7" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="12" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="4" width="1" height="1" fill="#c9a875"/>
            <!-- 耳（3 像素宽，深棕） -->
            <rect x="8" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="9" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="10" y="5" width="1" height="1" fill="#7a4f2c"/>
            <!-- 头（6 wide） -->
            <rect x="7" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="11" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="12" y="6" width="1" height="1" fill="#a87147"/>
            <!-- 脸：奶油颊 + 眼 + 鼻尖 -->
            <rect x="7" y="7" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="7" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="7" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="7" width="1" height="1" fill="#1a1a1a"/>
            <rect x="11" y="7" width="1" height="1" fill="#1a1a1a"/>
            <rect x="12" y="7" width="1" height="1" fill="#3a2418"/>
            <!-- 下巴 + 鼻尖 -->
            <rect x="7" y="8" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="9" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="11" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="12" y="8" width="1" height="1" fill="#3a2418"/>
            <!-- 颈（窄 + 奶油下划线） -->
            <rect x="8" y="9" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="9" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="9" width="1" height="1" fill="#a87147"/>
            <!-- 肩部 -->
            <rect x="8" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="10" width="1" height="1" fill="#a87147"/>
            <!-- 白尾尖 -->
            <rect x="1" y="10" width="1" height="1" fill="#fff5e1"/>
            <!-- 身体顶 + 尾巴 -->
            <rect x="1" y="11" width="1" height="1" fill="#fff5e1"/>
            <rect x="2" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="4" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="5" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="6" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="7" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="11" width="1" height="1" fill="#a87147"/>
            <!-- 身体 + 奶油腹 -->
            <rect x="2" y="12" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="4" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="5" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="6" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="7" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="8" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="9" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="12" width="1" height="1" fill="#a87147"/>
            <!-- 身体底 -->
            <rect x="2" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="4" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="5" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="6" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="7" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="13" width="1" height="1" fill="#a87147"/>
            <!-- 后腿 -->
            <rect x="2" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="3" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="2" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="17" width="1" height="1" fill="#3a2418"/>
            <rect x="3" y="17" width="1" height="1" fill="#3a2418"/>
            <!-- 前腿 -->
            <rect x="9" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="10" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="9" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="17" width="1" height="1" fill="#3a2418"/>
            <rect x="10" y="17" width="1" height="1" fill="#3a2418"/>
          </svg>
        </div>
        <!-- 浮动像素尘埃（3 个错开延迟） -->
        <div class="pixel-particle pixel-particle--1"></div>
        <div class="pixel-particle pixel-particle--2"></div>
        <div class="pixel-particle pixel-particle--3"></div>
      </div>

      <!-- 文案：与 NotFoundView 反向 —— 「等待启动」而非「找不到会话」 -->
      <div class="startup-loading-title">正在等待后端启动</div>
      <div class="startup-loading-subtitle">{{ subtitleText }}</div>
      <!-- 进度条：表达「正在等待」语义 —— 不倒计时而是顺向增长（0% → 100% over TOTAL_WAIT_SECONDS） -->
      <div class="startup-loading-progress-track">
        <div class="startup-loading-progress-bar" :style="{ width: progressPct + '%' }"></div>
      </div>
      <!-- 等待秒数 + 跳过提示（不响应点击；启动流程不允许中断） -->
      <div class="startup-loading-hint">已等待 {{ elapsedLabel }} 秒</div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'StartupLoadingView',
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    // 已等待秒数（App.vue setInterval 累加）
    elapsed: {
      type: Number,
      default: 0
    },
  },
  // 进度条「顺向增长」语义：120s 满（不是 10s 倒计时）。
  // 120s 是主进程 bootstrap 的上限（startBackend 的 /health poll 120s timeout），
  // 进度条满 = 已等待超过主进程最长允许时间 = 极端异常态（应该早就 ready 或 timeout）。
  data() {
    return {
      TOTAL_WAIT_SECONDS: 120,
    }
  },
  computed: {
    /**
     * 顺向进度条：elapsed / TOTAL_WAIT_SECONDS * 100
     * 与 NotFoundView 的 (remaining / 10) * 100 方向相反 —— 这里是「从 0 长到 100」表等待。
     */
    progressPct() {
      return Math.max(0, Math.min(100, (this.elapsed / this.TOTAL_WAIT_SECONDS) * 100))
    },
    /**
     * 取上界整数显示（10.0 → 10, 9.7 → 10）避免抖动。
     */
    elapsedLabel() {
      return Math.max(0, Math.ceil(this.elapsed))
    },
    /**
     * 不同等待时长给不同提示，让用户知道系统在干啥（不是卡死）：
     * 0-5s    — warm path 或 cold 启动 uv/redis/sandbox 检测
     * 5-30s   — cold uv sync / docker build（首次较慢）
     * 30-120s — cold Python 模型加载（QwenVL 首次加载 weights）
     * 120s+   — 超长警告
     */
    subtitleText() {
      if (this.elapsed < 5) return '后端服务启动中，请稍候…'
      if (this.elapsed < 30) return '首次启动需同步依赖，请稍候…'
      if (this.elapsed < 120) return '正在加载 AI 模型，请稍候…'
      return '启动耗时较长，请检查后端日志或网络'
    },
  },
}
</script>

<style scoped>
/*
 * 视觉风格统一 NotFoundView：fixed fullscreen + 半透明 backdrop + 居中卡片。
 * 卡片宽度 / padding 微调（容纳进度条），z-index 1500 介于 Bootstrap 与 NotFound 之间。
 */
.startup-loading-overlay {
  position: fixed;
  inset: 0;
  z-index: 1500;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: startup-loading-fade-in 0.22s ease-out;
}

.startup-loading-card {
  width: min(420px, 88vw);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  padding: 28px 32px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

/* ===== 像素鹿舞台（与 NotFoundView 同款）===== */
.pixel-deer-stage {
  position: relative;
  width: 128px;
  height: 160px;
  margin: 4px auto 8px;
}

.pixel-deer-wrap {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.pixel-deer {
  width: 100%;
  height: 100%;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  transform-origin: 50% 100%;
  animation: deer-hop 1.4s ease-in-out infinite;
  will-change: transform;
}

.pixel-deer-shadow {
  position: absolute;
  bottom: 2px;
  left: 50%;
  width: 72px;
  height: 8px;
  background: rgba(0, 0, 0, 0.22);
  border-radius: 50%;
  transform: translateX(-50%);
  animation: deer-shadow-pulse 1.4s ease-in-out infinite;
}

/* ===== 浮动像素尘埃（与 NotFoundView 同款）===== */
.pixel-particle {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 0;
  background: var(--text-secondary);
  opacity: 0;
  pointer-events: none;
}
.pixel-particle--1 {
  left: 14px;
  bottom: 18px;
  animation: pixel-float 2.6s ease-in-out infinite;
  animation-delay: 0s;
}
.pixel-particle--2 {
  left: 100px;
  bottom: 32px;
  animation: pixel-float 3.2s ease-in-out infinite;
  animation-delay: 0.8s;
}
.pixel-particle--3 {
  left: 112px;
  bottom: 10px;
  animation: pixel-float 2.8s ease-in-out infinite;
  animation-delay: 1.4s;
}

/* ===== 文案 ===== */
.startup-loading-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
  margin-top: 4px;
}

.startup-loading-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
  line-height: 1.4;
}

/* ===== 进度条 ===== */
.startup-loading-progress-track {
  width: 100%;
  height: 3px;
  background: var(--bg-hover);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 8px;
}

.startup-loading-progress-bar {
  height: 100%;
  background: var(--button-bg);
  transition: width 0.1s linear;
  border-radius: 2px;
}

.startup-loading-hint {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
  opacity: 0.85;
}

/* ===== 动画 keyframes（与 NotFoundView 同款：复用一组 keyframes 是设计意图）===== */
@keyframes deer-hop {
  0%   { transform: translateY(0)     scaleY(0.9)  scaleX(1.06); }
  18%  { transform: translateY(-4px)  scaleY(1)    scaleX(1); }
  50%  { transform: translateY(-18px) scaleY(1.07) scaleX(0.95); }
  82%  { transform: translateY(-4px)  scaleY(1)    scaleX(1); }
  100% { transform: translateY(0)     scaleY(0.9)  scaleX(1.06); }
}

@keyframes deer-shadow-pulse {
  0%, 100% {
    transform: translateX(-50%) scaleX(1);
    opacity: 0.22;
  }
  50% {
    transform: translateX(-50%) scaleX(0.55);
    opacity: 0.1;
  }
}

@keyframes pixel-float {
  0%   { opacity: 0;    transform: translateY(0); }
  15%  { opacity: 0.65; }
  100% { opacity: 0;    transform: translateY(-34px); }
}

@keyframes startup-loading-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

/* ===== 用户偏好减少动效时停掉动画 ===== */
@media (prefers-reduced-motion: reduce) {
  .pixel-deer,
  .pixel-deer-shadow,
  .pixel-particle { animation: none; }
}
</style>
