<template>
  <div class="rio-toast-container" role="region" :aria-label="t('Notifications', 'Thông báo')">
    <!-- Assertive so an error interrupts; the visible stack is the same either way. -->
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="rio-toast-item"
      :class="[`rio-toast-${toast.type}`, toast.closing ? 'rio-toast-closing' : 'rio-toast-visible']"
      :role="toast.type === 'error' ? 'alert' : 'status'"
      :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
      @mouseenter="pause(toast.id)"
      @mouseleave="resume(toast.id)"
      @focusin="pause(toast.id)"
      @focusout="resume(toast.id)"
    >
      <div class="rio-toast-content">
        <div class="rio-toast-icon" aria-hidden="true">
          <svg v-if="toast.type === 'success'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
          <svg v-else-if="toast.type === 'warning'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
          <svg v-else-if="toast.type === 'error'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>
          <svg v-else-if="toast.type === 'process'" class="rio-toast-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6" /><line x1="12" y1="18" x2="12" y2="22" /><line x1="4.93" y1="4.93" x2="7.76" y2="7.76" /><line x1="16.24" y1="16.24" x2="19.07" y2="19.07" /><line x1="2" y1="12" x2="6" y2="12" /><line x1="18" y1="12" x2="22" y2="12" /><line x1="4.93" y1="19.07" x2="7.76" y2="16.24" /><line x1="16.24" y1="7.76" x2="19.07" y2="4.93" /></svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg>
        </div>
        <div class="rio-toast-text-wrap">
          <div class="rio-toast-header">
            <span class="rio-toast-title">{{ toast.title }}</span>
            <button
              v-if="toast.closable"
              type="button"
              class="rio-toast-close"
              :title="t('Dismiss', 'Đóng')"
              :aria-label="`${t('Dismiss', 'Đóng')}: ${toast.title}`"
              @click="close(toast.id)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
          </div>
          <div v-if="toast.message" class="rio-toast-msg">{{ toast.message }}</div>
        </div>
      </div>
      <div v-if="toast.duration > 0" class="rio-toast-progress">
        <div class="rio-toast-progress-bar" :style="{ animationDuration: `${toast.duration}ms` }" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { close, pause, resume, toasts } from "../utils/rioToast";
import { useI18n } from "../stores/i18n";

const { currentLang } = useI18n();
const t = (en, vi) => (currentLang.value === "vi" ? vi : en);
</script>

<style scoped>
.rio-toast-container {
  position: fixed;
  top: 64px;
  right: 24px;
  z-index: 100000;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
  max-width: 440px;
  width: calc(100vw - 48px);
}
.rio-toast-item {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--outline-border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-card) 92%, transparent);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  pointer-events: auto;
  user-select: text;
  transform: translateX(115%);
  opacity: 0;
  transition: transform 0.32s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.32s ease;
}
.rio-toast-item.rio-toast-visible { transform: translateX(0); opacity: 1; }
.rio-toast-item.rio-toast-closing { transform: translateX(115%) scale(0.94); opacity: 0; }
.rio-toast-content { display: flex; gap: 12px; padding: 13px 14px; }
.rio-toast-icon { flex: none; width: 22px; height: 22px; }
.rio-toast-icon svg { width: 100%; height: 100%; }
.rio-toast-text-wrap { min-width: 0; flex: 1; }
.rio-toast-header { display: flex; align-items: center; gap: 10px; }
.rio-toast-title { flex: 1; font-size: 11px; font-weight: 800; letter-spacing: 0.9px; }
.rio-toast-close { flex: none; width: 18px; height: 18px; color: var(--ink-muted); cursor: pointer; }
.rio-toast-close:hover { color: var(--ink-primary); }
.rio-toast-close svg { width: 100%; height: 100%; }
.rio-toast-msg { margin-top: 4px; color: var(--ink-secondary); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.rio-toast-progress { height: 2px; background: rgba(255, 255, 255, 0.07); }
.rio-toast-progress-bar { width: 100%; height: 100%; animation-name: rio-toast-drain; animation-timing-function: linear; animation-fill-mode: forwards; }
/* Hover holds the bar exactly where the dismiss timer stopped. */
.rio-toast-item:hover .rio-toast-progress-bar,
.rio-toast-item:focus-within .rio-toast-progress-bar { animation-play-state: paused; }
@keyframes rio-toast-drain { from { width: 100%; } to { width: 0%; } }
.rio-toast-spin { animation: rio-toast-spin 1.1s linear infinite; }
@keyframes rio-toast-spin { to { transform: rotate(360deg); } }

.rio-toast-info, .rio-toast-process { border-left: 3.5px solid #00f0ff; box-shadow: 0 12px 35px rgba(0, 0, 0, 0.7), 0 0 22px rgba(0, 240, 255, 0.22); }
.rio-toast-info .rio-toast-icon, .rio-toast-info .rio-toast-title,
.rio-toast-process .rio-toast-icon, .rio-toast-process .rio-toast-title { color: #00f0ff; }
.rio-toast-info .rio-toast-progress-bar, .rio-toast-process .rio-toast-progress-bar { background: #00f0ff; box-shadow: 0 0 8px #00f0ff; }
.rio-toast-success { border-left: 3.5px solid #10b981; box-shadow: 0 12px 35px rgba(0, 0, 0, 0.7), 0 0 22px rgba(16, 185, 129, 0.24); }
.rio-toast-success .rio-toast-icon, .rio-toast-success .rio-toast-title { color: #10b981; }
.rio-toast-success .rio-toast-progress-bar { background: #10b981; box-shadow: 0 0 8px #10b981; }
.rio-toast-warning { border-left: 3.5px solid #f59e0b; box-shadow: 0 12px 35px rgba(0, 0, 0, 0.7), 0 0 22px rgba(245, 158, 11, 0.24); }
.rio-toast-warning .rio-toast-icon, .rio-toast-warning .rio-toast-title { color: #f59e0b; }
.rio-toast-warning .rio-toast-progress-bar { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; }
.rio-toast-error { border-left: 3.5px solid #f43f5e; box-shadow: 0 12px 35px rgba(0, 0, 0, 0.7), 0 0 22px rgba(244, 63, 94, 0.26); }
.rio-toast-error .rio-toast-icon, .rio-toast-error .rio-toast-title { color: #f43f5e; }
.rio-toast-error .rio-toast-progress-bar { background: #f43f5e; box-shadow: 0 0 8px #f43f5e; }

@media (max-width: 640px) {
  .rio-toast-container { top: 12px; right: 12px; width: calc(100vw - 24px); }
}
@media (prefers-reduced-motion: reduce) {
  .rio-toast-item { transition: opacity 0.2s ease; transform: none; }
  .rio-toast-item.rio-toast-closing { transform: none; }
  .rio-toast-spin { animation: none; }
}
</style>
