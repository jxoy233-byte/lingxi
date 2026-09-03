<!--
  NotFoundView.vue

  访问到不存在的 URL（hash 格式不合法 / 后端 404）时显示的浮层：
  - 全屏半透明 backdrop + 居中卡片
  - 像素鹿 SVG + 跳跃动画（translateY + squash/stretch，阴影同步缩放）
  - 标题 + 副标题 + 进度条 + 倒计时文案，点击立即跳主页

  Props:
    remaining: number  剩余秒数（父组件 100ms tick 驱动）

  Emits:
    click-anywhere  用户点击浮层任意位置（包括卡片本身 + 卡片外部 backdrop）
                   App.vue 收到后跳转主页

  ====== 像素鹿设计（16x18 viewBox，鹿朝右）======
  垂直比例（高辨识度鹿的关键）：
  - 鹿角 5 行（顶尖 2 + 中分枝 + 主体收束），占整高 28%
  - 头 + 耳 4 行（耳 3 像素宽 → 辨识「耳在角下」）
  - 颈 2 行（窄 → 显得身体纤细）
  - 身体 3 行（水平延展 9 列，奶油腹 7 像素宽）
  - 腿 4 行（腿高 = 身体的 1.33x，是真鹿的标志）
  - 白色尾尖 2 像素（垂直贴在身体最左端）
