<template>
  <div class="edit-timeline-track-shell">
    <div class="timeline-heading">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
          <span>🎞️</span>
          <span>{{ currentLang === 'vi' ? 'DÒNG THỜI GIAN EDIT' : 'EDIT TIMELINE' }}</span>
        </span>
        <span class="timeline-meta">{{ clips.length }} {{ currentLang === 'vi' ? 'clip' : 'clips' }} · {{ durationLabel }}</span>
      </div>

      <div class="flex items-center gap-1.5 flex-wrap">
        <button
          type="button"
          class="tool-btn"
          :disabled="!canSplit || busy"
          :title="currentLang === 'vi' ? 'Tách clip tại playhead' : 'Split clip at playhead'"
          @click="splitAtPlayhead"
        >
          ✂ {{ currentLang === 'vi' ? 'Tách' : 'Split' }}
        </button>
        <button
          type="button"
          class="tool-btn"
          :disabled="!selectedClip || busy"
          :title="currentLang === 'vi' ? 'Nhân đôi clip đang chọn' : 'Duplicate selected clip'"
          @click="duplicateSelected"
        >
          ⧉ {{ currentLang === 'vi' ? 'Nhân đôi' : 'Duplicate' }}
        </button>
        <button
          type="button"
          class="tool-btn danger"
          :disabled="!selectedClip || busy"
          :title="currentLang === 'vi' ? 'Xóa clip khỏi timeline' : 'Delete clip from timeline'"
          @click="deleteSelected"
        >
          ⌫ {{ currentLang === 'vi' ? 'Xóa' : 'Delete' }}
        </button>
        <button
          type="button"
          class="tool-btn"
          :class="{ active: snapping }"
          :title="currentLang === 'vi' ? 'Bật/tắt hít vào điểm mốc' : 'Toggle snapping'"
          @click="snapping = !snapping"
        >
          ⌁ {{ currentLang === 'vi' ? 'Hút' : 'Snap' }}
        </button>
        <label class="zoom-control">
          <span>－</span>
          <input v-model.number="zoom" type="range" min="0.6" max="3" step="0.1" />
          <span>＋</span>
        </label>
      </div>
    </div>

    <!-- Timeline Ruler -->
    <div
      ref="ruler"
      class="timeline-ruler"
      :style="{ width: `${timelineCanvasWidth}px` }"
      @click="seekTimeline"
    >
      <div class="ruler-labels">
        <span
          v-for="tick in rulerTicks"
          :key="tick.frame"
          :style="{ left: `${tick.frame * pixelsPerFrame}px` }"
        >
          {{ tick.label }}
        </span>
      </div>
      <div class="playhead" :style="{ left: `${playheadFrame * pixelsPerFrame}px` }">
        <span class="playhead-head" />
      </div>
    </div>

    <!-- Clip Track -->
    <div v-if="clips.length" class="clip-track">
      <div class="timeline-canvas" :style="{ width: `${timelineCanvasWidth}px` }">
        <template v-for="(clip, index) in clips" :key="clip.name">
          <article
            class="timeline-clip"
            :class="{ selected: selectedClip?.name === clip.name }"
            :style="clipStyle(clip)"
            draggable="true"
            @dragstart="onDragStart(clip, $event)"
            @dragover.prevent
            @drop.prevent="onDrop(index)"
            @click="onSelectClip(clip)"
          >
            <button
              type="button"
              class="trim-handle trim-handle-left"
              aria-label="Trim start"
              @pointerdown.stop="startTrim(clip, 'left', $event)"
            />
            <button
              type="button"
              class="trim-handle trim-handle-right"
              aria-label="Trim end"
              @pointerdown.stop="startTrim(clip, 'right', $event)"
            />
            <div class="clip-title-row">
              <span class="truncate">{{ clipLabel(clip) }}</span>
              <span class="font-mono text-[9px] text-ink-muted">{{ seconds(clip.duration_frames).toFixed(2) }}s</span>
            </div>
            <div class="clip-filmstrip">
              <video
                v-if="clip.source_file"
                :src="clip.source_file"
                muted
                preload="metadata"
                class="clip-thumb"
              />
              <div v-else class="clip-thumb-empty">{{ clip.clip_order }}</div>
              <div class="clip-frame-overlay">
                <span>IN {{ clip.source_in_frame }}</span>
                <span>OUT {{ clip.source_out_frame }}</span>
              </div>
            </div>
            <div class="clip-range">
              <span>{{ frameTime(clip.timeline_start_frame) }}</span>
              <span>{{ frameTime(clip.timeline_end_frame) }}</span>
            </div>
          </article>

          <!-- Transition node between clips -->
          <button
            v-if="index < clips.length - 1"
            type="button"
            class="transition-node"
            :class="{ active: clip.transition_to_next !== 'Cut' }"
            :style="{ left: `${clip.timeline_end_frame * pixelsPerFrame}px` }"
            :title="transitionTitle(clip)"
            @click.stop="onSelectTransition(clip)"
          >
            {{ clip.transition_to_next === 'Cut' ? '│' : '◇' }}
          </button>
        </template>
      </div>
    </div>
    <div v-else class="empty-timeline">
      {{ currentLang === 'vi' ? 'Chưa có clip trên timeline để chỉnh sửa.' : 'No clips on the timeline for editing.' }}
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "../../stores/i18n";

