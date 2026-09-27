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
            <button type="button" class="tool-btn" :disabled="!canUndo || busy" @click="undo">↶ {{ currentLang === 'vi' ? 'Hoàn tác' : 'Undo' }}</button>
            <button type="button" class="tool-btn" :disabled="!canRedo || busy" @click="redo">↷ {{ currentLang === 'vi' ? 'Làm lại' : 'Redo' }}</button>
            <button type="button" class="tool-btn" :disabled="!canSplit || busy" @click="splitAtPlayhead">✂ {{ currentLang === 'vi' ? 'Tách' : 'Split' }}</button>
            <button type="button" class="tool-btn" :disabled="!selectedClip || busy" @click="duplicateSelected">⧉ {{ currentLang === 'vi' ? 'Nhân đôi' : 'Duplicate' }}</button>
            <button type="button" class="tool-btn danger" :disabled="!selectedClip || busy" @click="deleteSelected">⌫ {{ currentLang === 'vi' ? 'Xóa' : 'Delete' }}</button>
            <button type="button" class="tool-btn ai-tool-btn" :disabled="!selectedClip" @click="openAiPanel">✨ {{ currentLang === 'vi' ? 'Hỏi AI' : 'Ask AI' }}</button>
            <button type="button" class="tool-btn" :class="{ active: snapping }" @click="snapping = !snapping">⌁ {{ currentLang === 'vi' ? 'Hút' : 'Snap' }}</button>
            <label class="zoom-control">＋ <input v-model.number="zoom" type="range" min="0.6" max="3" step="0.1" /> ＋</label>
          </div>
        </div>

        <div ref="ruler" class="timeline-ruler" :style="{ width: `${timelineCanvasWidth}px` }" @click="seekTimeline">
          <div class="ruler-labels">
            <span v-for="tick in rulerTicks" :key="tick.frame" :style="{ left: `${tick.frame * pixelsPerFrame}px` }">{{ tick.label }}</span>
          </div>
          <div class="playhead" :style="{ left: `${playheadFrame * pixelsPerFrame}px` }">
            <span class="playhead-head" />
          </div>
        </div>

        <div v-if="clips.length" class="clip-track">
          <div class="timeline-canvas" :style="{ width: `${timelineCanvasWidth}px` }">
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
              <button type="button" class="trim-handle trim-handle-left" aria-label="Trim start" @pointerdown.stop="startTrim(clip, 'left', $event)" />
              <button type="button" class="trim-handle trim-handle-right" aria-label="Trim end" @pointerdown.stop="startTrim(clip, 'right', $event)" />
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
              :style="{ left: `${clip.timeline_end_frame * pixelsPerFrame}px` }"
              :title="transitionTitle(clip)"
              @click.stop="selectTransitionSource(clip)"
            >
              {{ clip.transition_to_next === 'Cut' ? '│' : '◇' }}
            </button>
          </template>
          </div>
        </div>
        <div v-else class="empty-timeline">
          {{ currentLang === 'vi' ? 'Không còn clip trên timeline.' : 'There are no clips on the timeline.' }}
        </div>
      </section>
    </main>

    <aside class="editor-inspector">
      <div class="inspector-header inspector-tabs">
        <button type="button" class="inspector-tab" :class="{ active: rightPanel === 'inspector' }" @click="rightPanel = 'inspector'">
          {{ currentLang === 'vi' ? 'Thanh tra' : 'Inspector' }}
        </button>
        <button type="button" class="inspector-tab" :class="{ active: rightPanel === 'prompt' }" @click="rightPanel = 'prompt'">
          Prompt
        </button>
        <button type="button" class="inspector-tab" :class="{ active: rightPanel === 'ai' }" @click="rightPanel = 'ai'">
          ✨ AI Edit
        </button>
      </div>

      <div v-if="rightPanel === 'inspector' && selectedClip" class="inspector-body">
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

      </div>

      <div v-else-if="rightPanel === 'prompt' && selectedClip" class="inspector-body">
        <div class="inspector-card">
          <div class="section-title">{{ currentLang === 'vi' ? 'Prompt cảnh' : 'Shot prompt' }}</div>
          <div class="text-[11px] font-bold text-ink-primary mt-2">{{ clipLabel(selectedClip) }}</div>
          <div class="prompt-field">
            <span>{{ currentLang === 'vi' ? 'Prompt tạo video' : 'Generation prompt' }}</span>
            <p>{{ selectedShot?.generation_prompt || '—' }}</p>
          </div>
          <div class="prompt-field"><span>{{ currentLang === 'vi' ? 'Chủ thể' : 'Subject' }}</span><p>{{ selectedShot?.subject_identity || '—' }}</p></div>
          <div class="prompt-field"><span>{{ currentLang === 'vi' ? 'Hành động' : 'Action' }}</span><p>{{ selectedShot?.action_plot || '—' }}</p></div>
          <div class="prompt-field"><span>{{ currentLang === 'vi' ? 'Máy quay' : 'Camera' }}</span><p>{{ selectedShot?.camera_direction || '—' }}</p></div>
          <div class="prompt-field"><span>{{ currentLang === 'vi' ? 'Bối cảnh' : 'Environment' }}</span><p>{{ selectedShot?.environment || '—' }}</p></div>
        </div>

        <div class="inspector-card">
          <div class="section-title">{{ currentLang === 'vi' ? 'Tham chiếu nguồn' : 'Source references' }}</div>
          <div class="reference-grid">
            <div v-if="selectedShot?.reference_image" class="reference-item"><img :src="selectedShot.reference_image" alt="Product reference" /><span>{{ selectedShot.reference_asset_name || 'Product' }}</span></div>
            <div v-if="selectedShot?.last_frame_image" class="reference-item"><img :src="selectedShot.last_frame_image" alt="Previous shot final frame" /><span>{{ selectedShot.last_frame_asset_name || 'Previous final frame' }}</span></div>
            <div v-if="selectedShot?.selected_output_file" class="reference-item"><span class="reference-file">▶</span><span>{{ currentLang === 'vi' ? 'Video đã chọn' : 'Selected output' }}</span></div>
            <div v-if="!selectedShot?.reference_image && !selectedShot?.last_frame_image && !selectedShot?.selected_output_file" class="helper-text">{{ currentLang === 'vi' ? 'Chưa có tham chiếu cho cảnh này.' : 'No references are attached to this shot.' }}</div>
          </div>
        </div>

        <div class="inspector-card">
          <div class="section-title">{{ currentLang === 'vi' ? 'Thông tin tạo' : 'Generation' }}</div>
          <div class="metadata-row"><span>Workflow</span><strong>{{ workspace?.video_settings?.video_style_name || workspace?.video_settings?.style || '—' }}</strong></div>
          <div class="metadata-row"><span>FPS</span><strong>{{ fpsLabel }}</strong></div>
          <div class="metadata-row"><span>Output</span><strong>{{ selectedShot?.selected_output_asset_version ? 'Generated video' : '—' }}</strong></div>
          <p class="helper-text mt-2">{{ currentLang === 'vi' ? 'Các trường prompt là dữ liệu Shot Specification hiện có và chỉ đọc trong trình chỉnh sửa timeline.' : 'These fields come from the existing Shot Specification and are read-only in the timeline editor.' }}</p>
        </div>
      </div>

      <div v-else-if="rightPanel === 'ai' && selectedClip" class="inspector-body">
        <div class="inspector-card ai-card">
          <div class="section-title">✨ {{ currentLang === 'vi' ? 'Chỉnh sửa bằng AI' : 'AI Edit' }}</div>
          <p class="helper-text mt-2">{{ currentLang === 'vi' ? 'AI Edit đề xuất thay đổi timeline để bạn xem trước. Nó không tự tạo lại video và không tự sửa dữ liệu.' : 'AI Edit is for proposed timeline changes. It does not regenerate video or change data automatically.' }}</p>
          <label class="field-label ai-label"><span>{{ currentLang === 'vi' ? 'Phạm vi' : 'Scope' }}</span></label>
          <select v-model="aiScope" class="field-control">
            <option value="selected_clip">{{ currentLang === 'vi' ? 'Clip đang chọn' : 'Selected clip' }}</option>
            <option value="selected_clips">{{ currentLang === 'vi' ? 'Các clip đang chọn' : 'Selected clips' }}</option>
            <option value="timeline_range">{{ currentLang === 'vi' ? 'Khoảng timeline hiện tại' : 'Current timeline range' }}</option>
            <option value="whole_video">{{ currentLang === 'vi' ? 'Toàn bộ video' : 'Whole video' }}</option>
          </select>
          <textarea ref="aiInput" v-model="aiInstruction" class="ai-input" rows="5" :placeholder="currentLang === 'vi' ? 'Ví dụ: làm cảnh này ngắn hơn và chuyển cảnh mượt hơn' : 'Example: make this shot shorter and use a smoother transition'" />
          <button type="button" class="action-wide ai-submit" disabled title="Timeline proposal service is not configured">{{ currentLang === 'vi' ? 'Đề xuất AI chưa được cấu hình' : 'AI proposal service unavailable' }}</button>
          <p class="helper-text">{{ currentLang === 'vi' ? 'Chưa có API đề xuất chỉnh sửa timeline trong hệ thống hiện tại. Không có thay đổi nào được gửi hoặc áp dụng.' : 'This installation has no timeline proposal API yet. No change is sent or applied.' }}</p>
        </div>
        <div class="inspector-card">
          <div class="section-title">{{ currentLang === 'vi' ? 'Ngữ cảnh gửi cho AI' : 'AI context' }}</div>
          <div class="metadata-row"><span>Clip</span><strong>{{ clipLabel(selectedClip) }}</strong></div>
          <div class="metadata-row"><span>Timeline</span><strong>{{ frameTime(selectedClip.timeline_start_frame) }}–{{ frameTime(selectedClip.timeline_end_frame) }}</strong></div>
          <div class="metadata-row"><span>Source</span><strong>{{ selectedClip.source_asset_name || selectedClip.source_asset_version || '—' }}</strong></div>
          <div class="metadata-row"><span>Neighbors</span><strong>{{ selectedIndex > 0 ? clipLabel(clips[selectedIndex - 1]) : '—' }} → {{ selectedIndex < clips.length - 1 ? clipLabel(clips[selectedIndex + 1]) : '—' }}</strong></div>
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
const rightPanel = ref("inspector");
const aiScope = ref("selected_clip");
const aiInstruction = ref("");
const aiInput = ref(null);
const zoom = ref(1);
const snapping = ref(true);
const history = ref([]);
const future = ref([]);
const trimDrag = ref(null);
let seekAfterLoadFrame = null;

