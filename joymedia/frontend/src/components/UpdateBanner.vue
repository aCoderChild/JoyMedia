<template>
  <div v-if="updateAvailable" class="update-banner" role="status">
    <span class="update-dot" aria-hidden="true" />
    <span class="update-text">{{ t("A newer version of the studio is ready.", "Đã có phiên bản mới của studio.") }}</span>
    <button type="button" class="update-reload" @click="reload">{{ t("Reload", "Tải lại") }}</button>
  </div>
</template>

<script setup>
import { useVersionWatch } from "../composables/useVersionWatch";
import { useI18n } from "../stores/i18n";

const { currentLang } = useI18n();
const t = (en, vi) => (currentLang.value === "vi" ? vi : en);
const { updateAvailable, reload } = useVersionWatch();
</script>

<style scoped>
.update-banner {
  position: fixed;
  left: 50%;
  bottom: 20px;
  transform: translateX(-50%);
  z-index: 100002;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 14px;
  border: 1px solid var(--primary-accent, #00f0ff);
  border-radius: 30px;
  background: color-mix(in srgb, var(--surface-card, #0e121a) 94%, transparent);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 10px 34px rgba(0, 0, 0, 0.6), 0 0 20px var(--primary-glow, rgba(0, 240, 255, 0.4));
  color: var(--ink-primary, #eaf7fb);
  font: 12px Inter, system-ui, sans-serif;
}
.update-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: var(--primary-accent, #00f0ff);
  box-shadow: 0 0 9px var(--primary-accent, #00f0ff);
  animation: update-pulse 1.6s ease-in-out infinite;
}
.update-text { white-space: nowrap; }
.update-reload {
  flex: none;
  border: 0;
  border-radius: 20px;
  padding: 5px 13px;
  background: var(--primary-accent, #00f0ff);
  color: var(--primary-on-accent, #04121a);
  font-weight: 700;
  font-size: 12px;
  cursor: pointer;
}
.update-reload:hover { filter: brightness(1.1); }
@keyframes update-pulse { 50% { opacity: 0.4; } }
@media (prefers-reduced-motion: reduce) { .update-dot { animation: none; } }
@media (max-width: 640px) { .update-text { white-space: normal; } }
</style>