const props = defineProps({
  clips: { type: Array, default: () => [] },
  fps: { type: Number, default: 24 },
  selectedClipName: { type: String, default: null },
  playheadFrame: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
  totalFrames: { type: Number, default: 0 },
  totalSeconds: { type: Number, default: 0 },
});

const emit = defineEmits([
  "select-clip",
  "update:playhead-frame",
  "trim",
  "split",
  "duplicate",
  "delete",
  "reorder",
  "select-transition",
]);

const { currentLang } = useI18n();
const ruler = ref(null);
const zoom = ref(1);
const snapping = ref(true);
const draggedClipName = ref(null);
const trimDrag = ref(null);

const activeFps = computed(() => Number(props.fps || 24));
const selectedClip = computed(() =>
  props.clips.find((clip) => clip.name === props.selectedClipName) || props.clips[0] || null
);

const activeClip = computed(() =>
  props.clips.find(
    (clip) =>
      props.playheadFrame > clip.timeline_start_frame &&
      props.playheadFrame < clip.timeline_end_frame
  ) || null
);

const canSplit = computed(() => Boolean(activeClip.value));

const effectiveTotalFrames = computed(() => {
  if (props.totalFrames) return props.totalFrames;
  if (!props.clips.length) return 0;
  const last = props.clips[props.clips.length - 1];
  return last.timeline_end_frame || 0;
});

const durationLabel = computed(() => {
  const secondsVal = props.totalSeconds || (effectiveTotalFrames.value / activeFps.value);
  return `${Number(secondsVal || 0).toFixed(2)}s`;
});

const pixelsPerFrame = computed(() => Math.max(2, (36 * zoom.value) / Math.max(1, activeFps.value)));
const timelineCanvasWidth = computed(() => Math.max(700, Number(effectiveTotalFrames.value || 0) * pixelsPerFrame.value));

const rulerTicks = computed(() => {
  const total = Number(effectiveTotalFrames.value || 0);
  if (!total || !activeFps.value) return [{ frame: 0, label: "00:00" }];
  const totalSec = total / activeFps.value;
  const targetTicks = 6;
  const rawStep = totalSec / targetTicks;
  const candidates = [0.5, 1, 2, 5, 10, 15, 30, 60];
  const step = candidates.find((value) => value >= rawStep) || 60;
  const values = [];
  for (let s = 0; s <= totalSec + 0.0001; s += step) {
    const frame = Math.min(total, Math.round(s * activeFps.value));
    values.push({ frame, label: secondsTime(s) });
  }
  if (values[values.length - 1]?.frame !== total) {
    values.push({ frame: total, label: secondsTime(totalSec) });
  }
  return values;
});

