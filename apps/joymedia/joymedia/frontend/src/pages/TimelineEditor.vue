<template>
  <div class="timeline-editor-page">
    <main class="timeline-main">
      <header class="editor-topbar">
        <div class="min-w-0">
          <button type="button" class="back-link" @click="goBack">← {{ currentLang === 'vi' ? 'Chiến dịch' : 'Campaigns' }}</button>
          <div class="flex items-center gap-2 mt-1 min-w-0">
            <h1 class="text-sm font-bold text-ink-primary truncate">{{ projectTitle }}</h1>
            <span class="editor-badge">{{ currentLang === 'vi' ? 'CHỈNH SỬA' : 'EDIT' }}</span>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button type="button" class="jm-btn-secondary text-xs" :disabled="busy" @click="resetTimeline">
            {{ currentLang === 'vi' ? 'Đặt lại từ cảnh gốc' : 'Reset from shots' }}
          </button>
          <button type="button" class="jm-btn-primary text-xs" :disabled="busy || !clips.length" @click="exportTimeline">
            <span v-if="exporting" class="lucide-refresh-cw size-3 animate-spin" />
            {{ exporting ? (currentLang === 'vi' ? 'Đang kết xuất…' : 'Rendering…') : (currentLang === 'vi' ? 'Xuất video' : 'Export video') }}
          </button>
        </div>
      </header>

      <section class="preview-shell">
        <div class="preview-toolbar">
          <div class="flex items-center gap-2 min-w-0">
            <span class="size-2 rounded-full bg-indigo-500" />
            <span v-if="previewMode === 'master'" class="truncate">{{ currentLang === 'vi' ? 'Video hoàn chỉnh' : 'Master video' }}</span>
            <span v-else-if="selectedClip" class="truncate">
              {{ clipLabel(selectedClip) }} · {{ frameTime(selectedClip.timeline_start_frame) }}–{{ frameTime(selectedClip.timeline_end_frame) }}
            </span>
          </div>
          <div class="flex items-center gap-1">
            <button v-if="timeline.final_video?.file" type="button" class="preview-mode-btn" :class="{ active: previewMode === 'master' }" @click="showMaster">
              {{ currentLang === 'vi' ? 'Video cuối' : 'Master' }}
            </button>
            <button v-if="selectedClip" type="button" class="preview-mode-btn" :class="{ active: previewMode === 'clip' }" @click="showClip">
              {{ currentLang === 'vi' ? 'Cảnh' : 'Clip' }}
            </button>
          </div>
        </div>

        <div class="video-stage">
          <video
            v-if="previewMode === 'master' && timeline.final_video?.file"
            :key="`master-${timeline.final_video.file}`"
            :src="timeline.final_video.file"
            class="stage-video"
            controls
            preload="metadata"
          />
          <video
            v-else-if="selectedClip?.source_file"
            ref="clipVideo"
            :key="selectedClip.name"
            :src="selectedClip.source_file"
            class="stage-video"
            preload="auto"
            playsinline
            @loadedmetadata="seekSelectedSource"
            @timeupdate="handleVideoTimeUpdate"
            @play="playing = true"
            @pause="playing = false"
            @ended="advancePlayback"
          />
          <div v-else class="empty-stage">
            {{ currentLang === 'vi' ? 'Chưa có clip video để chỉnh sửa.' : 'No generated video clips are ready for editing.' }}
          </div>
        </div>

        <div class="playback-bar">
          <div class="flex items-center gap-2">
            <button type="button" class="transport-btn" :disabled="previewMode === 'master' || !selectedClip" @click="togglePlayback">
              {{ playing ? '⏸' : '▶' }}
            </button>
            <button type="button" class="transport-btn" :disabled="!selectedClip" @click="stepFrame(-1)">‹</button>
            <button type="button" class="transport-btn" :disabled="!selectedClip" @click="stepFrame(1)">›</button>
            <span class="timecode">{{ frameTime(playheadFrame, true) }} / {{ frameTime(timeline.total_frames, true) }}</span>
          </div>
          <div class="text-[10px] text-ink-muted font-mono">
            {{ fpsLabel }} · F{{ Math.round(playheadFrame) }}
          </div>
        </div>
      </section>

      <section class="timeline-shell">
        <div class="timeline-heading">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold text-ink-primary">🎞 {{ currentLang === 'vi' ? 'DÒNG THỜI GIAN' : 'TIMELINE' }}</span>
            <span class="timeline-meta">{{ clips.length }} {{ currentLang === 'vi' ? 'clip' : 'clips' }} · {{ durationLabel }}</span>
          </div>
          <div class="flex items-center gap-1.5">
            <button type="button" class="tool-btn" :disabled="!canSplit || busy" @click="splitAtPlayhead">✂ {{ currentLang === 'vi' ? 'Tách' : 'Split' }}</button>
            <button type="button" class="tool-btn" :disabled="!selectedClip || busy" @click="duplicateSelected">⧉ {{ currentLang === 'vi' ? 'Nhân đôi' : 'Duplicate' }}</button>
            <button type="button" class="tool-btn danger" :disabled="!selectedClip || busy" @click="deleteSelected">⌫ {{ currentLang === 'vi' ? 'Xóa' : 'Delete' }}</button>
          </div>
        </div>

        <div ref="ruler" class="timeline-ruler" @click="seekTimeline">
          <div class="ruler-labels">
            <span v-for="tick in rulerTicks" :key="tick.frame" :style="{ left: `${tick.percent}%` }">{{ tick.label }}</span>
          </div>
          <div class="playhead" :style="{ left: `${playheadPercent}%` }">
            <span class="playhead-head" />
          </div>
        </div>

        <div v-if="clips.length" class="clip-track">
          <template v-for="(clip, index) in clips" :key="clip.name">
            <article
              class="timeline-clip"
              :class="{ selected: selectedClip?.name === clip.name }"
              :style="clipStyle(clip)"
              draggable="true"
              @dragstart="draggedClipName = clip.name"
              @dragover.prevent
              @drop.prevent="dropClip(index)"
              @click="selectClip(clip)"
            >
              <div class="clip-title-row">
                <span class="truncate">{{ clipLabel(clip) }}</span>
                <span class="font-mono text-[9px] text-ink-muted">{{ seconds(clip.duration_frames).toFixed(2) }}s</span>
              </div>
              <div class="clip-filmstrip">
                <video v-if="clip.source_file" :src="clip.source_file" muted preload="metadata" class="clip-thumb" />
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

            <button
              v-if="index < clips.length - 1"
              type="button"
              class="transition-node"
              :class="{ active: clip.transition_to_next !== 'Cut' }"
              :title="transitionTitle(clip)"
              @click.stop="selectTransitionSource(clip)"
            >
              {{ clip.transition_to_next === 'Cut' ? '│' : '◇' }}
            </button>
          </template>
        </div>
        <div v-else class="empty-timeline">
          {{ currentLang === 'vi' ? 'Không còn clip trên timeline.' : 'There are no clips on the timeline.' }}
        </div>
      </section>
    </main>

    <aside class="editor-inspector">
      <div class="inspector-header">
        <span class="font-bold">{{ currentLang === 'vi' ? 'Thuộc tính clip' : 'Clip Inspector' }}</span>
        <span v-if="selectedClip" class="text-indigo-400">#{{ selectedClip.clip_order }}</span>
      </div>

      <div v-if="selectedClip" class="inspector-body">
        <div class="inspector-card">
          <div class="text-[11px] font-bold text-ink-primary">{{ clipLabel(selectedClip) }}</div>
          <div class="text-[10px] text-ink-muted mt-1 break-all">{{ selectedClip.source_asset_name || selectedClip.source_asset_version }}</div>
          <div class="grid grid-cols-2 gap-2 mt-3">
            <div class="stat-box">
              <span>{{ currentLang === 'vi' ? 'Bắt đầu timeline' : 'Timeline start' }}</span>
              <strong>{{ frameTime(selectedClip.timeline_start_frame, true) }}</strong>
            </div>
            <div class="stat-box">
              <span>{{ currentLang === 'vi' ? 'Độ dài' : 'Duration' }}</span>
              <strong>{{ seconds(selectedClip.duration_frames).toFixed(2) }}s</strong>
            </div>
          </div>
        </div>

        <div class="inspector-card space-y-3">
          <div class="section-title">{{ currentLang === 'vi' ? 'Cắt theo frame' : 'Frame trim' }}</div>
          <label class="field-label">
            <span>IN</span>
            <input class="frame-input" type="number" min="0" :value="selectedClip.source_in_frame" @change="changeInFrame($event)" />
          </label>
          <label class="field-label">
            <span>OUT</span>
            <input class="frame-input" type="number" :min="selectedClip.source_in_frame + 1" :value="selectedClip.source_out_frame" @change="changeOutFrame($event)" />
          </label>
          <div class="grid grid-cols-4 gap-1">
            <button class="nudge-btn" type="button" @click="nudgeTrim('in', -1)">IN −1</button>
            <button class="nudge-btn" type="button" @click="nudgeTrim('in', 1)">IN +1</button>
            <button class="nudge-btn" type="button" @click="nudgeTrim('out', -1)">OUT −1</button>
            <button class="nudge-btn" type="button" @click="nudgeTrim('out', 1)">OUT +1</button>
          </div>
          <p class="helper-text">
            {{ currentLang === 'vi' ? 'IN là frame đầu tiên được giữ; OUT là frame kết thúc (không bao gồm).' : 'IN is inclusive; OUT is the exclusive end frame.' }}
          </p>
        </div>

        <div class="inspector-card space-y-2">
          <div class="section-title">{{ currentLang === 'vi' ? 'Chuyển cảnh tiếp theo' : 'Transition to next' }}</div>
          <select class="field-control" :value="selectedClip.transition_to_next" :disabled="isLastSelected" @change="changeTransitionType($event)">
            <option value="Cut">Cut</option>
            <option value="Dissolve">Dissolve</option>
            <option value="Fade">Fade</option>
          </select>
          <label v-if="selectedClip.transition_to_next !== 'Cut' && !isLastSelected" class="field-label">
            <span>{{ currentLang === 'vi' ? 'Thời lượng' : 'Duration' }}</span>
            <div class="flex items-center gap-1">
              <input
                class="frame-input"
                type="number"
                min="1"
                step="1"
                :value="selectedClip.transition_frames"
                @change="changeTransitionFrames($event)"
              />
              <span class="text-[10px] text-ink-muted">frames</span>
            </div>
          </label>
        </div>

        <div class="inspector-card space-y-2">
          <div class="section-title">{{ currentLang === 'vi' ? 'Thao tác' : 'Edit actions' }}</div>
          <button type="button" class="action-wide" :disabled="!canSplit || busy" @click="splitAtPlayhead">✂ {{ currentLang === 'vi' ? 'Tách tại playhead' : 'Split at playhead' }}</button>
          <button type="button" class="action-wide" :disabled="busy" @click="duplicateSelected">⧉ {{ currentLang === 'vi' ? 'Nhân đôi clip' : 'Duplicate clip' }}</button>
          <button type="button" class="action-wide danger" :disabled="busy" @click="deleteSelected">⌫ {{ currentLang === 'vi' ? 'Xóa khỏi timeline' : 'Delete from timeline' }}</button>
        </div>
      </div>

      <div v-else class="inspector-empty">
        {{ currentLang === 'vi' ? 'Chọn một clip trên timeline để chỉnh sửa.' : 'Select a timeline clip to edit it.' }}
      </div>
    </aside>
  </div>
