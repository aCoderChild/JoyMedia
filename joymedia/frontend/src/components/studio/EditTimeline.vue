<template>
  <div class="edit-timeline-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <div class="flex items-center justify-between mb-2.5 px-1">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>✂️</span>
          <span>{{ currentLang === 'vi' ? 'Trình dựng Video (Edit Timeline)' : 'Edit Timeline' }}</span>
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ activeVideoClips.length }} {{ currentLang === 'vi' ? 'video' : 'video' }} · {{ totalSeconds?.toFixed(1) || 0 }}s
        </span>
      </div>

      <div class="flex items-center gap-2 text-xs">
        <span class="text-[11px] text-ink-muted">
          {{ currentLang === 'vi' ? 'Bấm clip để chỉnh sửa In/Out, tách hoặc chuyển cảnh trong Inspector.' : 'Click clip to adjust In/Out, split, or transitions in Inspector.' }}
        </span>
        <label class="timeline-zoom-control">
          <span>－</span>
          <input v-model.number="zoom" type="range" min="0.6" max="3" step="0.1" />
          <span>＋</span>
        </label>
        <button type="button" class="timeline-history-btn" :disabled="!canUndo || busy" @click="$emit('undo')">↶ Undo</button>
        <button type="button" class="timeline-history-btn" :disabled="!canRedo || busy" @click="$emit('redo')">↷ Redo</button>
      </div>
    </div>

    <div class="timeline-shared-scroll rounded-xl border border-outline-border bg-surface-muted/40 p-2">
      <div class="timeline-shared-canvas space-y-3" :style="{ width: `${timelineCanvasWidth}px` }">
        <div>
          <div class="flex items-center gap-2 mb-1 px-1">
            <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1.5">
              <span>🎬</span>
              <span>Visuals</span>
              <span class="text-ink-secondary text-[9px] font-semibold border-l border-outline-border pl-1">Video</span>
            </span>
            <span class="text-[11px] text-ink-secondary">
              {{ activeVideoClips.length }} {{ currentLang === 'vi' ? 'phân đoạn hình ảnh' : 'video scenes' }}
            </span>
          </div>

          <EditTimelineTrack
            :clips="activeVideoClips"
            :all-clips="clips"
            :fps="fps"
            :pixels-per-frame="pixelsPerFrame"
            :timeline-canvas-width="timelineCanvasWidth"
            :selected-clip-name="selectedClipName"
            :playhead-frame="playheadFrame"
            :busy="busy"
            :total-frames="canvasTotalFrames || totalFrames"
            :total-seconds="(canvasTotalFrames || totalFrames) / (fps || 24)"
            :current-lang="currentLang"
            @select-clip="forwardSelectClip"
            @update:playhead-frame="$emit('update:playheadFrame', $event)"
            @trim="$emit('trim', $event)"
            @split="$emit('split', $event)"
            @duplicate="$emit('duplicate', $event)"
            @delete="$emit('delete', $event)"
            @reorder="$emit('reorder', $event)"
            @select-transition="$emit('selectTransition', $event)"
            @open-inspector="forwardOpenInspector"
          />
        </div>

      <AudioTimelineTracks
        :audio-clips="activeAudioClips"
        :video-clips="activeVideoClips"
        :fps="fps"
        :selected-clip-name="selectedClipName"
        :total-frames="totalFrames"
        :pixels-per-frame="pixelsPerFrame"
        :timeline-canvas-width="timelineCanvasWidth"
        :current-lang="currentLang"
        @select-clip="forwardSelectClip"
        @open-inspector="forwardOpenInspector"
        @trim="$emit('trim', $event)"
        @move="$emit('move', $event)"
        @set-audio-clip-enabled="forwardSetAudioClipEnabled"
        @open-audio-picker="$emit('openAudioPicker')"
      />

        <div class="flex justify-end pt-1">
          <button
            type="button"
            class="rounded-xl border border-dashed border-indigo-500/50 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-400 hover:bg-indigo-500/20 cursor-pointer"
            @click="$emit('addScene')"
          >
            + {{ currentLang === 'vi' ? 'Thêm cảnh' : 'Add Scene' }}
          </button>
        </div>

        <div
          class="timeline-global-playhead"
          :style="{ left: `${playheadFrame * pixelsPerFrame}px` }"
          aria-hidden="true"
        >
          <span class="timeline-global-playhead-head" />
        </div>
        <div
          v-if="renderTotalFrames < canvasTotalFrames"
          class="timeline-outside-render"
          :style="{ left: `${renderTotalFrames * pixelsPerFrame}px` }"
          aria-hidden="true"
        >
          <span>{{ currentLang === 'vi' ? 'KẾT THÚC VIDEO' : 'END OF VIDEO' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import AudioTimelineTracks from "./AudioTimelineTracks.vue";
import EditTimelineTrack from "./EditTimelineTrack.vue";

const props = defineProps({
  clips: { type: Array, default: () => [] },
  videoClips: { type: Array, default: () => [] },
  audioClips: { type: Array, default: () => [] },
  fps: { type: Number, default: 24 },
  selectedClipName: { type: String, default: null },
  playheadFrame: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
  totalFrames: { type: Number, default: 0 },
  totalSeconds: { type: Number, default: 0 },
  canvasTotalFrames: { type: Number, default: 0 },
  renderTotalFrames: { type: Number, default: 0 },
  canUndo: { type: Boolean, default: false },
  canRedo: { type: Boolean, default: false },
  audioTrackAsset: { type: Object, default: null },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits([
  "selectClip",
  "update:playheadFrame",
  "trim",
  "split",
  "duplicate",
  "delete",
  "reorder",
  "move",
  "selectTransition",
  "openInspector",
  "openAudioPicker",
  "setAudioClipEnabled",
  "undo",
  "redo",
]);

const zoom = ref(1);

const activeVideoClips = computed(() => {
  if (props.videoClips?.length) return props.videoClips;
  return (props.clips || []).filter((clip) => (clip.track_type || "Video") === "Video");
});

const activeAudioClips = computed(() => {
  if (props.audioClips?.length) return props.audioClips;
  return (props.clips || []).filter((clip) => clip.track_type === "Audio");
});

const pixelsPerFrame = computed(() => Math.max(2, (36 * zoom.value) / Math.max(1, props.fps || 24)));
const canvasFrames = computed(() => Number(props.canvasTotalFrames || props.totalFrames || 0));
const timelineCanvasWidth = computed(() => Math.max(700, canvasFrames.value * pixelsPerFrame.value));

function handleHistoryShortcut(event) {
  const target = event.target;
  if (target?.matches?.("input, textarea, select, [contenteditable='true']")) return;
  if (!(event.metaKey || event.ctrlKey)) return;
  const key = event.key.toLowerCase();
  if (key === "y" || (key === "z" && event.shiftKey)) {
    event.preventDefault();
    emit("redo");
    return;
  }
  if (key !== "z") return;
  event.preventDefault();
  emit("undo");
}

onMounted(() => window.addEventListener("keydown", handleHistoryShortcut));
onBeforeUnmount(() => window.removeEventListener("keydown", handleHistoryShortcut));

function forwardSelectClip(...args) {
  emit("selectClip", ...args);
}

function forwardOpenInspector(clip) {
  emit("openInspector", clip);
}

function forwardSetAudioClipEnabled(...args) {
  emit("setAudioClipEnabled", ...args);
}
</script>