-->
<template>
  <div class="not-found-overlay" @click="$emit('click-anywhere')">
    <div class="not-found-card" @click.stop="$emit('click-anywhere')">
      <!-- 像素鹿舞台：SVG 鹿 + 阴影 + 浮动像素尘埃 -->
      <div class="pixel-deer-stage" aria-hidden="true">
        <div class="pixel-deer-shadow"></div>
        <div class="pixel-deer-wrap">
          <!--
            16x18 viewBox；每个 viewBox 单位 = 8 CSS px（128x144 鹿 + 16px 跳跃空间 = 128x160 舞台）。
            shape-rendering: crispEdges + image-rendering: pixelated 保证像素锐利。
          -->
          <svg class="pixel-deer" viewBox="0 0 16 18" xmlns="http://www.w3.org/2000/svg">
            <!-- ===== Antlers: 5 行，V 形分叉 + 收束基座 ===== -->
            <!-- 顶尖 (cream) -->
            <rect x="8" y="0" width="1" height="1" fill="#f5e6c8"/>
            <rect x="11" y="0" width="1" height="1" fill="#f5e6c8"/>
            <!-- 第 1 层分枝：左右外尖 + 中间 4 个深色（鹿角主梁投影） -->
            <rect x="7" y="1" width="1" height="1" fill="#f5e6c8"/>
            <rect x="8" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="12" y="1" width="1" height="1" fill="#f5e6c8"/>
            <!-- 第 2 层分枝：左右更外的尖（鹿角最宽点） -->
            <rect x="6" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="13" y="2" width="1" height="1" fill="#c9a875"/>
            <!-- 鹿角主梁收束 -->
            <rect x="7" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="12" y="3" width="1" height="1" fill="#c9a875"/>
            <!-- 主梁最窄（接近头部） -->
            <rect x="8" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="4" width="1" height="1" fill="#c9a875"/>

            <!-- ===== Ear (3 像素宽，深棕) ===== -->
            <rect x="8" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="9" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="10" y="5" width="1" height="1" fill="#7a4f2c"/>

            <!-- ===== Head top (6 wide) ===== -->
            <rect x="7" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="11" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="12" y="6" width="1" height="1" fill="#a87147"/>

            <!-- ===== Face: cheek cream + eye + dark nose tip ===== -->
            <rect x="7" y="7" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="7" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="7" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="7" width="1" height="1" fill="#1a1a1a"/>
            <rect x="11" y="7" width="1" height="1" fill="#1a1a1a"/>
            <rect x="12" y="7" width="1" height="1" fill="#3a2418"/>

            <!-- ===== Snout/jaw: 奶油下巴 + 鼻尖延伸 ===== -->
            <rect x="7" y="8" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="9" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="11" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="12" y="8" width="1" height="1" fill="#3a2418"/>

            <!-- ===== Neck (narrow, cream underline) ===== -->
            <rect x="8" y="9" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="9" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="9" width="1" height="1" fill="#a87147"/>

            <!-- ===== Shoulder widens to support body ===== -->
            <rect x="8" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="10" width="1" height="1" fill="#a87147"/>
            <!-- 白尾尖：垂直 2 像素，紧贴身体最左端 -->
            <rect x="1" y="10" width="1" height="1" fill="#fff5e1"/>

            <!-- ===== Body top + tail ===== -->
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

            <!-- ===== Body w/ cream belly (7 wide) ===== -->
            <rect x="2" y="12" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="4" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="5" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="6" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="7" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="8" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="9" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="12" width="1" height="1" fill="#a87147"/>

            <!-- ===== Body bottom ===== -->
            <rect x="2" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="4" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="5" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="6" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="7" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="13" width="1" height="1" fill="#a87147"/>

            <!-- ===== Legs (4 行，腿:身体 = 4:3 ≈ 1.33:1 — 真鹿标志) ===== -->
            <!-- 后腿 (cols 2-3, 在臀下) -->
            <rect x="2" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="3" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="2" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="17" width="1" height="1" fill="#3a2418"/>
            <rect x="3" y="17" width="1" height="1" fill="#3a2418"/>

            <!-- 前腿 (cols 9-10, 在肩下) -->
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
        <!-- 浮动像素尘埃：3 个错开延迟的小方块升起，渲染像素风"扬尘" -->
        <div class="pixel-particle pixel-particle--1"></div>
        <div class="pixel-particle pixel-particle--2"></div>
        <div class="pixel-particle pixel-particle--3"></div>
      </div>
      <div class="not-found-title">找不到该会话</div>
      <div class="not-found-subtitle">该链接已失效或会话不存在</div>
      <div class="not-found-progress-track">
        <div class="not-found-progress-bar" :style="{ width: progressPct + '%' }"></div>
      </div>
      <div class="not-found-hint">{{ countdownLabel }} 秒后自动返回主页 · 点击立即返回</div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'NotFoundView',
  props: {
    // 父组件 100ms tick 倒计的剩余秒数；驱动进度条 + 文案
    remaining: { type: Number, default: 10 }
  },
  emits: ['click-anywhere'],
  computed: {
    progressPct() {
      // 10s 总长，进度条从 100% → 0% 平滑收缩
      return Math.max(0, Math.min(100, (this.remaining / 10) * 100))
    },
    countdownLabel() {
      // 取上界整数（10.0 → 10, 9.7 → 10, 9.3 → 10, ...）不抖动
      return Math.max(0, Math.ceil(this.remaining))
    }
  }
}
</script>

<style scoped>
.not-found-overlay {
  position: fixed;
  inset: 0;
  /* 高于 BootstrapView (1000) 和 SetupView (1500) 和 SettingsDialog (1500)，确保盖住所有浮层 */
  z-index: 1800;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 半透明 backdrop：让用户看到原界面被遮住，强化「这是个状态变化」的信号 */
  background: rgba(0, 0, 0, 0.45);
  cursor: pointer;
}

.not-found-card {
  /* 居中卡片：min(380px, 88vw) 适配移动端 */
  width: min(380px, 88vw);
  background: var(--bg-primary);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  padding: 28px 32px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  /* 主题色边界：让卡片在暗色 / 亮色主题下都有清晰边界 */
  border: 1px solid var(--border-color);
}

/* ===== 像素鹿舞台 ===== */
.pixel-deer-stage {
  /* 16x18 viewBox × 8 CSS px = 128x144 鹿 + 16px 跳跃空间 = 128x160 舞台 */
  position: relative;
  width: 128px;
  height: 160px;
  margin: 4px auto 8px;
}