</template>

<script setup>
import { call, toast } from "frappe-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "../stores/i18n";

const props = defineProps({
  initialTimeline: { type: Object, required: true },
});

const { currentLang } = useI18n();
const route = useRoute();
const projectName = computed(() => route.params.name);
const timeline = ref({ ...props.initialTimeline });
const workspace = ref(null);
const selectedClipName = ref(props.initialTimeline?.clips?.[0]?.name || null);
const playheadFrame = ref(props.initialTimeline?.clips?.[0]?.timeline_start_frame || 0);
const draggedClipName = ref(null);
const clipVideo = ref(null);
const ruler = ref(null);
const playing = ref(false);
const busy = ref(false);
const exporting = ref(false);
const previewMode = ref("clip");
let seekAfterLoadFrame = null;

const clips = computed(() => timeline.value?.clips || []);
const fps = computed(() => Number(timeline.value?.fps || 0));
const selectedClip = computed(() => clips.value.find((clip) => clip.name === selectedClipName.value) || clips.value[0] || null);
const selectedIndex = computed(() => clips.value.findIndex((clip) => clip.name === selectedClip.value?.name));
const isLastSelected = computed(() => selectedIndex.value < 0 || selectedIndex.value === clips.value.length - 1);
const fpsLabel = computed(() => fps.value ? `${fps.value} fps` : "-- fps");
const durationLabel = computed(() => `${Number(timeline.value?.total_seconds || 0).toFixed(2)}s`);
const playheadPercent = computed(() => {
  const total = Number(timeline.value?.total_frames || 0);
  return total > 0 ? Math.min(100, Math.max(0, (Number(playheadFrame.value || 0) / total) * 100)) : 0;
});
const canSplit = computed(() => {
  const clip = selectedClip.value;
  if (!clip) return false;
  const sourceFrame = sourceFrameAtPlayhead(clip);
  return sourceFrame > clip.source_in_frame && sourceFrame < clip.source_out_frame;
});
const projectTitle = computed(() => workspace.value?.campaign?.project_name || workspace.value?.campaign?.campaign_name || projectName.value);