function seconds(frameCount) {
  return activeFps.value ? Number(frameCount || 0) / activeFps.value : 0;
}

function secondsTime(value) {
  const total = Math.max(0, Number(value || 0));
  const minutes = Math.floor(total / 60);
  const secs = Math.floor(total % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function frameTime(frameCount) {
  if (!activeFps.value) return "00:00";
  const frames = Math.max(0, Math.round(Number(frameCount || 0)));
  const wholeSeconds = Math.floor(frames / activeFps.value);
  const minutes = Math.floor(wholeSeconds / 60);
  const secs = wholeSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function clipLabel(clip) {
  if (!clip) return "Clip";
  if (clip.shot_number) return currentLang.value === "vi" ? `Cảnh ${clip.shot_number}` : `Shot ${clip.shot_number}`;
  return `Clip ${clip.clip_order}`;
}

function clipStyle(clip) {
  return {
    left: `${clip.timeline_start_frame * pixelsPerFrame.value}px`,
    width: `${Math.max(48, clip.duration_frames * pixelsPerFrame.value)}px`,
  };
}

function transitionTitle(clip) {
  if (clip.transition_to_next === "Cut") return currentLang.value === "vi" ? "Cắt thẳng" : "Cut";
  return `${clip.transition_to_next} · ${clip.transition_frames}f`;
}

function onSelectClip(clip, sourceFrame = null) {
  emit("select-clip", clip, sourceFrame);
}

function onSelectTransition(clip) {
  emit("select-transition", clip);
}

function onDragStart(clip, event) {
  draggedClipName.value = clip.name;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
  }
}

function onDrop(targetIndex) {
  const name = draggedClipName.value;
  draggedClipName.value = null;
  if (!name) return;
  const clip = props.clips.find((item) => item.name === name);
  if (!clip) return;
  emit("reorder", clip, targetIndex + 1);
}

function splitAtPlayhead() {
  const clip = activeClip.value;
  if (!clip) return;
  const local = Math.max(1, Math.min(clip.duration_frames - 1, props.playheadFrame - clip.timeline_start_frame));
  const splitSourceFrame = clip.source_in_frame + local;
  emit("split", clip, splitSourceFrame);
}

function duplicateSelected() {
  if (!selectedClip.value) return;
  emit("duplicate", selectedClip.value);
}

function deleteSelected() {
  if (!selectedClip.value) return;
  emit("delete", selectedClip.value);
}

function seekTimeline(event) {
  if (!ruler.value || !props.clips.length) return;
  const rect = ruler.value.getBoundingClientRect();
  const percent = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const target = Math.round(percent * Number(effectiveTotalFrames.value || 0));
  emit("update:playhead-frame", target);

  const clip = props.clips.find(
    (item) => target >= item.timeline_start_frame && target < item.timeline_end_frame
  ) || props.clips[props.clips.length - 1];

  if (clip) {
    const local = Math.max(0, Math.min(clip.duration_frames - 1, target - clip.timeline_start_frame));
    emit("select-clip", clip, clip.source_in_frame + local);
  }
}

function snapFrame(frame, clipName) {
  if (!snapping.value) return Math.round(frame);
  const rounded = Math.round(frame);
  const candidates = [0, Number(props.playheadFrame || 0)];
  props.clips.forEach((clip) => {
    if (clip.name !== clipName) {
      candidates.push(Number(clip.timeline_start_frame), Number(clip.timeline_end_frame));
    }
  });
  const nearest = candidates
    .map((candidate) => ({ candidate, distance: Math.abs(candidate - rounded) }))
    .filter((item) => item.distance <= 3)
    .sort((a, b) => a.distance - b.distance)[0];
  return nearest == null ? rounded : nearest.candidate;
}

function startTrim(clip, edge, event) {
  if (props.busy || !clip) return;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  trimDrag.value = {
    clipName: clip.name,
    edge,
    startX: event.clientX,
    originalIn: Number(clip.source_in_frame),
    originalOut: Number(clip.source_out_frame),
    originalTimelineStart: Number(clip.timeline_start_frame),
    originalTimelineEnd: Number(clip.timeline_end_frame),
    currentIn: Number(clip.source_in_frame),
    currentOut: Number(clip.source_out_frame),
  };
  window.addEventListener("pointermove", handleTrimMove);
  window.addEventListener("pointerup", finishTrim);
}

function handleTrimMove(event) {
  const drag = trimDrag.value;
  const clip = props.clips.find((item) => item.name === drag?.clipName);
  if (!drag || !clip) return;

  const delta = Math.round((event.clientX - drag.startX) / pixelsPerFrame.value);
  const edgeFrame = drag.edge === "left" ? drag.originalTimelineStart : drag.originalTimelineEnd;
  const timelineDelta = snapFrame(edgeFrame + delta, clip.name) - edgeFrame;
  const minDuration = Math.max(1, Number(clip.min_duration_frames || Math.round(activeFps.value * 0.25)));
  const sourceMax = Number(clip.source_total_frames || drag.originalOut);

  drag.currentIn = drag.edge === "left"
    ? Math.max(0, Math.min(drag.originalOut - minDuration, drag.originalIn + timelineDelta))
    : drag.originalIn;
  drag.currentOut = drag.edge === "right"
    ? Math.min(sourceMax, Math.max(drag.originalIn + minDuration, drag.originalOut + timelineDelta))
    : drag.originalOut;
}

function finishTrim() {
  const drag = trimDrag.value;
  trimDrag.value = null;
  window.removeEventListener("pointermove", handleTrimMove);
  window.removeEventListener("pointerup", finishTrim);
  if (!drag) return;
  const clip = props.clips.find((item) => item.name === drag.clipName);
  if (!clip) return;
  if (drag.currentIn === drag.originalIn && drag.currentOut === drag.originalOut) {
    return;
  }
  emit("trim", clip, drag.currentIn, drag.currentOut);
}

onBeforeUnmount(() => {
  window.removeEventListener("pointermove", handleTrimMove);
  window.removeEventListener("pointerup", finishTrim);
});
</script>

<style scoped>
.edit-timeline-track-shell {
  width: 100%;
  padding: 10px;
  background: var(--surface-card, #fff);
  border: 1px solid var(--outline-border, #e4e7ec);
  border-radius: 14px;
  box-shadow: 0 1px 2px rgb(15 23 42 / 4%);
  overflow-x: auto;
}
.timeline-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 32px;
}
.timeline-meta {
  font: 700 10px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #6366f1;
  background: var(--surface-muted, #f2f4f7);
  border: 1px solid var(--outline-border, #e4e7ec);
  border-radius: 999px;
  padding: 2px 7px;
}
.tool-btn {
  padding: 4px 8px;
  border: 1px solid var(--outline-border, #e4e7ec);
  border-radius: 7px;
  background: var(--surface-muted, #f2f4f7);
  font-size: 10.5px;
  font-weight: 700;
  color: var(--ink-secondary, #4b5565);
  cursor: pointer;
  transition: all .15s;
}
.tool-btn:hover:not(:disabled), .tool-btn.active {
  border-color: #818cf8;
  color: #4f46e5;
  background: #eef2ff;
}
.tool-btn.danger:hover:not(:disabled) {
  border-color: #fb7185;
  color: #e11d48;
  background: #fff1f2;
}
.tool-btn:disabled {
  opacity: .4;
  cursor: not-allowed;
}
.zoom-control {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border: 1px solid var(--outline-border, #e4e7ec);
  border-radius: 7px;
  color: var(--ink-muted, #8790a3);
  font-size: 11px;
}
.zoom-control input {
  width: 58px;
  accent-color: #6366f1;
}
.timeline-ruler {
  position: relative;
  height: 30px;
  margin: 6px 0 4px;
  cursor: crosshair;
  border-bottom: 1px solid var(--outline-border, #e4e7ec);
}
.ruler-labels {
  position: absolute;
  inset: 0;
}
.ruler-labels span {
  position: absolute;
  top: 2px;
  transform: translateX(-50%);
  font: 9px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--ink-muted, #8b93a7);
}
.ruler-labels span::after {
  content: "";
  display: block;
  width: 1px;
  height: 8px;
  background: var(--outline-border, #d7dce5);
  margin: 2px auto 0;
}
.playhead {
  position: absolute;
  top: 0;
  bottom: -122px;
  width: 1.5px;
  background: #6366f1;
  z-index: 10;
  pointer-events: none;
}
.playhead-head {
  position: absolute;
  top: -1px;
  left: -4px;
  width: 9px;
  height: 9px;
  border-radius: 2px 2px 5px 5px;
  background: #6366f1;
}
.clip-track {
  min-height: 112px;
  overflow: visible;
  padding: 4px 0 8px;
}
.timeline-canvas {
  position: relative;
  min-height: 112px;
}
.timeline-clip {
  position: absolute;
  top: 4px;
  bottom: 8px;
  border: 1px solid var(--outline-border, #dfe3ea);
  border-radius: 9px;
  padding: 6px;
  background: var(--surface-muted, #f5f6f9);
  cursor: pointer;
  transition: border-color .12s, box-shadow .12s;
}
.timeline-clip:hover {
  border-color: #a5b4fc;
}
.timeline-clip.selected {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgb(99 102 241 / 15%);
  background: rgb(99 102 241 / 4%);
}
.clip-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 5px;
  height: 18px;
  font-size: 10px;
  font-weight: 800;
}
.clip-filmstrip {
  position: relative;
  height: 58px;
  border-radius: 6px;
  overflow: hidden;
  background: #0b0d12;
}
.clip-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
}
.clip-thumb-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7d8493;
}
.clip-frame-overlay {
  position: absolute;
  inset: auto 4px 3px;
  display: flex;
  justify-content: space-between;
  color: white;
  font: 8px ui-monospace, SFMono-Regular, Menlo, monospace;
  text-shadow: 0 1px 4px black;
}
.clip-range {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  color: var(--ink-muted, #8790a3);
  font: 8px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.transition-node {
  position: absolute;
  top: 42px;
  transform: translateX(-50%);
  width: 26px;
  height: 26px;
  z-index: 3;
  border-radius: 999px;
  border: 1px solid var(--outline-border, #dfe3ea);
  background: var(--surface-card, #fff);
  color: var(--ink-muted, #8790a3);
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all .15s;
}
.transition-node:hover {
  border-color: #818cf8;
  color: #4f46e5;
  background: #eef2ff;
}
.transition-node.active {
  border-color: #818cf8;
  color: #6366f1;
  background: #eef2ff;
}
.trim-handle {
  position: absolute;
  top: 20px;
  bottom: 20px;
  width: 7px;
  z-index: 4;
  border: 0;
  border-radius: 4px;
  background: rgb(99 102 241 / 75%);
  opacity: 0;
  cursor: ew-resize;
  transition: opacity .15s;
}
.timeline-clip:hover .trim-handle, .timeline-clip.selected .trim-handle {
  opacity: 1;
}
.trim-handle-left {
  left: 1px;
}
.trim-handle-right {
  right: 1px;
}
.empty-timeline {
  padding: 28px;
  text-align: center;
  color: var(--ink-muted, #8790a3);
  font-size: 11px;
}
</style>
