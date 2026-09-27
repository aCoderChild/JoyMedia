<template>
  <div v-if="loading" class="flex-1 min-h-[calc(100vh-52px)] flex items-center justify-center bg-surface-base text-ink-muted text-sm">
    <span class="lucide-refresh-cw size-5 animate-spin mr-2" />
    {{ currentLang === 'vi' ? 'Đang mở Studio…' : 'Opening Studio…' }}
  </div>
  <TimelineEditor v-else-if="timeline?.ready" :key="timelineKey" :initial-timeline="timeline" />
  <ProjectDetail v-else />
</template>

<script setup>
import { call } from "frappe-ui";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "../stores/i18n";
import ProjectDetail from "./ProjectDetail.vue";
import TimelineEditor from "./TimelineEditor.vue";

const { currentLang } = useI18n();
const route = useRoute();
const projectName = computed(() => route.params.name);
const loading = ref(true);
const timeline = ref(null);
let readinessTimer = null;

const timelineKey = computed(() => `${projectName.value}-${timeline.value?.media_specification || 'timeline'}`);

async function checkTimeline() {
  try {
    const result = await call("joymedia.services.timeline_editor.get_project_timeline", {
      project_name: projectName.value,
      create_if_possible: true,
    });
    timeline.value = result;
    if (result?.ready && readinessTimer) {
      clearInterval(readinessTimer);
      readinessTimer = null;
    }
  } catch (_) {
    // During rollout, or before `bench migrate`, keep the existing planner UI
    // available instead of making the project page unusable.
    timeline.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await checkTimeline();
  if (!timeline.value?.ready) {
    readinessTimer = setInterval(checkTimeline, 6000);
  }
});

onBeforeUnmount(() => {
  if (readinessTimer) clearInterval(readinessTimer);
});
</script>