const clips = computed(() => timeline.value?.clips || []);
const fps = computed(() => Number(timeline.value?.fps || 0));
const selectedClip = computed(() => clips.value.find((clip) => clip.name === selectedClipName.value) || clips.value[0] || null);
const selectedIndex = computed(() => clips.value.findIndex((clip) => clip.name === selectedClip.value?.name));
const isLastSelected = computed(() => selectedIndex.value < 0 || selectedIndex.value === clips.value.length - 1);
const fpsLabel = computed(() => fps.value ? `${fps.value} fps` : "-- fps");
const durationLabel = computed(() => `${Number(timeline.value?.total_seconds || 0).toFixed(2)}s`);
const pixelsPerFrame = computed(() => Math.max(2, (36 * zoom.value) / Math.max(1, fps.value)));
const timelineCanvasWidth = computed(() => Math.max(700, Number(timeline.value?.total_frames || 0) * pixelsPerFrame.value));
const canUndo = computed(() => history.value.length > 0);
const canRedo = computed(() => future.value.length > 0);
const activeClip = computed(() => clips.value.find((clip) => playheadFrame.value > clip.timeline_start_frame && playheadFrame.value < clip.timeline_end_frame) || null);
const canSplit = computed(() => Boolean(activeClip.value));
const projectTitle = computed(() => workspace.value?.campaign?.project_name || workspace.value?.campaign?.campaign_name || projectName.value);
const selectedShot = computed(() => {
  const storyboard = workspace.value?.storyboard || [];
  if (!selectedClip.value) return null;
  return storyboard.find((shot) => shot.name === selectedClip.value.shot_specification)
    || storyboard.find((shot) => Number(shot.shot_number) === Number(selectedClip.value.shot_number))
    || null;
});

