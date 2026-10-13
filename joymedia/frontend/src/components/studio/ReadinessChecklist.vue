<template>
  <section class="rounded-2xl border border-outline-border bg-surface-card p-3.5" data-test="readiness">
    <header class="mb-2 flex items-center justify-between gap-3">
      <h3 class="text-sm font-bold text-ink-primary">
        {{ tr('Before you generate', 'Trước khi tạo video') }}
        <Badge class="ml-1.5" :theme="ready ? 'green' : 'amber'" :label="ready ? tr('Ready', 'Sẵn sàng') : tr('Needs attention', 'Cần xử lý')" />
      </h3>
      <Button size="sm" variant="subtle" :loading="planning.running" :disabled="!hasStory" @click="planScenes">
        {{ tr('Plan scenes with AI', 'AI lập kế hoạch cảnh') }}
      </Button>
    </header>

    <ul class="flex flex-col gap-1.5">
      <li v-for="step in steps" :key="step.key" class="flex items-start gap-2 text-xs" :class="step.key === next ? 'font-semibold' : ''">
        <span :class="{ 'text-emerald-400': step.status === 'done', 'text-amber-400': step.status === 'todo', 'text-ink-muted': step.status === 'note' }">
          {{ step.status === 'done' ? '✓' : step.status === 'todo' ? '•' : 'i' }}
        </span>
        <span class="min-w-0">
          <span class="text-ink-primary">{{ step.label }}</span>
          <span v-if="step.detail" class="block truncate text-ink-muted" :title="step.detail">{{ step.detail }}</span>
        </span>
      </li>
    </ul>

    <div v-if="planning.running || planning.message" class="mt-3">
      <Progress v-if="planning.running" :value="planning.total ? (planning.done / planning.total) * 100 : 5" size="sm"
        :label="planning.total ? `${planning.done}/${planning.total} · ${planning.shot}` : tr('Starting…', 'Đang bắt đầu…')" />
      <Alert v-else :theme="planning.failed ? 'red' : 'green'" :title="planning.message" />
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, watch } from "vue";
import { Alert, Badge, Button, Progress, call, createResource } from "frappe-ui";
import { tr, useI18n } from "../../stores/i18n";
import { useProjectRealtime } from "../../composables/useProjectRealtime";

const props = defineProps({ projectName: { type: String, required: true } });
const { currentLang } = useI18n();
const emit = defineEmits(["changed"]);

const readiness = createResource({
  url: "joymedia.services.project_intake.get_project_readiness",
  params: { project_name: props.projectName, lang: currentLang.value },
  auto: true,
});
// The server translates the step texts; follow the studio's language switch without a reload.
watch(currentLang, (lang) => {
  readiness.update({ params: { project_name: props.projectName, lang } });
  readiness.reload();
});
const steps = computed(() => readiness.data?.steps || []);
const ready = computed(() => Boolean(readiness.data?.ready));
const next = computed(() => readiness.data?.next);
const hasStory = computed(() => steps.value.find((step) => step.key === "story")?.status === "done");

const planning = reactive({ running: false, done: 0, total: 0, shot: "", message: "", failed: false });

// Frappe pushes changes to the project's document room; reload instead of polling.
let reloadTimer = null;
function scheduleReload() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(() => { readiness.reload(); emit("changed"); }, 400);
}

useProjectRealtime(props.projectName, {
  joymedia_project_updated: scheduleReload,
  joymedia_planning_progress: (event) => {
    planning.failed = event.state === "failed";
    planning.running = ["started", "running"].includes(event.state);
    if (event.state === "running") Object.assign(planning, { done: event.done, total: event.total, shot: event.shot_name });
    if (event.state === "done") {
      planning.message = tr(`Planned ${event.total} scene(s). Review them before approving.`, `Đã lập kế hoạch ${event.total} cảnh. Hãy xem lại trước khi duyệt.`);
    }
    if (event.state === "failed") planning.message = event.error;
    if (!planning.running) scheduleReload();
  },
});

async function planScenes() {
  Object.assign(planning, { running: true, done: 0, total: 0, shot: "", message: "", failed: false });
  try {
    await call("joymedia.api.storyboard.start_project_planning", { project_name: props.projectName });
  } catch (err) {
    Object.assign(planning, { running: false, failed: true, message: err?.messages?.[0] || String(err?.message || err) });
  }
}
</script>
