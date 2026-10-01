<template>
  <div class="scene-strip-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <!-- Storyboard Header -->
    <div class="flex items-center justify-between mb-2.5 px-1">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>🎞️</span>
          <span>{{ currentLang === 'vi' ? 'Storyboard Phân cảnh' : 'Storyboard' }}</span>
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ shots.length }} {{ currentLang === 'vi' ? 'Cảnh' : 'Shots' }} · {{ totalDurationSeconds }}s
        </span>
        <button
          type="button"
          class="hidden sm:inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md font-semibold bg-surface-muted text-ink-secondary border border-outline-border cursor-pointer hover:border-indigo-400 transition-colors"
          :title="currentLang === 'vi' ? 'Bấm để đổi chế độ nối cảnh' : 'Click to toggle continuity mode'"
          @click="$emit('toggleContinuityMode')"
        >
          <span>{{ generationMode === 'Continuous' ? '🔗 Continuous (Chained)' : '⧉ Multi-shot' }}</span>
        </button>
      </div>

      <!-- Right Actions: AI Storyboard Revision & New Version -->
      <div class="flex items-center gap-2">
        <button
          v-if="hasStoryboard"
          type="button"
          class="text-xs font-semibold text-indigo-400 hover:text-indigo-300 px-2.5 py-1 rounded-xl bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-xs"
          :disabled="isRevising || isGenerating"
          :title="currentLang === 'vi' ? 'AI viết lại cấu trúc kịch bản' : 'Revise storyboard with AI'"
          @click="$emit('reviseStoryboard')"
        >
          <span v-if="isRevising" class="lucide-refresh-cw size-3 animate-spin" />
          <span v-else>✨</span>
          <span>{{ currentLang === 'vi' ? 'Cập nhật kịch bản ✦' : 'Revise with AI ✦' }}</span>
        </button>
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
        <span class="text-indigo-400 font-mono font-semibold">
          {{ completedShotsCount }} / {{ shots.length || expectedShotCount }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes ready' }}
        </span>
      </div>

      <!-- Shot Progress Indicators -->
      <div class="flex items-center gap-1.5 overflow-x-auto">
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

    <!-- CapCut / Flow Filmstrip Shots Track -->
    <div v-if="shots.length" class="capcut-track flex items-stretch gap-2 overflow-x-auto pb-2">
      <template v-for="(shot, index) in shots" :key="shot.name || shot.shot_number || index">
        <!-- Shot Card Item -->
        <div
          class="capcut-clip flex-1 shrink-0 rounded-xl border p-2 transition-all cursor-pointer bg-surface-muted select-none flex flex-col justify-between"
          :class="[
            selectedShotIndex === index && selectedTarget !== 'asset'
              ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/30'
              : 'border-outline-border hover:border-indigo-400'
          ]"
          :style="{ minWidth: '150px', maxWidth: '240px' }"
          draggable="true"
          @dragstart="onDragStart(shot, index, $event)"
          @dragover.prevent
          @drop.prevent="onDrop(shot, index)"
          @click="$emit('selectShot', shot, index)"
        >
          <!-- Clip Header (Scene # & Duration Trim) -->
          <div class="flex items-center justify-between text-[11px] font-bold text-ink-primary mb-1.5">
            <span class="truncate">Cảnh {{ shot.shot_number }}</span>
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="capcut-trim-button"
                :title="currentLang === 'vi' ? 'Giảm 0,5s' : 'Trim 0.5s'"
                @click.stop="$emit('changeShotDuration', shot, -0.5)"
              >
                −
              </button>
              <span class="text-ink-muted font-mono text-[10px] min-w-[30px] text-center">
                {{ estimateShotDuration(shot) }}s
              </span>
              <button
                type="button"
                class="capcut-trim-button"
                :title="currentLang === 'vi' ? 'Tăng 0,5s' : 'Extend 0.5s'"
                @click.stop="$emit('changeShotDuration', shot, 0.5)"
              >
                +
              </button>
            </div>
          </div>

          <!-- Thumbnail Visual Body -->
          <div class="relative w-full aspect-video rounded-lg overflow-hidden bg-black flex items-center justify-center">
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

          <!-- Keyframe Track Nodes (Start & End) -->
          <div class="capcut-keyframe-track-lane mt-2 pt-1 border-t border-outline-border/60 relative flex items-center justify-between px-1">
            <!-- Connecting Line -->
            <div class="absolute left-2 right-2 h-[2px] bg-outline-border rounded-full" />

            <!-- Start Keyframe Reference Node -->
            <button
              type="button"
              class="capcut-kf-node relative z-10 cursor-pointer transition-transform hover:scale-125"
              :class="{
                'is-active': selectedTarget === 'keyframe-start' && selectedShotIndex === index,
                'is-shot-active': selectedShotIndex === index
              }"
              :title="`Start Reference: ${formatShotKeyframeTime(index, 0)}`"
              @click.stop="$emit('selectKeyframe', shot, index, 'start')"
            >
              <span class="capcut-kf-diamond capcut-kf-in" />
              <span class="capcut-kf-time-badge">Start</span>
            </button>

            <!-- End Keyframe Reference Node -->
            <button
              type="button"
              class="capcut-kf-node relative z-10 cursor-pointer transition-transform hover:scale-125"
              :class="{
                'is-active': selectedTarget === 'keyframe-end' && selectedShotIndex === index,
                'is-shot-active': selectedShotIndex === index
              }"
              :title="`End Reference: ${formatShotKeyframeTime(index, 1)}`"
              @click.stop="$emit('selectKeyframe', shot, index, 'end')"
            >
              <span
                class="capcut-kf-diamond"
                :class="shot.last_frame_image || generationMode === 'Continuous' ? 'capcut-kf-out-set' : 'capcut-kf-out-empty'"
              />
              <span class="capcut-kf-time-badge">{{ generationMode === 'Continuous' ? 'Continuity' : 'End' }}</span>
            </button>
          </div>
        </div>

        <!-- Transition Node Between Shots -->
        <div v-if="index < shots.length - 1" class="capcut-transition-node self-center shrink-0">
          <button
            type="button"
            class="capcut-transition-pill"
            :title="generationMode === 'Continuous' ? 'Continuous chained cut' : 'Multi-shot independent cut'"
            @click="$emit('toggleContinuityMode')"
          >
            <span>{{ generationMode === 'Continuous' ? '⫸' : '⧉' }}</span>
          </button>
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
  expectedShotCount: { type: Number, default: 4 },
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