const rulerTicks = computed(() => {
  const total = Number(timeline.value?.total_frames || 0);
  if (!total || !fps.value) return [{ frame: 0, label: "00:00" }];
  const totalSeconds = total / fps.value;
  const targetTicks = 6;
  const rawStep = totalSeconds / targetTicks;
  const candidates = [0.5, 1, 2, 5, 10, 15, 30, 60];
  const step = candidates.find((value) => value >= rawStep) || 60;
  const values = [];
  for (let secondsValue = 0; secondsValue <= totalSeconds + 0.0001; secondsValue += step) {
    const frame = Math.min(total, Math.round(secondsValue * fps.value));
    values.push({ frame, label: secondsTime(secondsValue) });
  }
  if (values[values.length - 1]?.frame !== total) {
    values.push({ frame: total, label: secondsTime(totalSeconds) });
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
  return {
    left: `${clip.timeline_start_frame * pixelsPerFrame.value}px`,
    width: `${Math.max(48, clip.duration_frames * pixelsPerFrame.value)}px`,
  };
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

function cloneTimeline(value) {
  return JSON.parse(JSON.stringify(value || { clips: [] }));
}

function recordHistory(entry) {
  history.value.push(entry);
  future.value = [];
}

function rippleTimeline(value) {
  const next = cloneTimeline(value);
  let cursor = 0;
  next.clips = (next.clips || []).map((clip, index, list) => {
    const duration = Math.max(1, Number(clip.source_out_frame) - Number(clip.source_in_frame));
    const transitionFrames = index < list.length - 1 && clip.transition_to_next !== "Cut"
      ? Math.max(0, Number(clip.transition_frames || 0))
      : 0;
    const updated = {
      ...clip,
      duration_frames: duration,
      timeline_start_frame: cursor,
      timeline_end_frame: cursor + duration,
    };
    cursor += duration - transitionFrames;
    return updated;
  });
  next.total_frames = cursor;
  next.total_seconds = fps.value ? cursor / fps.value : 0;
  return next;
}

function snapFrame(frame, clipName) {
  if (!snapping.value) return Math.round(frame);
  const rounded = Math.round(frame);
  const candidates = [0, Number(playheadFrame.value || 0)];
  clips.value.forEach((clip) => {
    if (clip.name !== clipName) candidates.push(Number(clip.timeline_start_frame), Number(clip.timeline_end_frame));
  });
  const nearest = candidates
    .map((candidate) => ({ candidate, distance: Math.abs(candidate - rounded) }))
    .filter((item) => item.distance <= 3)
    .sort((left, right) => left.distance - right.distance)[0];
  return nearest == null ? rounded : nearest.candidate;
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

function openAiPanel() {
  if (!selectedClip.value) return;
  rightPanel.value = "ai";
  nextTick(() => aiInput.value?.focus());
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

function startTrim(clip, edge, event) {
  if (busy.value || !clip) return;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  trimDrag.value = {
    clipName: clip.name,
    edge,
    startX: event.clientX,
    originalIn: Number(clip.source_in_frame),
    originalOut: Number(clip.source_out_frame),
    originalTimelineStart: Number(clip.timeline_start_frame),
    originalTimelineEnd: Number(clip.timeline_end_frame),
    before: cloneTimeline(timeline.value),
  };
  window.addEventListener("pointermove", handleTrimMove);
  window.addEventListener("pointerup", finishTrim);
}

function handleTrimMove(event) {
  const drag = trimDrag.value;
  const clip = clips.value.find((item) => item.name === drag?.clipName);
  if (!drag || !clip) return;
  const delta = Math.round((event.clientX - drag.startX) / pixelsPerFrame.value);
  const edgeFrame = drag.edge === "left" ? drag.originalTimelineStart : drag.originalTimelineEnd;
  const timelineDelta = snapFrame(edgeFrame + delta, clip.name) - edgeFrame;
  const minDuration = Math.max(1, Number(clip.min_duration_frames || Math.round(fps.value * 0.25)));
  const sourceMax = Number(clip.source_total_frames || drag.originalOut);
  const nextIn = drag.edge === "left"
    ? Math.max(0, Math.min(drag.originalOut - minDuration, drag.originalIn + timelineDelta))
    : drag.originalIn;
  const nextOut = drag.edge === "right"
    ? Math.min(sourceMax, Math.max(drag.originalIn + minDuration, drag.originalOut + timelineDelta))
    : drag.originalOut;
  const next = cloneTimeline(timeline.value);
  const target = next.clips.find((item) => item.name === clip.name);
  if (!target) return;
  target.source_in_frame = nextIn;
  target.source_out_frame = nextOut;
  timeline.value = rippleTimeline(next);
  const refreshed = timeline.value.clips.find((item) => item.name === clip.name);
  playheadFrame.value = Math.min(playheadFrame.value, Math.max(0, Number(timeline.value.total_frames) - 1));
  if (refreshed) selectedClipName.value = refreshed.name;
}

async function finishTrim() {
  const drag = trimDrag.value;
  trimDrag.value = null;
  window.removeEventListener("pointermove", handleTrimMove);
  window.removeEventListener("pointerup", finishTrim);
  const clip = clips.value.find((item) => item.name === drag?.clipName);
  if (!drag || !clip) return;
  if (clip.source_in_frame === drag.originalIn && clip.source_out_frame === drag.originalOut) {
    timeline.value = drag.before;
    return;
  }
  await trimSelected(clip.source_in_frame, clip.source_out_frame, drag.before);
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

async function trimSelected(start, end, before = cloneTimeline(timeline.value), record = true) {
  const clip = selectedClip.value;
  if (!clip) return;
  const result = await runEdit("trim_timeline_clip", {
    clip_name: clip.name,
    source_in_frame: Math.round(start),
    source_out_frame: Math.round(end),
  }, clip.name);
  if (result) {
    if (record) recordHistory({ type: "trim", clipName: clip.name, before, after: cloneTimeline(result) });
    const refreshed = result.clips.find((item) => item.name === clip.name);
    if (refreshed) selectClip(refreshed, Math.max(refreshed.source_in_frame, Math.min(sourceFrameAtPlayhead(refreshed), refreshed.source_out_frame - 1)));
  }
}

async function splitAtPlayhead() {
  const clip = activeClip.value;
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

async function restoreHistory(entry, snapshotKey) {
  if (!entry || entry.type !== "trim") return;
  const snapshot = entry[snapshotKey];
  const clip = snapshot.clips.find((item) => item.name === entry.clipName);
  if (!clip) return;
  const result = await runEdit("trim_timeline_clip", {
    clip_name: entry.clipName,
    source_in_frame: clip.source_in_frame,
    source_out_frame: clip.source_out_frame,
  }, entry.clipName);
  return Boolean(result);
}

async function undo() {
  if (busy.value || !history.value.length) return;
  const entry = history.value[history.value.length - 1];
  if (await restoreHistory(entry, "before")) {
    history.value.pop();
    future.value.push(entry);
  }
}

async function redo() {
  if (busy.value || !future.value.length) return;
  const entry = future.value[future.value.length - 1];
  if (await restoreHistory(entry, "after")) {
    future.value.pop();
    history.value.push(entry);
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
  const modifier = event.metaKey || event.ctrlKey;
  if (modifier && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
  } else if (modifier && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redo();
  } else if (modifier && event.key.toLowerCase() === "k") {
    event.preventDefault();
    splitAtPlayhead();
  } else if (modifier && event.key.toLowerCase() === "j") {
    event.preventDefault();
    openAiPanel();
  } else if (event.code === "Space") {
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
  window.removeEventListener("pointermove", handleTrimMove);
  window.removeEventListener("pointerup", finishTrim);
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
.timeline-shell { margin-top: 10px; padding: 10px; overflow-x: auto; }
.timeline-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 32px; }
.timeline-meta { font: 700 10px ui-monospace, SFMono-Regular, Menlo, monospace; color: #6366f1; background: var(--surface-muted, #f2f4f7); border: 1px solid var(--outline-border, #e4e7ec); border-radius: 999px; padding: 2px 7px; }
.tool-btn { padding: 5px 8px; border: 1px solid var(--outline-border, #e4e7ec); border-radius: 7px; background: var(--surface-muted, #f2f4f7); font-size: 10px; font-weight: 700; color: var(--ink-secondary, #4b5565); }
.tool-btn:hover:not(:disabled), .tool-btn.active { border-color: #818cf8; color: #4f46e5; }
.ai-tool-btn { color: #5b21b6; background: #f5f3ff; border-color: #ddd6fe; }
.tool-btn.danger:hover:not(:disabled) { border-color: #fb7185; color: #e11d48; }
.tool-btn:disabled { opacity: .4; }
.timeline-ruler { position: relative; height: 32px; margin: 6px 0 4px; cursor: crosshair; border-bottom: 1px solid var(--outline-border, #e4e7ec); }
.ruler-labels { position: absolute; inset: 0; }
.ruler-labels span { position: absolute; top: 2px; transform: translateX(-50%); font: 9px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--ink-muted, #8b93a7); }
.ruler-labels span::after { content: ""; display: block; width: 1px; height: 8px; background: var(--outline-border, #d7dce5); margin: 2px auto 0; }
.playhead { position: absolute; top: 0; bottom: -122px; width: 1px; background: #6366f1; z-index: 10; pointer-events: none; }
.playhead-head { position: absolute; top: -1px; left: -4px; width: 9px; height: 9px; border-radius: 2px 2px 5px 5px; background: #6366f1; }
.clip-track { min-height: 112px; overflow: visible; padding: 4px 0 8px; }
.timeline-canvas { position: relative; min-height: 112px; }
.timeline-clip { position: absolute; top: 4px; bottom: 8px; border: 1px solid var(--outline-border, #dfe3ea); border-radius: 9px; padding: 6px; background: var(--surface-muted, #f5f6f9); cursor: pointer; transition: border-color .12s, box-shadow .12s; }
.timeline-clip:hover { border-color: #a5b4fc; }
.timeline-clip.selected { border-color: #6366f1; box-shadow: 0 0 0 2px rgb(99 102 241 / 15%); background: rgb(99 102 241 / 4%); }
.clip-title-row { display: flex; align-items: center; justify-content: space-between; gap: 5px; height: 18px; font-size: 10px; font-weight: 800; }
.clip-filmstrip { position: relative; height: 58px; border-radius: 6px; overflow: hidden; background: #0b0d12; }
.clip-thumb { width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
.clip-thumb-empty { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #7d8493; }
.clip-frame-overlay { position: absolute; inset: auto 4px 3px; display: flex; justify-content: space-between; color: white; font: 8px ui-monospace, SFMono-Regular, Menlo, monospace; text-shadow: 0 1px 4px black; }
.clip-range { display: flex; justify-content: space-between; margin-top: 4px; color: var(--ink-muted, #8790a3); font: 8px ui-monospace, SFMono-Regular, Menlo, monospace; }
.transition-node { position: absolute; top: 42px; transform: translateX(-50%); width: 26px; height: 26px; z-index: 3; border-radius: 999px; border: 1px solid var(--outline-border, #dfe3ea); background: var(--surface-card, #fff); color: var(--ink-muted, #8790a3); font-size: 12px; }
.trim-handle { position: absolute; top: 20px; bottom: 20px; width: 7px; z-index: 4; border: 0; border-radius: 4px; background: rgb(99 102 241 / 75%); opacity: 0; cursor: ew-resize; }
.timeline-clip:hover .trim-handle, .timeline-clip.selected .trim-handle { opacity: 1; }
.trim-handle-left { left: 1px; }
.trim-handle-right { right: 1px; }
.zoom-control { display: inline-flex; align-items: center; gap: 3px; padding: 3px 6px; border: 1px solid var(--outline-border, #e4e7ec); border-radius: 7px; color: var(--ink-muted, #8790a3); font-size: 11px; }
.zoom-control input { width: 58px; accent-color: #6366f1; }
.transition-node.active { border-color: #818cf8; color: #6366f1; background: #eef2ff; }
.empty-timeline { padding: 28px; text-align: center; color: var(--ink-muted, #8790a3); font-size: 11px; }
.editor-inspector { min-width: 0; border-left: 1px solid var(--outline-border, #e4e7ec); background: var(--surface-card, #fff); overflow-y: auto; }
.inspector-header { height: 48px; padding: 0 14px; border-bottom: 1px solid var(--outline-border, #e4e7ec); display: flex; align-items: center; justify-content: space-between; font-size: 11px; }
.inspector-tabs { padding: 0 8px; gap: 2px; justify-content: flex-start; }
.inspector-tab { height: 100%; padding: 0 7px; border-bottom: 2px solid transparent; color: var(--ink-muted, #8790a3); font-size: 10px; font-weight: 800; white-space: nowrap; }
.inspector-tab.active { color: #4f46e5; border-bottom-color: #6366f1; }
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
.prompt-field { margin-top: 9px; }
.prompt-field span { display: block; margin-bottom: 3px; color: var(--ink-muted, #8790a3); font-size: 9px; font-weight: 800; text-transform: uppercase; letter-spacing: .03em; }
.prompt-field p { margin: 0; color: var(--ink-secondary, #596174); font-size: 10px; line-height: 1.45; white-space: pre-wrap; }
.reference-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin-top: 8px; }
.reference-item { min-width: 0; display: flex; flex-direction: column; gap: 4px; color: var(--ink-secondary, #596174); font-size: 9px; }
.reference-item img { width: 100%; height: 58px; object-fit: cover; border-radius: 6px; border: 1px solid var(--outline-border, #e4e7ec); background: #f2f4f7; }
.reference-file { height: 58px; display: flex; align-items: center; justify-content: center; border-radius: 6px; background: #eef2ff; color: #4f46e5; font-size: 18px; }
.metadata-row { display: flex; justify-content: space-between; gap: 8px; margin-top: 7px; font-size: 9px; color: var(--ink-muted, #8790a3); }
.metadata-row strong { max-width: 62%; color: var(--ink-secondary, #596174); font-weight: 700; text-align: right; overflow-wrap: anywhere; }
.ai-card { background: linear-gradient(180deg, #faf9ff, var(--surface-muted, #f7f8fa)); }
.ai-label { margin-top: 12px; }
.ai-input { width: 100%; margin-top: 9px; resize: vertical; border: 1px solid var(--outline-border, #dfe3ea); border-radius: 8px; padding: 8px; background: var(--surface-card, #fff); color: var(--ink-primary, #172033); font-size: 10px; line-height: 1.45; }
.ai-input:focus { outline: 2px solid rgb(99 102 241 / 20%); border-color: #818cf8; }
.ai-submit { margin-top: 8px; color: #6b7280; cursor: not-allowed; }
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
