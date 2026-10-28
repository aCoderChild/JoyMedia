<template>
  <section class="stages" data-test="project-stages" :aria-label="t('What the system is doing', 'Hệ thống đang làm gì')">
    <button type="button" class="stages-summary" :aria-expanded="open" @click="open = !open">
      <span class="stages-dot" :class="`is-${current?.state || 'waiting'}`" aria-hidden="true" />
      <strong>{{ current ? current.label : t('Progress', 'Tiến độ') }}</strong>
      <span class="stages-detail">{{ current?.detail }}</span>
      <span v-if="current?.percent !== undefined" class="stages-pct">{{ current.percent }}%</span>
      <span v-if="current?.etaMinutes !== undefined" class="stages-eta">{{ etaLabel(current.etaMinutes) }}</span>
      <span class="stages-chevron" aria-hidden="true">{{ open ? '▴' : '▾' }}</span>
    </button>

    <ol v-if="open" class="stages-list">
      <li v-for="stage in stages" :key="stage.key" :class="`is-${stage.state}`">
        <span class="stages-mark" aria-hidden="true">{{ mark(stage.state) }}</span>
        <span class="stages-body">
          <strong>{{ stage.label }}</strong>
          <span class="stages-line">
            {{ stage.detail }}
            <template v-if="stage.percent !== undefined"> · {{ stage.percent }}%</template>
            <template v-if="stage.etaMinutes !== undefined"> · {{ etaLabel(stage.etaMinutes) }}</template>
          </span>
          <!-- A stopped or retried stage always says why. -->
          <span v-if="stage.reason" class="stages-reason">{{ stage.reason }}</span>
        </span>
        <span class="stages-state">{{ stateLabel(stage.state) }}</span>
      </li>
    </ol>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { buildStages, currentStage } from "../../utils/projectStages";

const props = defineProps({
  project: { type: Object, default: () => ({}) },
  production: { type: Object, default: null },
  shots: { type: Array, default: () => [] },
  assets: { type: Array, default: () => [] },
  frames: { type: Array, default: () => [] },
  currentLang: { type: String, default: "vi" },
});

const open = ref(false);
const t = (en, vi) => (props.currentLang === "vi" ? vi : en);

const stages = computed(() =>
  buildStages({
    project: props.project,
    production: props.production,
    shots: props.shots,
    assets: props.assets,
    frames: props.frames,
    lang: props.currentLang,
  }),
);
const current = computed(() => currentStage(stages.value));

function mark(state) {
  return { done: "✓", running: "●", review: "!", attention: "!", waiting: "·" }[state] || "·";
}
function stateLabel(state) {
  return {
    done: t("Done", "Xong"),
    running: t("Working", "Đang chạy"),
    review: t("Your turn", "Chờ bạn"),
    attention: t("Needs attention", "Cần xử lý"),
    waiting: t("Waiting", "Đang chờ"),
  }[state] || "";
}
function etaLabel(minutes) {
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return t(`about ${hours}h ${minutes % 60}m left`, `còn khoảng ${hours} giờ ${minutes % 60} phút`);
  }
  return t(`about ${minutes} min left`, `còn khoảng ${minutes} phút`);
}
</script>

<style scoped>
.stages { flex: none; border-bottom: 1px solid var(--outline-border, #22293d); background: #080d13; color: #d6e6ee; font-size: 12px; }
.stages-summary { display: flex; align-items: center; gap: 9px; width: 100%; padding: 7px 14px; background: none; border: 0; color: inherit; text-align: left; cursor: pointer; }
.stages-summary:hover { background: #0b1520; }
.stages-summary strong { white-space: nowrap; }
.stages-detail { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #8fa8b6; }
.stages-pct, .stages-eta { white-space: nowrap; color: #00f0ff; font-variant-numeric: tabular-nums; }
.stages-chevron { color: #64748b; }
.stages-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: #64748b; }
.stages-dot.is-running { background: #00f0ff; box-shadow: 0 0 9px #00f0ff; animation: stages-pulse 1.6s ease-in-out infinite; }
.stages-dot.is-done { background: #10b981; }
.stages-dot.is-review { background: #f59e0b; }
.stages-dot.is-attention { background: #f43f5e; box-shadow: 0 0 9px #f43f5e; }
@keyframes stages-pulse { 50% { opacity: 0.35; } }

.stages-list { margin: 0; padding: 2px 14px 10px; list-style: none; display: flex; flex-direction: column; gap: 2px; }
.stages-list li { display: flex; align-items: flex-start; gap: 9px; padding: 5px 0; border-top: 1px solid #141b26; }
.stages-mark { width: 14px; flex: none; text-align: center; color: #64748b; }
.stages-list li.is-done .stages-mark { color: #10b981; }
.stages-list li.is-running .stages-mark { color: #00f0ff; }
.stages-list li.is-review .stages-mark { color: #f59e0b; }
.stages-list li.is-attention .stages-mark { color: #f43f5e; }
.stages-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.stages-line { color: #8fa8b6; }
.stages-reason { color: #ffb8be; }
.stages-state { flex: none; color: #64748b; font-size: 11px; }
.stages-list li.is-attention .stages-state { color: #f43f5e; }
.stages-list li.is-review .stages-state { color: #f59e0b; }

@media (prefers-reduced-motion: reduce) { .stages-dot.is-running { animation: none; } }
</style>