.pixel-deer-wrap {
  /* 把 SVG 钉在舞台底部；translateY 只动它不动舞台尺寸，舞台底部固定为「地面」 */
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.pixel-deer {
  /* SVG 撑满 wrap —— 128x144 → 每个 viewBox 单位 = 8 CSS px，pixelated 锐利 */
  width: 100%;
  height: 100%;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  shape-rendering: crispEdges;
  /* squash/stretch 锚点：底部中心（脚着地点）；translateY 上跳，scaleY 压扁/拉伸 */
  transform-origin: 50% 100%;
  animation: deer-hop 1.4s ease-in-out infinite;
  /* 提示 GPU 合成，让 transform 动画走 compositor */
  will-change: transform;
}

.pixel-deer-shadow {
  /* 椭圆阴影钉在舞台底部，鹿跳起来时阴影变小变淡（高度感） */
  position: absolute;
  bottom: 2px;
  left: 50%;
  /* 腿跨 col 2-3 与 9-10，跨距 8 列 ≈ 64px；阴影略宽让视觉更稳 */
  width: 72px;
  height: 8px;
  background: rgba(0, 0, 0, 0.22);
  border-radius: 50%;
  transform: translateX(-50%);
  animation: deer-shadow-pulse 1.4s ease-in-out infinite;
}

/* ===== 浮动像素尘埃 ===== */
.pixel-particle {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 0;
  /* 用主题色：亮 / 暗主题都能看清 */
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

/* ===== 鹿跳跃：translateY + squash/stretch 5 段关键帧 ===== */
@keyframes deer-hop {
  /* 落地：垂直压扁 + 水平外扩（脚着地冲击） */
  0%   { transform: translateY(0)     scaleY(0.9)  scaleX(1.06); }
  /* 起跳离地：拉回正方形 */
  18%  { transform: translateY(-4px)  scaleY(1)    scaleX(1); }
  /* 顶点：垂直拉伸 + 水平收紧（空中姿态） */
  50%  { transform: translateY(-18px) scaleY(1.07) scaleX(0.95); }
  /* 下落回到拉伸回正 */
  82%  { transform: translateY(-4px)  scaleY(1)    scaleX(1); }
  /* 再次落地：压扁 */
  100% { transform: translateY(0)     scaleY(0.9)  scaleX(1.06); }
}

/* ===== 阴影同步：鹿最高时阴影最小最淡 ===== */
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

/* ===== 浮动像素：从下方升起 + 渐隐 ===== */
@keyframes pixel-float {
  0%   { opacity: 0;    transform: translateY(0); }
  15%  { opacity: 0.65; }
  100% { opacity: 0;    transform: translateY(-34px); }
}

/* ===== 文字 ===== */
.not-found-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
  margin-top: 4px;
}

.not-found-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
  line-height: 1.4;
}

/* ===== 进度条 ===== */
.not-found-progress-track {
  width: 100%;
  height: 3px;
  background: var(--bg-hover);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 8px;
}

.not-found-progress-bar {
  height: 100%;
  background: var(--button-bg);
  /* transition 让宽度变化平滑（100ms tick 之间过渡），避免阶跃 */
  transition: width 0.1s linear;
  border-radius: 2px;
}

.not-found-hint {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
  opacity: 0.85;
}

/* —— 进场过渡（与 App.vue 的 <transition name="not-found-fade"> 对应） —— */
.not-found-fade-enter-active,
.not-found-fade-leave-active {
  transition: opacity 0.18s ease;
}
.not-found-fade-enter-from,
.not-found-fade-leave-to {
  opacity: 0;
}

/* 移动端：卡片稍小 + 鹿舞台缩放，避免在小屏挤压文字 */
@media (max-width: 480px) {
  .not-found-card {
    padding: 22px 22px 20px;
  }
  .pixel-deer-stage {
    transform: scale(0.78);
    transform-origin: center top;
  }
}

/* ===== 可访问性：用户偏好减少动效时停掉所有 CSS 动画 ===== */
@media (prefers-reduced-motion: reduce) {
  .pixel-deer,
  .pixel-deer-shadow,
  .pixel-particle {
    animation: none;
  }
}
</style>