const rulerTicks = computed(() => {
  const total = Number(timeline.value?.total_frames || 0);
  if (!total || !fps.value) return [{ frame: 0, percent: 0, label: "00:00" }];
  const totalSeconds = total / fps.value;
  const targetTicks = 6;
  const rawStep = totalSeconds / targetTicks;
  const candidates = [0.5, 1, 2, 5, 10, 15, 30, 60];
  const step = candidates.find((value) => value >= rawStep) || 60;
  const values = [];
  for (let secondsValue = 0; secondsValue <= totalSeconds + 0.0001; secondsValue += step) {
    const frame = Math.min(total, Math.round(secondsValue * fps.value));
    values.push({ frame, percent: (frame / total) * 100, label: secondsTime(secondsValue) });
  }
  if (values[values.length - 1]?.frame !== total) {
    values.push({ frame: total, percent: 100, label: secondsTime(totalSeconds) });
  }
  return values;
});

function seconds(frameCount) {
  return fps.value ? Number(frameCount || 0) / fps.value : 0;
}

function secondsTime(value) {
  const total = Math.max(0, Number(value || 0));
  const minutes = Math.floor(total / 60);
  const secs = Math.floor(total % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function frameTime(frameCount, includeFrames = false) {
  if (!fps.value) return includeFrames ? "00:00:00" : "00:00";
  const frames = Math.max(0, Math.round(Number(frameCount || 0)));
  const wholeSeconds = Math.floor(frames / fps.value);
  const frameRemainder = Math.round(frames - wholeSeconds * fps.value);
  const minutes = Math.floor(wholeSeconds / 60);
  const secs = wholeSeconds % 60;
  if (!includeFrames) return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}:${String(frameRemainder).padStart(2, "0")}`;
}

function clipLabel(clip) {
  if (!clip) return "Clip";
  if (clip.shot_number) return currentLang.value === "vi" ? `Cảnh ${clip.shot_number}` : `Shot ${clip.shot_number}`;
  return `Clip ${clip.clip_order}`;
}

function clipStyle(clip) {
  const total = Number(timeline.value?.total_frames || 1);
  const percentage = Math.max(12, (clip.duration_frames / total) * 100);
  return { flex: `${clip.duration_frames} 1 0%`, minWidth: `${Math.min(260, Math.max(130, percentage * 5))}px` };
}

function transitionTitle(clip) {
  if (clip.transition_to_next === "Cut") return currentLang.value === "vi" ? "Cắt thẳng" : "Cut";
  return `${clip.transition_to_next} · ${clip.transition_frames}f`;
}

function sourceFrameAtPlayhead(clip) {
  if (!clip) return 0;
  const local = Math.max(0, Math.min(clip.duration_frames, playheadFrame.value - clip.timeline_start_frame));
  return Math.round(clip.source_in_frame + local);
}

async function loadWorkspace() {
  try {
    workspace.value = await call("joymedia.joymedia.doctype.media_project.media_project.get_project_workspace", { name: projectName.value });
  } catch (_) {
    workspace.value = null;
  }
}

function applyTimeline(next, preferredClip = null) {
  timeline.value = next || { clips: [] };
  const preferred = preferredClip || next?.selected_clip;
  const nextSelected = next?.clips?.find((clip) => clip.name === preferred)
    || next?.clips?.find((clip) => clip.name === selectedClipName.value)
    || next?.clips?.[0]
    || null;
  selectedClipName.value = nextSelected?.name || null;
  if (nextSelected) {
    playheadFrame.value = Math.max(nextSelected.timeline_start_frame, Math.min(playheadFrame.value, nextSelected.timeline_end_frame - 1));
  } else {
    playheadFrame.value = 0;
  }
}

async function refreshTimeline() {
  const next = await call("joymedia.services.timeline_editor.get_project_timeline", {
    project_name: projectName.value,
    create_if_possible: true,
  });
  applyTimeline(next);
}

function selectClip(clip, sourceFrame = null) {
  if (!clip) return;
  previewMode.value = "clip";
  selectedClipName.value = clip.name;
  const targetSource = sourceFrame == null ? clip.source_in_frame : sourceFrame;
  const local = Math.max(0, Math.min(clip.duration_frames - 1, targetSource - clip.source_in_frame));
  playheadFrame.value = clip.timeline_start_frame + local;
  seekAfterLoadFrame = targetSource;
  nextTick(seekSelectedSource);
}

function selectTransitionSource(clip) {
  selectClip(clip, Math.max(clip.source_in_frame, clip.source_out_frame - 1));
}

function seekSelectedSource() {
  const video = clipVideo.value;
  const clip = selectedClip.value;
  if (!video || !clip || !fps.value) return;
  const sourceFrame = seekAfterLoadFrame == null ? sourceFrameAtPlayhead(clip) : seekAfterLoadFrame;
  const time = Math.max(0, sourceFrame / fps.value);
  try {
    video.currentTime = time;
  } catch (_) {}
  seekAfterLoadFrame = null;
}

function handleVideoTimeUpdate() {
  const video = clipVideo.value;
  const clip = selectedClip.value;
  if (!video || !clip || !fps.value || previewMode.value !== "clip") return;
  const sourceFrame = Math.round(video.currentTime * fps.value);
  const local = Math.max(0, Math.min(clip.duration_frames, sourceFrame - clip.source_in_frame));
  playheadFrame.value = clip.timeline_start_frame + local;
  if (playing.value && sourceFrame >= clip.source_out_frame - 1) advancePlayback();
}

async function advancePlayback() {
  const index = selectedIndex.value;
  if (index >= 0 && index < clips.value.length - 1) {
    const next = clips.value[index + 1];
    selectClip(next, next.source_in_frame);
    await nextTick();
    seekSelectedSource();
    clipVideo.value?.play().catch(() => {});
  } else {
    playing.value = false;
    clipVideo.value?.pause();
  }
}

function togglePlayback() {
  if (previewMode.value === "master") return;
  const video = clipVideo.value;
  if (!video) return;
  if (video.paused) video.play().catch(() => {});
  else video.pause();
}

function stepFrame(direction) {
  const clip = selectedClip.value;
  if (!clip || !fps.value) return;
  const source = sourceFrameAtPlayhead(clip);
  const nextSource = Math.max(clip.source_in_frame, Math.min(clip.source_out_frame - 1, source + direction));
  selectClip(clip, nextSource);
}

function seekTimeline(event) {
  if (!ruler.value || !clips.value.length) return;
  const rect = ruler.value.getBoundingClientRect();
  const percent = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const target = Math.round(percent * Number(timeline.value.total_frames || 0));
  const clip = clips.value.find((item) => target >= item.timeline_start_frame && target < item.timeline_end_frame)
    || clips.value[clips.value.length - 1];
  const local = Math.max(0, Math.min(clip.duration_frames - 1, target - clip.timeline_start_frame));
  selectClip(clip, clip.source_in_frame + local);
}

async function runEdit(method, payload, preferredClip = null) {
  if (busy.value) return;
  busy.value = true;
  try {
    const result = await call(`joymedia.services.timeline_editor.${method}`, {
      project_name: projectName.value,
      ...payload,
    });
    applyTimeline(result, preferredClip);
    return result;
  } catch (error) {
    toast({
      title: currentLang.value === "vi" ? "Không thể chỉnh sửa timeline" : "Timeline edit failed",
      text: error?.messages?.join(" ") || error?.message || "Please try again.",
      type: "error",
    });
    return null;
  } finally {
    busy.value = false;
  }
}

async function changeInFrame(event) {
  const clip = selectedClip.value;
  if (!clip) return;
  const next = Number(event.target.value);
  await trimSelected(next, clip.source_out_frame);
}

async function changeOutFrame(event) {
  const clip = selectedClip.value;
  if (!clip) return;
  const next = Number(event.target.value);
  await trimSelected(clip.source_in_frame, next);
}

async function nudgeTrim(edge, delta) {
  const clip = selectedClip.value;
  if (!clip) return;
  const start = edge === "in" ? clip.source_in_frame + delta : clip.source_in_frame;
  const end = edge === "out" ? clip.source_out_frame + delta : clip.source_out_frame;
  await trimSelected(start, end);
}

async function trimSelected(start, end) {
  const clip = selectedClip.value;
  if (!clip) return;
  const result = await runEdit("trim_timeline_clip", {
    clip_name: clip.name,
    source_in_frame: Math.round(start),
    source_out_frame: Math.round(end),
  }, clip.name);
  if (result) {
    const refreshed = result.clips.find((item) => item.name === clip.name);
    if (refreshed) selectClip(refreshed, Math.max(refreshed.source_in_frame, Math.min(sourceFrameAtPlayhead(refreshed), refreshed.source_out_frame - 1)));
  }
}

async function splitAtPlayhead() {
  const clip = selectedClip.value;
  if (!clip || !canSplit.value) return;
  const splitFrame = sourceFrameAtPlayhead(clip);
  const result = await runEdit("split_timeline_clip", {
    clip_name: clip.name,
    source_split_frame: splitFrame,
  });
  if (result?.selected_clip) {
    const created = result.clips.find((item) => item.name === result.selected_clip);
    if (created) selectClip(created, created.source_in_frame);
  }
}

async function duplicateSelected() {
  const clip = selectedClip.value;
  if (!clip) return;
  const result = await runEdit("duplicate_timeline_clip", { clip_name: clip.name });
  if (result?.selected_clip) {
    const created = result.clips.find((item) => item.name === result.selected_clip);
    if (created) selectClip(created, created.source_in_frame);
  }
}

async function deleteSelected() {
  const clip = selectedClip.value;
  if (!clip) return;
  await runEdit("delete_timeline_clip", { clip_name: clip.name });
}

async function dropClip(targetIndex) {
  const name = draggedClipName.value;
  draggedClipName.value = null;
  if (!name) return;
  const clip = clips.value.find((item) => item.name === name);
  if (!clip || clip.clip_order === targetIndex + 1) return;
  await runEdit("reorder_timeline_clip", {
    clip_name: name,
    target_order: targetIndex + 1,
  }, name);
}

async function changeTransitionType(event) {
  const clip = selectedClip.value;
  if (!clip) return;
  const transition = event.target.value;
  let transitionFrames = 0;
  if (transition !== "Cut") {
    const nextClip = clips.value[selectedIndex.value + 1];
    const maxFrames = Math.max(1, Math.min(clip.duration_frames, nextClip?.duration_frames || clip.duration_frames) - 1);
    transitionFrames = Math.min(maxFrames, Math.max(1, Math.round(fps.value * 0.35)));
  }
  await runEdit("set_timeline_transition", {
    clip_name: clip.name,
    transition,
    transition_frames: transitionFrames,
  }, clip.name);
}

async function changeTransitionFrames(event) {
  const clip = selectedClip.value;
  if (!clip) return;
  await runEdit("set_timeline_transition", {
    clip_name: clip.name,
    transition: clip.transition_to_next,
    transition_frames: Math.round(Number(event.target.value)),
  }, clip.name);
}

async function resetTimeline() {
  if (busy.value) return;
  busy.value = true;
  try {
    const result = await call("joymedia.services.timeline_editor.reset_project_timeline", { project_name: projectName.value });
    applyTimeline(result);
    toast({ title: currentLang.value === "vi" ? "Đã đặt lại timeline" : "Timeline reset", type: "success" });
  } catch (error) {
    toast({ title: "Reset failed", text: error?.message || "Please try again.", type: "error" });
  } finally {
    busy.value = false;
  }
}

async function exportTimeline() {
  if (exporting.value || !clips.value.length) return;
  exporting.value = true;
  try {
    const result = await call("joymedia.services.timeline_editor.compose_project_timeline", { project_name: projectName.value });
    await refreshTimeline();
    previewMode.value = "master";
    toast({
      title: currentLang.value === "vi" ? "Đã xuất video" : "Video exported",
      text: `${Number(result.duration_seconds || 0).toFixed(2)}s · ${result.timeline_frames} frames`,
      type: "success",
    });
  } catch (error) {
    toast({
      title: currentLang.value === "vi" ? "Kết xuất thất bại" : "Export failed",
      text: error?.messages?.join(" ") || error?.message || "Please try again.",
      type: "error",
    });
  } finally {
    exporting.value = false;
  }
}

function showMaster() {
  previewMode.value = "master";
  playing.value = false;
}

function showClip() {
  previewMode.value = "clip";
  nextTick(seekSelectedSource);
}

function goBack() {
  window.location.href = "/joymedia/campaigns";
}

function handleKeydown(event) {
  if (event.target?.matches?.("input, textarea, select")) return;
  if (event.code === "Space") {
    event.preventDefault();
    togglePlayback();
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    stepFrame(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    stepFrame(1);
  }
}

onMounted(() => {
  loadWorkspace();
  window.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeydown);
});
</script>

<style scoped>
.timeline-editor-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 310px;
  width: 100%;
  height: calc(100vh - 52px);
  min-height: 680px;
  overflow: hidden;
  background: var(--surface-base, #f7f8fb);
  color: var(--ink-primary, #172033);
}
.timeline-main { min-width: 0; overflow: auto; padding: 14px 16px 18px; }
.editor-topbar, .preview-shell, .timeline-shell {
  background: var(--surface-card, #fff);
  border: 1px solid var(--outline-border, #e4e7ec);
  border-radius: 14px;
  box-shadow: 0 1px 2px rgb(15 23 42 / 4%);
}
.editor-topbar { min-height: 54px; padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.back-link { font-size: 11px; color: var(--ink-muted, #7b8498); font-weight: 600; cursor: pointer; }
.editor-badge { font-size: 9px; padding: 2px 7px; border-radius: 6px; background: rgb(99 102 241 / 10%); color: #6366f1; font-weight: 800; letter-spacing: .06em; }
.preview-shell { margin-top: 10px; overflow: hidden; }
.preview-toolbar { min-height: 40px; padding: 7px 10px; border-bottom: 1px solid var(--outline-border, #e4e7ec); display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--ink-secondary, #4b5565); }
.preview-mode-btn { padding: 4px 8px; border-radius: 7px; font-size: 10px; font-weight: 700; color: var(--ink-muted, #7b8498); background: var(--surface-muted, #f2f4f7); }
.preview-mode-btn.active { color: white; background: #6366f1; }
.video-stage { height: min(47vh, 500px); min-height: 310px; display: flex; align-items: center; justify-content: center; background: #090b10; }
.stage-video { width: 100%; height: 100%; object-fit: contain; background: #090b10; }
.empty-stage { color: #8b93a7; font-size: 12px; }
.playback-bar { height: 42px; padding: 6px 10px; border-top: 1px solid var(--outline-border, #e4e7ec); display: flex; align-items: center; justify-content: space-between; }
.transport-btn { width: 26px; height: 26px; border-radius: 7px; background: var(--surface-muted, #f2f4f7); color: var(--ink-primary, #172033); font-size: 11px; font-weight: 800; }
.transport-btn:disabled { opacity: .4; }
.timecode { font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--ink-primary, #172033); }
.timeline-shell { margin-top: 10px; padding: 10px; overflow-x: hidden; }
.timeline-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 32px; }
.timeline-meta { font: 700 10px ui-monospace, SFMono-Regular, Menlo, monospace; color: #6366f1; background: var(--surface-muted, #f2f4f7); border: 1px solid var(--outline-border, #e4e7ec); border-radius: 999px; padding: 2px 7px; }
.tool-btn { padding: 5px 8px; border: 1px solid var(--outline-border, #e4e7ec); border-radius: 7px; background: var(--surface-muted, #f2f4f7); font-size: 10px; font-weight: 700; color: var(--ink-secondary, #4b5565); }
.tool-btn:hover:not(:disabled) { border-color: #818cf8; color: #4f46e5; }
.tool-btn.danger:hover:not(:disabled) { border-color: #fb7185; color: #e11d48; }
.tool-btn:disabled { opacity: .4; }
.timeline-ruler { position: relative; height: 32px; margin: 6px 0 4px; cursor: crosshair; border-bottom: 1px solid var(--outline-border, #e4e7ec); }
.ruler-labels { position: absolute; inset: 0; }
.ruler-labels span { position: absolute; top: 2px; transform: translateX(-50%); font: 9px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--ink-muted, #8b93a7); }
.ruler-labels span::after { content: ""; display: block; width: 1px; height: 8px; background: var(--outline-border, #d7dce5); margin: 2px auto 0; }
.playhead { position: absolute; top: 0; bottom: -122px; width: 1px; background: #6366f1; z-index: 10; pointer-events: none; }
.playhead-head { position: absolute; top: -1px; left: -4px; width: 9px; height: 9px; border-radius: 2px 2px 5px 5px; background: #6366f1; }
.clip-track { display: flex; align-items: stretch; gap: 0; min-height: 112px; overflow-x: auto; padding: 4px 0 8px; }
.timeline-clip { position: relative; border: 1px solid var(--outline-border, #dfe3ea); border-radius: 9px; padding: 6px; background: var(--surface-muted, #f5f6f9); cursor: pointer; transition: border-color .12s, box-shadow .12s; }
.timeline-clip:hover { border-color: #a5b4fc; }
.timeline-clip.selected { border-color: #6366f1; box-shadow: 0 0 0 2px rgb(99 102 241 / 15%); background: rgb(99 102 241 / 4%); }
.clip-title-row { display: flex; align-items: center; justify-content: space-between; gap: 5px; height: 18px; font-size: 10px; font-weight: 800; }
.clip-filmstrip { position: relative; height: 58px; border-radius: 6px; overflow: hidden; background: #0b0d12; }
.clip-thumb { width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
.clip-thumb-empty { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #7d8493; }
.clip-frame-overlay { position: absolute; inset: auto 4px 3px; display: flex; justify-content: space-between; color: white; font: 8px ui-monospace, SFMono-Regular, Menlo, monospace; text-shadow: 0 1px 4px black; }
.clip-range { display: flex; justify-content: space-between; margin-top: 4px; color: var(--ink-muted, #8790a3); font: 8px ui-monospace, SFMono-Regular, Menlo, monospace; }
.transition-node { align-self: center; flex: 0 0 26px; width: 26px; height: 26px; margin: 0 -2px; z-index: 3; border-radius: 999px; border: 1px solid var(--outline-border, #dfe3ea); background: var(--surface-card, #fff); color: var(--ink-muted, #8790a3); font-size: 12px; }
.transition-node.active { border-color: #818cf8; color: #6366f1; background: #eef2ff; }
.empty-timeline { padding: 28px; text-align: center; color: var(--ink-muted, #8790a3); font-size: 11px; }
.editor-inspector { min-width: 0; border-left: 1px solid var(--outline-border, #e4e7ec); background: var(--surface-card, #fff); overflow-y: auto; }
.inspector-header { height: 48px; padding: 0 14px; border-bottom: 1px solid var(--outline-border, #e4e7ec); display: flex; align-items: center; justify-content: space-between; font-size: 11px; }
.inspector-body { padding: 10px; display: flex; flex-direction: column; gap: 9px; }
.inspector-card { border: 1px solid var(--outline-border, #e4e7ec); border-radius: 11px; background: var(--surface-muted, #f7f8fa); padding: 10px; }
.section-title { font-size: 10px; font-weight: 800; color: var(--ink-primary, #172033); text-transform: uppercase; letter-spacing: .04em; }
.stat-box { display: flex; flex-direction: column; gap: 2px; padding: 6px; border-radius: 7px; background: var(--surface-card, #fff); border: 1px solid var(--outline-border, #e4e7ec); }
.stat-box span { font-size: 8px; color: var(--ink-muted, #8790a3); }
.stat-box strong { font: 700 9px ui-monospace, SFMono-Regular, Menlo, monospace; }
.field-label { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 10px; color: var(--ink-secondary, #596174); }
.frame-input, .field-control { min-width: 0; border: 1px solid var(--outline-border, #dfe3ea); border-radius: 7px; background: var(--surface-card, #fff); color: var(--ink-primary, #172033); padding: 5px 7px; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
.frame-input { width: 100px; text-align: right; }
.field-control { width: 100%; }
.nudge-btn { padding: 5px 2px; border-radius: 6px; background: var(--surface-card, #fff); border: 1px solid var(--outline-border, #e4e7ec); font-size: 8px; font-weight: 700; }
.helper-text { font-size: 9px; line-height: 1.45; color: var(--ink-muted, #8790a3); }
.action-wide { width: 100%; padding: 7px 9px; border-radius: 7px; border: 1px solid var(--outline-border, #e4e7ec); background: var(--surface-card, #fff); color: var(--ink-secondary, #4b5565); font-size: 10px; font-weight: 700; text-align: left; }
.action-wide:hover:not(:disabled) { border-color: #818cf8; color: #4f46e5; }
.action-wide.danger:hover:not(:disabled) { border-color: #fb7185; color: #e11d48; }
.inspector-empty { padding: 24px 14px; color: var(--ink-muted, #8790a3); font-size: 11px; line-height: 1.5; }
@media (max-width: 1000px) {
  .timeline-editor-page { grid-template-columns: 1fr; height: auto; min-height: calc(100vh - 52px); overflow: visible; }
  .editor-inspector { border-left: 0; border-top: 1px solid var(--outline-border, #e4e7ec); }
  .video-stage { min-height: 260px; }
}
</style>
