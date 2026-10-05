<template>
  <div class="flex flex-col items-center w-full">
    <!-- Viewport Container with CapCut dark canvas border -->
    <div
      ref="viewport"
      class="gflow-viewport w-full max-w-[760px] max-h-[41vh] bg-black/90 rounded-2xl overflow-hidden relative flex items-center justify-center border border-outline-border shadow-2xl transition-all"
      :class="{
        'ratio-landscape': settingsFormat === 'Landscape',
        'ratio-portrait': settingsFormat === 'Portrait',
        'ratio-square': settingsFormat === 'Square'
      }"
    >
      <!-- The scene's on-screen caption, as the export will draw it -->
      <div v-if="caption" class="pointer-events-none absolute inset-x-0 bottom-[12%] z-20 flex justify-center px-6">
        <span class="preview-caption text-center text-white text-sm sm:text-lg">{{ caption }}</span>
      </div>

      <!-- Floating Scene / Target HUD Chip -->
      <div class="viewport-hud-chip">
        <span class="size-2 rounded-full bg-indigo-500 animate-pulse" />
        <span v-if="studioMode === 'edit' && selectedClip">
          ✂️ {{ selectedClip.shot_number ? t('shot_n', { n: selectedClip.shot_number }) : selectedClip.track_type === 'Audio' ? (currentLang === 'vi' ? 'Nhạc nền' : 'Music') : !selectedClip.shot ? (currentLang === 'vi' ? 'Chuyển cảnh' : 'Transition') : `Clip ${selectedClip.clip_order || 1}` }} · {{ selectedClip.duration_seconds?.toFixed(2) }}s ({{ selectedClip.source_in_frame }}f–{{ selectedClip.source_out_frame }}f)
        </span>
        <span v-else-if="selectedTarget === 'asset' && selectedAsset">
          🖼️ {{ selectedAsset.asset_name }} · {{ selectedAsset.asset_category }}
        </span>
        <span v-else-if="selectedTarget === 'keyframe-start' && activeSelectedShot">
          ◆ {{ currentLang === 'vi' ? 'Khung đầu (In)' : 'Start Frame' }} · {{ t('shot_n', { n: activeSelectedShot.shot_number }) }}
        </span>
        <span v-else-if="selectedTarget === 'keyframe-end' && activeSelectedShot">
          ◆ {{ currentLang === 'vi' ? 'Khung cuối (Out)' : 'End Frame' }} · {{ t('shot_n', { n: activeSelectedShot.shot_number }) }}
        </span>
        <span v-else-if="previewSelection === 'master'">
          🎬 {{ currentLang === 'vi' ? 'Toàn bộ video' : 'Full Video' }} · 00:00–{{ formatSecondsLabel(timelineTotalSeconds) }}
        </span>
        <span v-else-if="activeSelectedShot">
          🎯 {{ t('shot_n', { n: activeSelectedShot.shot_number }) }} · {{ getShotTimestampRange(activeSelectedShot) }}
        </span>
      </div>

      <!-- Outdated result notice banner -->
      <div
        v-if="isOutdated && finalVideo?.file"
        class="absolute top-12 left-3 right-3 z-20 px-3 py-1.5 rounded-xl bg-amber-500/95 text-amber-950 backdrop-blur-md text-[11px] font-semibold flex items-center gap-2 shadow-lg"
      >
        <span>⚠️</span>
        <span class="truncate">{{ currentLang === 'vi' ? 'Kết quả phiên bản trước: Tư liệu hoặc cài đặt đã thay đổi. Tạo video mới để cập nhật.' : 'Previous result: References or settings have changed. Generate to update this video.' }}</span>
      </div>

      <!-- Keep generation errors inside the canvas -->
      <div v-if="productionError" class="flex flex-col items-center justify-center text-center p-6 space-y-2">
        <span class="size-12 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center text-xl mb-1 border border-rose-500/30">✕</span>
        <h3 class="text-sm font-bold text-ink-primary">{{ currentLang === 'vi' ? 'Không thể tạo video' : 'Video generation failed' }}</h3>
        <p class="text-xs text-rose-300 max-w-lg break-words whitespace-pre-wrap">{{ productionError }}</p>
        <p v-if="productionStatus" class="text-[11px] text-ink-muted">{{ currentLang === 'vi' ? 'Trạng thái' : 'Status' }}: {{ productionStatus }}</p>
        <div class="flex items-center gap-2 pt-2">
          <button type="button" class="px-3.5 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-xs cursor-pointer" @click="$emit('retryFailedScenes')">
            {{ currentLang === 'vi' ? 'Thử lại' : 'Retry' }}
          </button>
          <button type="button" class="px-3.5 py-1.5 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold shadow-xs cursor-pointer" @click="$emit('refresh')">
            {{ currentLang === 'vi' ? 'Làm mới' : 'Refresh' }}
          </button>
        </div>
      </div>

      <!-- Video Preview: Master, Edit Clip, or Scene Shot Video -->
      <video
        v-else-if="studioPreview?.isVideo && studioPreview?.url"
        ref="previewVideo"
        :key="studioPreview.type === 'clip' ? `${studioPreview.clip?.name}-${studioPreview.url}` : studioPreview.url"
        :src="studioPreview.url"
        :muted="props.isMuted || studioMode === 'edit'"
        class="w-full h-full object-contain"
        preload="auto"
        playsinline
        @loadedmetadata="onLoadedMetadata"
        @timeupdate="onTimeUpdate"
        @play="onPlay"
        @pause="onPause"
        @ended="onEnded"
        @error="onError"
      />

      <!-- Image Preview: Selected Shot Frame or Asset -->
      <img
        v-else-if="studioPreview?.url"
        :key="studioPreview.url"
        :src="studioPreview.url"
        :alt="studioPreview.title || 'Preview'"
        class="w-full h-full object-contain"
      />

      <!-- Fallback Frame of Selected Shot -->
      <img
        v-else-if="selectedShotFrame?.file"
        :src="selectedShotFrame.file"
        :alt="selectedShotFrame.name"
        class="w-full h-full object-contain"
      />

      <!-- Live Generating Radar Overlay -->
      <div v-else-if="isProductionActive" class="flex flex-col items-center justify-center text-center p-6">
        <div class="relative size-14 mb-3 flex items-center justify-center">
          <span class="lucide-refresh-cw size-9 animate-spin text-indigo-400" />
          <span class="absolute text-[11px] font-bold font-mono text-ink-primary">{{ production?.progress || 0 }}%</span>
        </div>
        <h3 class="text-sm font-semibold text-ink-primary">
          {{ currentLang === 'vi' ? 'Đang kết xuất video quảng cáo...' : 'Rendering video ad...' }}
        </h3>
        <p class="text-xs text-ink-muted mt-1">
          <template v-if="production?.shots?.length || production?.total_tasks">
            {{ completedShotCount(production) }} / {{ production?.shots?.length || production?.total_tasks }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes completed' }}
          </template>
          <template v-else>
            {{ currentLang === 'vi' ? 'Đang lập storyboard…' : 'Planning storyboard…' }}
          </template>
        </p>
      </div>

      <!-- Blank Canvas Placeholder -->
      <div v-else class="flex flex-col items-center justify-center text-center p-8 text-ink-muted">
        <span class="size-14 rounded-2xl bg-surface-card border border-outline-border flex items-center justify-center mb-3 text-ink-secondary text-2xl shadow-md">🎬</span>
        <template v-if="activeSelectedShot">
          <p class="text-sm text-ink-primary font-semibold">{{ t('shot_n', { n: activeSelectedShot.shot_number }) }}</p>
          <p class="text-xs text-ink-muted mt-1">{{ currentLang === 'vi' ? 'Chưa có video kết xuất cho cảnh này.' : 'No generated video is available for this shot yet.' }}</p>
        </template>
        <template v-else>
          <p class="text-sm text-ink-primary font-semibold">{{ currentLang === 'vi' ? 'Sẵn sàng sản xuất video' : 'Ready to create video' }}</p>
          <p class="text-xs text-ink-muted mt-1 max-w-sm">{{ currentLang === 'vi' ? 'Nhập ý tưởng và thêm tư liệu tham chiếu bên dưới để bắt đầu tạo video.' : 'Enter your video prompt and add reference media below to generate scenes.' }}</p>
        </template>
      </div>
    </div>

    <!-- Playback Transport: Render ONLY when previewing real video -->
    <PlaybackTransport
      v-if="studioPreview?.isVideo && studioPreview?.url"
      :active-selected-shot="activeSelectedShot"
      :current-lang="currentLang"
      :current-timeline-position-label="currentTimelinePositionLabel"
      :is-playing="isPlaying"
      :is-muted="props.isMuted"
      :timeline-total-seconds="timelineTotalSeconds"
      @fullscreen="requestFullscreen"
      @step-frame="$emit('stepFrame', $event)"
      @toggle-mute="toggleMute"
      @toggle-play-pause="$emit('togglePlayPause')"
    />
  </div>
</template>

<script setup>
import { ref, watch } from "vue";
import { useI18n } from "../../stores/i18n";
import PlaybackTransport from "./PlaybackTransport.vue";

const { t } = useI18n();

const previewVideo = ref(null);
const viewport = ref(null);
const props = defineProps({
  // On-screen caption of the scene on screen; empty for none.
  caption: { type: String, default: "" },
  studioMode: { type: String, default: "scene" },
  studioPreview: { type: Object, default: null },
  selectedTarget: { type: String, default: "scene" },
  selectedAsset: { type: Object, default: null },
  activeSelectedShot: { type: Object, default: null },
  selectedClip: { type: Object, default: null },
  selectedShotFrame: { type: Object, default: null },
  previewSelection: { type: String, default: "master" },
  timelineTotalSeconds: { type: Number, default: 0 },
  currentTimelinePositionLabel: { type: String, default: "00:00" },
  isPlaying: { type: Boolean, default: false },
  isMuted: { type: Boolean, default: false },
  isProductionActive: { type: Boolean, default: false },
  production: { type: Object, default: null },
  productionError: { type: String, default: "" },
  productionStatus: { type: String, default: "" },
  projectAssets: { type: Array, default: () => [] },
  settingsFormat: { type: String, default: "Landscape" },
  finalVideo: { type: Object, default: null },
  selectedShotIndex: { type: Number, default: 0 },
  currentLang: { type: String, default: "vi" },
  isOutdated: { type: Boolean, default: false },
  getShotTimestampRange: { type: Function, default: () => "00:00-00:04" },
});

const emit = defineEmits([
  "togglePlayPause",
  "toggleMute",
  "loadedmetadata",
  "timeupdate",
  "play",
  "pause",
  "ended",
  "error",
  "selectFullVideo",
  "selectClip",
  "selectShotTarget",
  "jumpToPrevKeyframe",
  "jumpToNextKeyframe",
  "toggleKeyframeAtPlayhead",
  "retryFailedScenes",
  "refresh",
  "openMediaPicker",
  "stepFrame",
]);

// The parent's isPlaying commands the <video>; the element's own play/pause
// events are reported back only when they differ from that command. Reporting
// the echo of our own play()/pause() calls makes parent and element flip each
// other forever when playback is toggled quickly (e.g. jumping between scenes).
let commandedPlaying = props.isPlaying;

async function applyPlayback(playing) {
  commandedPlaying = playing;
  const video = previewVideo.value;
  if (!video) return;
  if (!playing) {
    video.pause();
    return;
  }
  try {
    await video.play();
  } catch (err) {
    // AbortError only means a newer pause()/source change superseded this play().
    if (err?.name !== "AbortError" && commandedPlaying) {
      console.warn("Video playback was blocked:", err);
      commandedPlaying = false;
      emit("pause", err);
    }
  }
}

watch(() => props.isPlaying, applyPlayback);

function onLoadedMetadata(event) {
  emit("loadedmetadata", {
    duration: event.target.duration,
    videoWidth: event.target.videoWidth,
    videoHeight: event.target.videoHeight,
    event,
  });
  if (props.isPlaying) applyPlayback(true);
}

function onTimeUpdate(event) {
  emit("timeupdate", {
    currentTime: event.target.currentTime,
    duration: event.target.duration,
    event,
  });
}

function onPlay(event) {
  // Media events are delivered late: a "play" from an earlier play() can arrive
  // after a newer pause(). Only a playing element reports a real play.
  if (event.target !== previewVideo.value || commandedPlaying || event.target.paused) return;
  commandedPlaying = true;
  emit("play", event);
}

function onPause(event) {
  // Timeline/Edit playback is owned by the global timeline clock, not by the
  // lifecycle of one physical Shot file. A clip reaching its end or being
  // replaced by the next clip can fire a native pause event while the global
  // timeline is intentionally still playing. Ignore that internal pause.
  if (props.studioMode === "edit" && props.isPlaying) return;
  // A replaced <video> (new source) fires a late pause when it is removed.
  if (event.target !== previewVideo.value || !commandedPlaying || !event.target.paused) return;
  commandedPlaying = false;
  emit("pause", event);
}

function onEnded(event) {
  emit("ended", event);
  // In Timeline/Edit mode the global timeline clock owns playback. Reaching
  // the end of one physical Shot file must not pause the whole edit; the
  // parent switches to the next Timeline Clip and keeps isPlaying true.
  if (props.studioMode !== "edit") {
    commandedPlaying = false;
    emit("pause", event);
  }
}

function onError(event) {
  console.warn("Video playback element encountered error:", event);
  emit("error", event);
}

function seek(timeInSeconds) {
  if (previewVideo.value && Number.isFinite(timeInSeconds)) {
    previewVideo.value.currentTime = Math.max(0, timeInSeconds);
  }
}

function formatSecondsLabel(totalSeconds) {
  const safeSeconds = Math.max(0, Number(totalSeconds || 0));
  const mins = Math.floor(safeSeconds / 60);
  const secs = Math.floor(safeSeconds % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function completedShotCount(production) {
  return (production?.shots || []).filter((shot) => shot.status === "Completed").length;
}

function toggleMute() {
	emit("toggleMute");
}

function requestFullscreen() {
	viewport.value?.requestFullscreen?.();
}

defineExpose({
  previewVideo,
  seek,
});
</script>

<style scoped>
.ratio-landscape {
  aspect-ratio: 16 / 9;
}
.ratio-portrait {
  aspect-ratio: 9 / 16;
  max-width: 495px !important;
}
.ratio-square {
  aspect-ratio: 1 / 1;
  max-width: 620px !important;
}

.preview-caption {
  font-family: "Playfair Display", Georgia, serif;
  text-shadow: 0 2px 3px rgb(0 0 0 / 0.6);
}

.viewport-hud-chip {
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
  color: #f3f4f6;
  background: rgba(17, 24, 39, 0.75);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.file-input-hidden {
  display: none;
}
</style>
