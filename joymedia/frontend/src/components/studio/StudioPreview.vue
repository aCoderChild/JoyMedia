<template>
  <div class="flex flex-col items-center w-full">
    <!-- Viewport Container with CapCut dark canvas border -->
    <div
      class="gflow-viewport w-full max-w-[760px] max-h-[41vh] bg-black/90 rounded-2xl overflow-hidden relative flex items-center justify-center border border-outline-border shadow-2xl transition-all"
      :class="{
        'ratio-landscape': settingsFormat === 'Landscape',
        'ratio-portrait': settingsFormat === 'Portrait',
        'ratio-square': settingsFormat === 'Square'
      }"
    >
      <!-- Floating Scene / Target HUD Chip -->
      <div class="viewport-hud-chip">
        <span class="size-2 rounded-full bg-indigo-500 animate-pulse" />
        <span v-if="studioMode === 'edit' && selectedClip">
          ✂️ {{ selectedClip.shot_number ? t('shot_n', { n: selectedClip.shot_number }) : `Clip ${selectedClip.clip_order || 1}` }} · {{ selectedClip.duration_seconds?.toFixed(2) }}s ({{ selectedClip.source_in_frame }}f–{{ selectedClip.source_out_frame }}f)
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
        <span v-else-if="previewSelection === 'full'">
          🎬 {{ currentLang === 'vi' ? 'Toàn bộ video' : 'Full Video' }} · 00:00–{{ formatSecondsLabel(timelineTotalSeconds) }}
        </span>
        <span v-else-if="activeSelectedShot">
          🎯 {{ t('shot_n', { n: activeSelectedShot.shot_number }) }} · {{ getShotTimestampRange(activeSelectedShot) }}
        </span>
      </div>

      <!-- 62% Zoom Badge -->
      <div class="absolute top-3.5 right-3.5 z-10 text-[11px] font-mono text-ink-secondary bg-surface-card/90 backdrop-blur-md px-2 py-0.5 rounded-md border border-outline-border shadow-xs">
        62%
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
        class="w-full h-full object-contain"
        preload="metadata"
        playsinline
        @loadedmetadata="onLoadedMetadata"
        @timeupdate="onTimeUpdate"
        @play="$emit('play', $event)"
        @pause="$emit('pause', $event)"
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
          {{ completedShotCount(production) }} / {{ production?.shots?.length || (production?.total_tasks || 4) }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes completed' }}
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
      :final-video="finalVideo"
      :is-playing="isPlaying"
      :preview-selection="previewSelection"
      :selected-shot-index="selectedShotIndex"
      :timeline-total-seconds="timelineTotalSeconds"
      @fullscreen="requestFullscreen"
      @next-shot="$emit('jumpToNextKeyframe')"
      @previous-shot="$emit('jumpToPrevKeyframe')"
      @select-full-video="$emit('selectFullVideo')"
      @select-shot-target="$emit('selectShotTarget', activeSelectedShot, selectedShotIndex)"
      @toggle-mute="toggleMute"
      @toggle-play-pause="$emit('togglePlayPause')"
    />

    <!-- Legacy transport retained as a non-rendered fallback during migration. -->
    <div v-if="false" class="flex items-center justify-between w-full max-w-[880px] mt-1.5 px-3 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-secondary shadow-xs">
      <div class="flex items-center gap-2.5">
        <button
          type="button"
          class="size-6 rounded-lg bg-surface-muted hover:bg-surface-hover flex items-center justify-center font-bold text-ink-primary transition-colors cursor-pointer"
          :title="isPlaying ? (currentLang === 'vi' ? 'Tạm dừng' : 'Pause') : (currentLang === 'vi' ? 'Phát' : 'Play')"
          @click="$emit('togglePlayPause')"
        >
          <span>{{ isPlaying ? '⏸' : '▶' }}</span>
        </button>
        <span class="font-mono text-[11px] font-semibold text-ink-primary">
          {{ currentTimelinePositionLabel }} / {{ formatSecondsLabel(timelineTotalSeconds) }}
        </span>
        <span class="text-ink-muted text-[10px]">·</span>
        <span v-if="studioMode === 'edit' && selectedClip" class="text-[11px] text-ink-secondary truncate max-w-[180px]">
          Clip {{ selectedClip.clip_order || 1 }} ({{ selectedClip.duration_seconds?.toFixed(1) }}s)
        </span>
        <span v-else-if="activeSelectedShot" class="text-[11px] text-ink-secondary truncate max-w-[180px]">
          {{ t('shot_n', { n: activeSelectedShot.shot_number }) }} ({{ getShotTimestampRange(activeSelectedShot) }})
        </span>
      </div>

      <!-- Keyframe Quick Navigation & Toggle (Only in Scenes Mode) -->
      <div v-if="studioMode === 'scene'" class="flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-surface-muted border border-outline-border text-xs">
        <button
          type="button"
          class="size-5 rounded flex items-center justify-center text-[10px] text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Đến Keyframe trước' : 'Previous Keyframe'"
          @click="$emit('jumpToPrevKeyframe')"
        >
          ◀
        </button>
        <button
          type="button"
          class="size-5 rounded flex items-center justify-center transition-all cursor-pointer"
          :class="isPlayheadAtKeyframe ? 'text-indigo-400 font-bold scale-110' : 'text-ink-muted hover:text-ink-primary'"
          :title="isPlayheadAtKeyframe ? (currentLang === 'vi' ? 'Keyframe đang kích hoạt (Click để xem cảnh)' : 'Active Keyframe at playhead') : (currentLang === 'vi' ? 'Thêm / Đặt Keyframe tại playhead' : 'Add Keyframe at playhead')"
          @click="$emit('toggleKeyframeAtPlayhead')"
        >
          <span class="text-xs leading-none">{{ isPlayheadAtKeyframe ? '◆' : '◇' }}</span>
        </button>
        <button
          type="button"
          class="size-5 rounded flex items-center justify-center text-[10px] text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Đến Keyframe tiếp theo' : 'Next Keyframe'"
          @click="$emit('jumpToNextKeyframe')"
        >
          ▶
        </button>
      </div>

      <!-- Outdated/Unsaved Indicator in Edit Mode -->
      <div v-else-if="studioMode === 'edit' && isOutdated" class="text-[10.5px] text-amber-400 font-semibold px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
        ⚠️ {{ currentLang === 'vi' ? 'Có bản tạo mới hơn' : 'New version available' }}
      </div>

      <div class="flex items-center gap-1.5">
        <button
          v-if="finalVideo?.file"
          type="button"
          class="px-2 py-0.5 rounded-lg text-[10.5px] font-semibold transition-colors cursor-pointer"
          :class="previewSelection === 'full' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-surface-muted hover:bg-surface-hover text-ink-secondary'"
          @click="$emit('selectFullVideo')"
        >
          {{ currentLang === 'vi' ? 'Toàn bộ video' : 'Full Video' }}
        </button>
        <button
          v-if="studioMode === 'edit' && selectedClip"
          type="button"
          class="px-2 py-0.5 rounded-lg text-[10.5px] font-semibold transition-colors cursor-pointer"
          :class="previewSelection === 'clip' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-surface-muted hover:bg-surface-hover text-ink-secondary'"
          @click="$emit('selectClip')"
        >
          Clip {{ selectedClip.clip_order || 1 }}
        </button>
        <button
          v-else-if="activeSelectedShot"
          type="button"
          class="px-2 py-0.5 rounded-lg text-[10.5px] font-semibold transition-colors cursor-pointer"
          :class="previewSelection === 'shot' && selectedTarget !== 'asset' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-surface-muted hover:bg-surface-hover text-ink-secondary'"
          @click="$emit('selectShotTarget', activeSelectedShot, selectedShotIndex)"
        >
          {{ currentLang === 'vi' ? `Cảnh ${activeSelectedShot.shot_number}` : `Shot ${activeSelectedShot.shot_number}` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";
import { useI18n } from "../../stores/i18n";
import PlaybackTransport from "./PlaybackTransport.vue";

const { t } = useI18n();

const previewVideo = ref(null);

const props = defineProps({
  studioMode: { type: String, default: "scene" },
  studioPreview: { type: Object, default: null },
  selectedTarget: { type: String, default: "scene" },
  selectedAsset: { type: Object, default: null },
  activeSelectedShot: { type: Object, default: null },
  selectedClip: { type: Object, default: null },
  selectedShotFrame: { type: Object, default: null },
  previewSelection: { type: String, default: "full" },
  timelineTotalSeconds: { type: Number, default: 0 },
  currentTimelinePositionLabel: { type: String, default: "00:00" },
  isPlaying: { type: Boolean, default: false },
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
]);

watch(
  () => props.isPlaying,
  async (playing) => {
    if (!previewVideo.value) return;
    if (playing) {
      try {
        await previewVideo.value.play();
      } catch (err) {
        console.warn("Video play interrupted/failed:", err);
      }
    } else {
      previewVideo.value.pause();
    }
  }
);

function onLoadedMetadata(event) {
  emit("loadedmetadata", {
    duration: event.target.duration,
    videoWidth: event.target.videoWidth,
    videoHeight: event.target.videoHeight,
    event,
  });
  if (props.isPlaying) {
    previewVideo.value?.play()?.catch(() => {});
  }
}

function onTimeUpdate(event) {
  emit("timeupdate", {
    currentTime: event.target.currentTime,
    duration: event.target.duration,
    event,
  });
}

function onEnded(event) {
  emit("ended", event);
  emit("pause", event);
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
  if (previewVideo.value) previewVideo.value.muted = !previewVideo.value.muted;
}

function requestFullscreen() {
  previewVideo.value?.requestFullscreen?.();
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
