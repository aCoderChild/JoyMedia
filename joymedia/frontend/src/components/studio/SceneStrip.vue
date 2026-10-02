<template>
  <div class="scene-strip-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <!-- Storyboard Header -->
    <div class="flex items-center justify-between mb-2.5 px-1 flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>🎞️</span>
          <span>{{ currentLang === 'vi' ? 'Storyboard Phân cảnh' : 'Storyboard' }}</span>
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ totalDurationSeconds }}s
        </span>
      </div>

      <!-- Right Actions: Lightweight AI Director revision prompt -->
      <div v-if="hasStoryboard" class="flex items-center gap-2">
        <form class="flex items-center gap-1.5" @submit.prevent="submitAiRevision">
          <div class="relative flex items-center">
            <span class="absolute left-2.5 text-xs text-indigo-400">✨</span>
            <input
              v-model="aiRevisionInput"
              type="text"
              :placeholder="currentLang === 'vi' ? 'Hỏi AI Director sửa kịch bản... (vd: sang trọng hơn)' : 'Ask AI Director... (e.g. Make it more luxurious)'"
              class="bg-surface-muted border border-outline-border focus:border-indigo-500 rounded-xl pl-7 pr-3 py-1 text-xs text-ink-primary placeholder:text-ink-muted w-48 sm:w-72 focus:outline-none transition-all"
              :disabled="isRevising || isGenerating"
            />
          </div>
          <button
            type="submit"
            class="px-3 py-1 rounded-xl text-xs font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition-all cursor-pointer shadow-xs disabled:opacity-50"
            :disabled="isRevising || isGenerating"
          >
            <span v-if="isRevising" class="lucide-refresh-cw size-3 animate-spin inline-block" />
            <span v-else>{{ currentLang === 'vi' ? 'Áp dụng' : 'Apply' }}</span>
          </button>
        </form>
      </div>
    </div>

    <!-- Active Clean Generation Progress (Only when generating - Shots oriented) -->
    <div
      v-if="isGenerating"
      class="mb-3 p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-between gap-3 text-xs"
    >
      <div class="flex items-center gap-2 min-w-0">
        <span class="lucide-refresh-cw size-3.5 text-indigo-400 animate-spin shrink-0" />
        <span class="font-bold text-ink-primary">
          {{ currentLang === 'vi' ? 'Đang tạo video:' : 'Generating video:' }}
        </span>
        <span v-if="shots.length || expectedShotCount" class="text-indigo-400 font-mono font-semibold">
          {{ completedShotsCount }} / {{ shots.length || expectedShotCount }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes ready' }}
        </span>
        <span v-else class="text-indigo-400 font-mono font-semibold">
          {{ currentLang === 'vi' ? 'Đang lập storyboard…' : 'Planning storyboard…' }}
        </span>
      </div>

      <!-- Shot Progress Indicators -->
      <div v-if="shots.length || expectedShotCount" class="flex items-center gap-1.5 overflow-x-auto">
        <span
          v-for="(shot, idx) in (shots.length ? shots : expectedShotCount)"
          :key="idx"
          class="text-[10px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0"
          :class="getShotBadgeClass(shot, idx)"
        >
          <span>{{ getShotStatusGlyph(shot, idx) }}</span>
          <span>S{{ idx + 1 }}</span>
        </span>
      </div>
    </div>

    <!-- Simplified Flow / OpenSlop Storyboard Shots Track -->
    <div v-if="shots.length" class="capcut-track flex items-stretch gap-2.5 overflow-x-auto pb-2">
      <template v-for="(shot, index) in shots" :key="shot.name || shot.shot_number || index">
        <!-- Simplified Shot Card Item -->
        <div
          class="capcut-clip flex-1 shrink-0 rounded-2xl border p-2.5 transition-all cursor-pointer bg-surface-muted select-none flex flex-col justify-between"
          :class="[
            selectedShotIndex === index && selectedTarget !== 'asset'
              ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/30'
              : 'border-outline-border hover:border-indigo-400'
          ]"
          :style="{ minWidth: '175px', maxWidth: '240px' }"
          draggable="true"
          @dragstart="onDragStart(shot, index, $event)"
          @dragover.prevent
          @drop.prevent="onDrop(shot, index)"
          @click="$emit('selectShot', shot, index)"
        >
          <!-- Top: Thumbnail / Video Preview -->
          <div class="relative w-full aspect-video rounded-xl overflow-hidden bg-black flex items-center justify-center mb-2">
            <MediaThumbnail
              :src="getShotVideoFile(shot) || getShotFirstFrame(shot)?.file || shot.reference_image"
              :media-type="getShotVideoFile(shot) ? 'Video' : 'Image'"
              :poster="getShotFirstFrame(shot)?.file || shot.last_frame_image"
              :alt="`Shot ${shot.shot_number}`"
              :duration="estimateShotDuration(shot)"
              aspect="aspect-video"
            />

            <!-- In-progress state overlay -->
            <div
              v-if="isGenerating && getShotState(shot) !== 'Ready'"
              class="absolute inset-0 bg-black/60 flex flex-col items-center justify-center text-center p-1"
            >
              <span v-if="getShotState(shot) === 'Generating'" class="text-xs text-indigo-400 font-bold animate-pulse">
                ● {{ currentLang === 'vi' ? 'Đang tạo' : 'Generating' }}
              </span>
              <span v-else class="text-[10px] text-zinc-400 font-mono">
                ○ {{ currentLang === 'vi' ? 'Đang chờ' : 'Waiting' }}
              </span>
            </div>
          </div>

          <!-- Middle: Scene Title & Clean Duration -->
          <div class="flex items-center justify-between text-xs font-bold text-ink-primary mb-1">
            <span class="truncate">{{ currentLang === 'vi' ? `Cảnh ${shot.shot_number}` : `Scene ${shot.shot_number}` }}</span>
            <span class="text-ink-secondary font-mono text-[11px] font-semibold bg-surface-card px-1.5 py-0.5 rounded border border-outline-border/60">
              {{ estimateShotDuration(shot) }}s
            </span>
          </div>

          <!-- Creative summary snippet -->
          <p class="text-[11px] text-ink-secondary line-clamp-2 leading-relaxed mb-2 min-h-[30px]">
            {{ shot.generation_prompt || (currentLang === 'vi' ? 'Cảnh giới thiệu sản phẩm' : 'Product showcase') }}
          </p>

          <!-- Bottom: Role Badge & Edit Scene action button -->
          <div class="flex items-center justify-between pt-1.5 border-t border-outline-border/60 text-xs">
            <span class="text-[10px] text-ink-muted truncate font-medium max-w-[110px]">
              {{ shot.reference_role ? `@ ${shot.reference_role}` : 'Product · Studio' }}
            </span>
            <button
              type="button"
              class="px-2 py-0.5 rounded-lg text-[10.5px] font-semibold text-indigo-400 hover:text-indigo-300 hover:bg-surface-hover flex items-center gap-1 cursor-pointer transition-colors"
              :title="currentLang === 'vi' ? 'Chỉnh sửa cảnh' : 'Edit Scene'"
              @click.stop="$emit('selectShot', shot, index)"
            >
              <span>⋯</span>
              <span>{{ currentLang === 'vi' ? 'Sửa' : 'Edit' }}</span>
            </button>
          </div>
        </div>

        <!-- Clean Cut indicator between shots -->
        <div v-if="index < shots.length - 1" class="self-center shrink-0 text-ink-muted text-xs opacity-60">
          |
        </div>
      </template>
    </div>

    <!-- Empty Storyboard State -->
    <div v-else class="text-center py-6 text-xs text-ink-muted">
      {{ currentLang === 'vi' ? 'Nhập ý tưởng video bên trên và bấm Tạo Video để sinh phân cảnh tự động.' : 'Enter your video idea above and click Generate Video to create storyboard scenes.' }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import MediaThumbnail from "../MediaThumbnail.vue";

const props = defineProps({
  shots: { type: Array, default: () => [] },
  selectedShotIndex: { type: Number, default: 0 },
  selectedTarget: { type: String, default: "scene" },
  generationMode: { type: String, default: "Multi-shot" },
  totalDurationSeconds: { type: [Number, String], default: 15 },
  hasStoryboard: { type: Boolean, default: false },
  isGenerating: { type: Boolean, default: false },
  isRevising: { type: Boolean, default: false },
  expectedShotCount: { type: Number, default: 0 },
  production: { type: Object, default: null },
  currentLang: { type: String, default: "en" },
  estimateShotDuration: { type: Function, default: (s) => s?.duration_seconds || 5 },
  formatShotKeyframeTime: { type: Function, default: () => "0.0s" },
  getShotVideoFile: { type: Function, default: () => "" },
  getShotFirstFrame: { type: Function, default: () => ({}) },
});

const emit = defineEmits([
  "selectShot",
  "selectKeyframe",
  "changeShotDuration",
  "toggleContinuityMode",
  "reviseStoryboard",
  "reorderShots",
]);

const aiRevisionInput = ref("");

function submitAiRevision() {
  if (!aiRevisionInput.value?.trim()) {
    emit("reviseStoryboard");
    return;
  }
  emit("reviseStoryboard", aiRevisionInput.value.trim());
  aiRevisionInput.value = "";
}

const draggedIndex = ref(null);

function onDragStart(shot, index, event) {
  draggedIndex.value = index;
  event.dataTransfer.effectAllowed = "move";
}

function onDrop(shot, index) {
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    emit("reorderShots", draggedIndex.value, index);
  }
  draggedIndex.value = null;
}

const completedShotsCount = computed(() => {
  if (!props.shots?.length) return 0;
  return props.shots.filter((s) => Boolean(props.getShotVideoFile(s))).length;
});

function getShotState(shot) {
  if (props.getShotVideoFile(shot)) return "Ready";
  if (props.isGenerating) {
    return "Generating";
  }
  return "Waiting";
}

function getShotBadgeClass(shot, idx) {
  const ready = typeof shot === "object" && props.getShotVideoFile(shot);
  if (ready) return "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
  if (props.isGenerating && idx === completedShotsCount.value) {
    return "bg-indigo-500/20 text-indigo-400 border border-indigo-500/40 animate-pulse";
  }
  return "bg-surface-muted text-ink-muted border border-outline-border";
}

function getShotStatusGlyph(shot, idx) {
  const ready = typeof shot === "object" && props.getShotVideoFile(shot);
  if (ready) return "✓";
  if (props.isGenerating && idx === completedShotsCount.value) return "●";
  return "○";
}
</script>
