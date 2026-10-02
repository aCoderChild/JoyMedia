<template>
  <div class="project-studio-root relative flex flex-col w-screen h-screen overflow-hidden bg-surface-base text-ink-primary">
    <!-- 1. Single Studio Header (Full width across top: Projects | Title | Media | Export) -->
    <StudioHeader
      :project-name="projectName"
      :project-title="projectTitle"
      :project-status="projectStatus"
      :timeline-ready="timelineReady"
      :has-unexported-edits="hasUnexportedEdits"
      :is-exporting="isExporting"
      :export-status="exportStatus"
      :current-output-asset-version="currentOutputAssetVersion"
      :media-drawer-open="mediaDrawerOpen"
      :project-assets-count="projectAssets.length"
      :current-lang="currentLang"
      :user="user"
      @go-back="router.push('/campaigns')"
      @save-project-name="updateProjectName"
      @toggle-media-drawer="mediaDrawerOpen = !mediaDrawerOpen"
      @toggle-lang="toggleLang"
      @open-settings="showSettings = true"
      @export-timeline="exportTimeline"
    />

    <!-- 2. Studio Workspace Body: Media Drawer + Canvas + Contextual Inspector -->
    <div class="flex-1 flex min-h-0 w-full overflow-hidden relative">
      <!-- Media Drawer (Begins below header, 270px width, pushes canvas) -->
      <MediaDrawer
        v-if="mediaDrawerOpen"
        :project-assets="projectAssets"
        :selected-asset="selectedAsset"
        :current-lang="currentLang"
        @close="mediaDrawerOpen = false"
        @select-asset="onSelectAssetTarget"
        @remove-asset="removeReference"
        @open-media-picker="openPicker"
      />

      <!-- Center Stage Canvas: Viewport + Timeline -->
      <div class="studio-center-canvas flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-surface-base">
        <!-- Scrollable Studio Canvas -->
        <div class="flex-1 overflow-y-auto p-3 sm:p-4 space-y-4">
        <!-- Error Alert Banner -->
        <div v-if="productionError" class="p-3 rounded-xl border border-rose-500/40 bg-rose-500/10 text-xs flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-rose-300 min-w-0">
            <span class="text-rose-400 font-bold">✕</span>
            <span class="truncate">{{ productionError }}</span>
          </div>
          <button
            type="button"
            class="px-3 py-1 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold shrink-0 cursor-pointer"
            @click="handleGenerationRetry"
          >
            {{ currentLang === 'vi' ? 'Thử lại' : 'Retry' }}
          </button>
        </div>

        <!-- Cinema Viewport Hero (StudioPreview) -->
        <div class="flex flex-col items-center justify-center w-full" :class="studioMode === 'scene' ? 'max-h-[42vh] shrink-0' : 'min-h-[340px]'">
          <StudioPreview
            ref="studioPreviewRef"
            :studio-mode="studioMode"
            :studio-preview="studioPreview"
            :selected-target="selectedTarget"
            :selected-asset="selectedAsset"
            :active-selected-shot="activeSelectedShot"
            :selected-clip="selectedClip"
            :selected-shot-frame="selectedShotFrame"
            :preview-selection="previewSelection"
            :timeline-total-seconds="playerTotalSeconds"
            :current-timeline-position-label="currentTimelinePositionLabel"
            :is-playing="isPlaying"
            :is-production-active="isProductionActive"
            :production="currentRun"
            :production-error="productionError"
            :production-status="projectStatus"
            :project-assets="projectAssets"
            :settings-format="videoSettings.delivery_preset"
            :final-video="finalVideo"
            :selected-shot-index="selectedShotIndex"
            :current-lang="currentLang"
            :is-outdated="isOutdated"
            :get-shot-timestamp-range="getShotTimestampRange"
            @toggle-play-pause="isPlaying = !isPlaying"
            @play="isPlaying = true"
            @pause="isPlaying = false"
            @loadedmetadata="onPreviewLoadedMetadata"
            @timeupdate="onVideoTimeUpdate"
            @jump-to-next-keyframe="jumpToNextShot"
            @jump-to-prev-keyframe="jumpToPrevShot"
            @select-full-video="previewSelection = 'full'"
            @select-clip="previewSelection = 'clip'"
            @select-shot-target="onSelectShot"
            @retry-failed-scenes="handleGenerationRetry"
            @refresh="fetchWorkspace"
            @open-media-picker="openPicker"
          />
        </div>

        <!-- Bottom Workspace Mode Switcher (Storyboard | Timeline) -->
        <div class="flex items-center justify-between px-1 pt-1 pb-0.5">
          <div class="inline-flex items-center p-0.5 rounded-xl bg-surface-card border border-outline-border text-xs shadow-xs">
            <button
              type="button"
              class="px-3.5 py-1 rounded-lg font-semibold transition-all flex items-center gap-1.5 cursor-pointer"
              :class="studioMode === 'scene'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'text-ink-secondary hover:text-ink-primary'"
              aria-label="Storyboard / Scenes"
              @click="studioMode = 'scene'"
            >
              <span>🎞️</span>
              <span>{{ currentLang === 'vi' ? 'Storyboard' : 'Storyboard' }}</span>
              <span class="text-[10px] opacity-75 font-normal">({{ currentLang === 'vi' ? 'Phân cảnh' : 'Scenes' }})</span>
            </button>

            <button
              type="button"
              class="px-3.5 py-1 rounded-lg font-semibold transition-all flex items-center gap-1.5 cursor-pointer"
              :class="[
                studioMode === 'edit'
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : 'text-ink-secondary hover:text-ink-primary',
                { 'opacity-50 cursor-not-allowed': !timelineReady }
              ]"
              :disabled="!timelineReady"
              aria-label="Timeline / Edit"
              :title="!timelineReady ? (currentLang === 'vi' ? 'Cần tạo video xong để mở Timeline' : 'Generate video to enable Timeline') : ''"
              @click="studioMode = 'edit'"
            >
              <span>✂</span>
              <span>{{ currentLang === 'vi' ? 'Dòng thời gian' : 'Timeline' }}</span>
              <span class="text-[10px] opacity-75 font-normal">({{ currentLang === 'vi' ? 'Biên tập' : 'Edit' }})</span>
            </button>
          </div>

          <div class="text-[11px] text-ink-muted">
            <span v-if="studioMode === 'scene'">
              {{ storyboardShots.length }} {{ currentLang === 'vi' ? 'cảnh trong kịch bản' : 'scenes in storyboard' }}
            </span>
            <span v-else>
              {{ clips.length }} {{ currentLang === 'vi' ? 'phân đoạn trên timeline' : 'clips on timeline' }}
            </span>
          </div>
        </div>

        <!-- Legacy or Orphaned Project Output (Final video exists but 0 scenes) -->
        <div
          v-if="finalVideo?.file && storyboardShots.length === 0"
          class="p-3.5 mb-2 rounded-2xl bg-surface-card border border-amber-500/40 text-xs flex flex-wrap items-center justify-between gap-3 shadow-xs"
        >
          <div class="space-y-0.5">
            <div class="font-bold text-amber-400 flex items-center gap-1.5">
              <span>🎞️</span>
              <span>{{ currentLang === 'vi' ? 'Video phiên bản trước' : 'Previous generated video' }}</span>
            </div>
            <p class="text-[11px] text-ink-muted">
              {{ currentLang === 'vi' ? 'Kết quả cũ này không có dữ liệu phân cảnh để chỉnh sửa.' : 'This older result has no editable scene data.' }}
            </p>
          </div>
          <button
            type="button"
            class="jm-btn-primary !py-1.5 !px-3 text-xs"
            @click="generateVideo"
          >
            {{ currentLang === 'vi' ? 'Tạo phiên bản mới' : 'Create new version' }}
          </button>
        </div>

        <!-- 3. SCENE MODE: Simple Generation Composer + Scene Filmstrip -->
        <template v-if="studioMode === 'scene'">
          <!-- Generation Composer (Describe video + reference chips + Generate button) -->
          <GenerationComposer
            v-model:prompt="videoIdeaPrompt"
            :project-assets="projectAssets"
            :is-generating="isGenerating || isProductionActive"
            :is-improving-prompt="improvingIdea"
            :has-storyboard="Boolean(storyboardShots.length)"
            :duration-seconds="videoSettings.duration || 15"
            :delivery-preset="videoSettings.delivery_preset || 'Landscape'"
            :current-lang="currentLang"
            @generate="generateVideo"
            @open-media-picker="openPicker"
            @open-settings="showSettings = true"
            @improve-prompt="improveVideoIdea"
          />

          <!-- Scene Filmstrip / Storyboard Track -->
          <SceneStrip
            :shots="storyboardShots"
            :selected-shot-index="selectedShotIndex"
            :selected-target="selectedTarget"
            :generation-mode="videoSettings.generation_mode"
            :total-duration-seconds="videoSettings.duration || 15"
            :has-storyboard="Boolean(storyboardShots.length)"
            :is-generating="isGenerating || isProductionActive"
            :is-revising="isRevising"
            :expected-shot-count="storyboardShots.length || currentRun?.total_tasks || 0"
            :production="currentRun"
            :current-lang="currentLang"
            :estimate-shot-duration="estimateShotDuration"
            :format-shot-keyframe-time="formatShotKeyframeTime"
            :get-shot-video-file="getShotVideoFile"
            :get-shot-first-frame="getShotFirstFrame"
            @select-shot="onSelectShot"
            @select-keyframe="onSelectKeyframe"
            @change-shot-duration="changeShotDuration"
            @toggle-continuity-mode="toggleContinuityMode"
            @revise-storyboard="reviseStoryboard"
            @reorder-shots="onReorderShots"
          />
        </template>

        <!-- 4. EDIT MODE: Editorial Tracks (Video + Music / Audio) -->
        <template v-else>
          <EditTimeline
            :clips="clips"
            :video-clips="videoClips"
            :audio-clips="audioClips"
            :fps="fps"
            :selected-clip-name="selectedClipName"
            :playhead-frame="playheadFrame"
            :busy="timelineBusy"
            :total-frames="timeline?.total_frames || 0"
            :total-seconds="timeline?.total_seconds || 0"
            :current-lang="currentLang"
            @select-clip="onSelectClip"
            @update:playhead-frame="onSeekPlayhead"
            @trim="trimClip"
            @split="splitClip"
            @duplicate="duplicateClip"
            @delete="deleteClip"
            @reorder="reorderClip"
            @select-transition="setTransition"
            @open-audio-picker="openAudioPicker"
          />
        </template>
      </div>
    </div>

    <!-- Right Side: Selection-driven Contextual Inspector -->
    <StudioInspector
      v-if="inspectorOpen && hasInspectorSelection"
      v-model:open="inspectorOpen"
      :studio-mode="studioMode"
      :selected-target="selectedTarget"
      :selected-asset="selectedAsset"
      :active-selected-shot="activeSelectedShot"
      :selected-shot-index="selectedShotIndex"
      :selected-shot-frame="selectedShotFrame"
      :selected-clip="selectedClip"
      :selected-clip-source-shot="selectedClipSourceShot"
      :timeline-busy="timelineBusy"
      :fps="fps"
      :generation-mode="videoSettings.generation_mode"
      :current-duration="videoSettings.duration || 15"
      :current-preset="videoSettings.delivery_preset || 'Landscape'"
      :is-production-active="isProductionActive"
      :ai-revision-loading="aiRevisionLoading"
      :current-lang="currentLang"
      :estimate-shot-duration="estimateShotDuration"
      :format-shot-keyframe-time="formatShotKeyframeTime"
      @change-transition="onClipTransitionChange"
      @change-transition-frames="onClipTransitionFramesChange"
      @split-clip="splitClipAtPlayhead"
      @duplicate-clip="duplicateClip(selectedClip)"
      @delete-clip="deleteClip(selectedClip)"
      @update-audio-clip="onUpdateAudioClip"
      @update-source-for-selected-clip="onUpdateSourceForClip"
      @regenerate-source-for-selected-clip="onRegenerateSourceForClip"
      @apply-asset-to-shot="applyAssetToShot"
      @remove-asset="removeReference"
      @update-asset-role="updateReferenceRole"
      @select-keyframe-target="onSelectKeyframe"
      @toggle-generation-mode="toggleContinuityMode"
      @change-shot-duration="changeShotDuration"
      @regenerate-current-shot="regenerateCurrentShot"
      @save-active-shot="saveActiveShot"
      @ask-ai="onAskAiRewriteShot"
      @open-settings="showSettings = true"
      @open-media-picker="openPicker"
    />
  </div>

  <!-- Modal: Explicit Role Reference Picker -->
    <MediaPicker
      v-if="showMediaPicker"
      :candidates="mediaCandidates"
      :loading="candidatesLoading"
      :saving="savingReference"
      :uploading="uploadingMedia"
      :upload-error="uploadError"
      :last-uploaded-asset-version="lastUploadedAssetVersion"
      :initial-type-filter="mediaPickerFilter"
      :is-keyframe-target="selectedTarget === 'keyframe-start' || selectedTarget === 'keyframe-end'"
      :current-lang="currentLang"
      @close="showMediaPicker = false"
      @select-reference="handleSelectReference"
      @set-keyframe="onSetKeyframeFromPicker"
      @upload-files="uploadFilesToLibrary"
      @remove-reference="removeReference"
      @archive-asset="archiveMediaAsset"
    />

    <!-- Modal: Secondary Video Settings (Format, duration, style, instructions) -->
    <ProjectSettingsModal
      v-if="showSettings"
      :settings="videoSettings"
      :video-styles="videoStyles"
      :saving="savingSettings"
      :current-lang="currentLang"
      @close="showSettings = false"
      @save="saveVideoSettings"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { call, toast } from "frappe-ui";
import { useSession } from "../stores/session";
import { useI18n } from "../stores/i18n";

// Composables
import { useProjectWorkspace } from "../composables/useProjectWorkspace";
import { useProjectReferences } from "../composables/useProjectReferences";
import { useProjectGeneration } from "../composables/useProjectGeneration";
import { useProjectTimeline } from "../composables/useProjectTimeline";

// Studio Components
import StudioHeader from "../components/studio/StudioHeader.vue";
import MediaDrawer from "../components/studio/MediaDrawer.vue";
import GenerationComposer from "../components/studio/GenerationComposer.vue";
import StudioPreview from "../components/studio/StudioPreview.vue";
import SceneStrip from "../components/studio/SceneStrip.vue";
import EditTimeline from "../components/studio/EditTimeline.vue";
import StudioInspector from "../components/studio/StudioInspector.vue";
import MediaPicker from "../components/studio/MediaPicker.vue";
import ProjectSettingsModal from "../components/studio/ProjectSettingsModal.vue";

const route = useRoute();
const router = useRouter();
const { user } = useSession();
const { currentLang, toggleLang } = useI18n();

const projectName = computed(() => route.params.name);

// 1. Workspace composable
const {
  workspace,
  loading: workspaceLoading,
  studioMode,
  selectedTarget,
  selectedAsset,
  selectedShotIndex,
  inspectorOpen,
  showSettings,
  videoStyles,
  savingSettings,
  projectTitle,
  projectStatus,
  projectAssets,
  storyboard,
  storyboardShots,
  currentOutputAssetVersion,
  finalVideo,
  isOutdated: generationOutputOutdated,
  videoSettings,
  fetchWorkspace,
  fetchVideoStyles,
  updateProjectName,
  saveVideoSettings,
} = useProjectWorkspace(projectName);

// 2. References composable
const {
  showMediaPicker,
  mediaCandidates,
  candidatesLoading,
  savingReference,
  uploadingMedia,
  uploadError,
  lastUploadedAssetVersion,
  openPicker,
  addReference,
  updateReferenceRole,
  removeReference,
  archiveMediaAsset,
  setShotKeyframe,
  uploadFilesToLibrary,
} = useProjectReferences(projectName, fetchWorkspace);

// 3. Generation composable
const {
  isGenerating,
  isRevising,
  improvingIdea,
  aiRevisionLoading,
  productionError,
  videoIdeaPrompt,
  currentRun,
  isProductionActive,
  generateVideo,
  retryFailedScenes,
  reviseStoryboard,
  reviseShotWithAi,
  improveVideoIdea,
  stopPolling,
} = useProjectGeneration(projectName, fetchWorkspace);

// 4. Timeline composable
const {
  timeline,
  clips,
  videoClips,
  audioClips,
  fps,
  busy: timelineBusy,
  selectedClip,
  selectedClipName,
  playheadFrame,
  exportStatus,
  isExporting,
  isOutdated: timelineOutdated,
  loadTimeline,
  trimClip,
  reorderClip,
  splitClip,
  duplicateClip,
  deleteClip,
  setTransition,
  updateSourceForShot,
  updateAudioClip,
  addAudioClip,
  exportTimeline,
} = useProjectTimeline(projectName);

// Studio Local State
const studioPreviewRef = ref(null);
const mediaDrawerOpen = ref(false);
const isPlaying = ref(false);
const previewSelection = ref("shot"); // "shot" | "full" | "clip"
const mediaPickerFilter = ref("All");

// Automatically transition to Edit mode only when an active generation run finishes
watch(
  () => isProductionActive.value,
  async (active, prev) => {
    if (prev && !active) {
      await fetchWorkspace();
      await loadTimeline(true);
      if (finalVideo.value?.file && clips.value?.length) {
        studioMode.value = "edit";
      }
    }
  }
);

const pendingAudioRole = ref(null);

function openAudioPicker(role = "BGM") {
  pendingAudioRole.value = role;
  mediaPickerFilter.value = "Audio";
  openPicker();
}

async function onUpdateAudioClip(clip, settings) {
  await updateAudioClip(clip, settings);
}

async function handleSelectReference({ asset, role }) {
  // If user opened picker specifically to add an audio clip to a timeline track:
  if (pendingAudioRole.value) {
    const chosenRole = pendingAudioRole.value;
    pendingAudioRole.value = null;
    const assetVersion = asset.asset_version || asset.name;
    if (assetVersion) {
      await addAudioClip(assetVersion, playheadFrame.value || 0, chosenRole);
      toast({
        title: "Audio added",
        text: `Added ${asset.asset_name || "audio"} to ${chosenRole} track.`,
        type: "success",
      });
    }
    showMediaPicker.value = false;
    return;
  }

  // Otherwise, user is adding project generation references
  await addReference({ asset, role });

  // If product name is "Untitled Product" and user selected a Product reference, initialize product name automatically
  if (
    workspace.value?.project?.product_name === "Untitled Product" &&
    (role === "Product" || asset.asset_category === "Product") &&
    asset.asset_name
  ) {
    try {
      await call("frappe.client.set_value", {
        doctype: "Media Project",
        name: projectName.value,
        fieldname: "product_name",
        value: asset.asset_name,
      });
      if (workspace.value?.project) {
        workspace.value.project.product_name = asset.asset_name;
      }
    } catch (_) {}
  }
}

const timelineReady = computed(() => Boolean(clips.value?.length));
const isOutdated = computed(() => Boolean(generationOutputOutdated.value || timelineOutdated.value));
const hasUnexportedEdits = computed(() => isOutdated.value);

const hasInspectorSelection = computed(() => {
  if (studioMode.value === "edit") {
    return Boolean(selectedClip.value);
  }
  return Boolean(
    ((selectedTarget.value === "scene" || selectedTarget.value === "shot") && activeSelectedShot.value) ||
    (selectedTarget.value === "asset" && selectedAsset.value) ||
    selectedTarget.value === "keyframe-start" ||
    selectedTarget.value === "keyframe-end"
  );
});

const activeSelectedShot = computed(() => {
  return storyboardShots.value[selectedShotIndex.value] || storyboardShots.value[0] || null;
});

const selectedShotFrame = computed(() => {
  const shot = activeSelectedShot.value;
  if (!shot) return null;
  return getShotFirstFrame(shot);
});

const selectedClipSourceShot = computed(() => {
  if (!selectedClip.value) return null;
  return (
    storyboardShots.value.find(
      (s) => s.name === selectedClip.value.shot || s.shot_number === selectedClip.value.shot_number
    ) || null
  );
});

const previewDuration = ref(0);

function onPreviewLoadedMetadata({ duration }) {
  if (duration && Number.isFinite(duration) && duration > 0) {
    previewDuration.value = duration;
  }
}

// Player displayed media total duration (Strictly distinct from project target duration setting)
const playerTotalSeconds = computed(() => {
  if (previewDuration.value > 0) {
    return previewDuration.value;
  }
  return 0;
});

const currentTimelinePositionLabel = computed(() => {
  const f = playheadFrame.value || 0;
  const currentFps = fps.value || 24;
  const totalSec = Math.max(0, f / currentFps);
  const m = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const s = String(Math.floor(totalSec % 60)).padStart(2, "0");
  return `${m}:${s}`;
});

// Viewport Media computation (Unified persistent player model)
const studioPreview = computed(() => {
  // 1. Explicit asset preview (e.g. user selected an ingredient in Media Drawer to inspect)
  if (selectedTarget.value === "asset" && selectedAsset.value?.file) {
    const isVid = selectedAsset.value.media_type === "Video";
    return {
      type: "asset",
      url: selectedAsset.value.file,
      isVideo: isVid,
      title: selectedAsset.value.asset_name,
    };
  }

  // 2. Explicit clip source preview request
  if (previewSelection.value === "clip-source" && selectedClip.value?.source_file) {
    return {
      type: "clip",
      url: selectedClip.value.source_file,
      clip: selectedClip.value,
      isVideo: true,
      title: `Source: Clip ${selectedClip.value.clip_order || 1}`,
    };
  }

  // 3. PERSISTENT MASTER/FINAL VIDEO (OpenSlop unified player model)
  // When final/master video exists, IT IS THE PERSISTENT PLAYER
  if (finalVideo.value?.file) {
    return {
      type: "master",
      url: finalVideo.value.file,
      isVideo: true,
      title: "Master Video",
    };
  }

  // 4. BEFORE MASTER VIDEO EXISTS: individual shot video or first frame
  if (activeSelectedShot.value) {
    const vid = getShotVideoFile(activeSelectedShot.value);
    if (vid) {
      return {
        type: "shot",
        url: vid,
        isVideo: true,
        title: `Shot ${activeSelectedShot.value.shot_number}`,
      };
    }
    const frame = getShotFirstFrame(activeSelectedShot.value);
    if (frame?.file) {
      return {
        type: "shot-frame",
        url: frame.file,
        isVideo: false,
        title: `Shot ${activeSelectedShot.value.shot_number}`,
      };
    }
  }

  // 5. If selected clip has a source file before final video exists
  if (selectedClip.value?.source_file) {
    return {
      type: "clip",
      url: selectedClip.value.source_file,
      clip: selectedClip.value,
      isVideo: true,
      title: `Clip ${selectedClip.value.clip_order || 1}`,
    };
  }

  return null;
});

watch(
  () => studioPreview.value?.url,
  () => {
    previewDuration.value = 0;
  }
);

// Helper Functions
function getShotVideoFile(shot) {
  return shot?.selected_output_file || shot?.output_video || null;
}

function getShotFirstFrame(shot) {
  if (!shot) return {};
  if (shot.first_frame_image) return { file: shot.first_frame_image };
  if (shot.reference_image) return { file: shot.reference_image };
  return {};
}

function estimateShotDuration(shot) {
  return Number(shot?.duration_seconds) || 5;
}

function formatShotKeyframeTime(index, framePoint = 0) {
  let elapsed = 0;
  for (let i = 0; i < index; i++) {
    elapsed += estimateShotDuration(storyboardShots.value[i]);
  }
  if (framePoint === 1) {
    elapsed += estimateShotDuration(storyboardShots.value[index]);
  }
  return `${elapsed.toFixed(1)}s`;
}

function getShotTimestampRange(shot) {
  if (!shot) return "00:00–00:05";
  const index = storyboardShots.value.findIndex((s) => s.name === shot.name);
  const start = formatShotKeyframeTime(index >= 0 ? index : 0, 0);
  const end = formatShotKeyframeTime(index >= 0 ? index : 0, 1);
  return `${start}–${end}`;
}

// User Actions
function getShotStartTime(index) {
  const shot = storyboardShots.value[index];
  const timelineClip = timeline.value?.clips?.find(
    (clip) => clip.track_type === "Video" && (clip.shot === shot?.name || clip.shot_number === shot?.shot_number)
  );
  if (timelineClip && fps.value > 0) {
    return Number(timelineClip.timeline_start_frame || 0) / fps.value;
  }
	let elapsed = 0;
  for (let i = 0; i < index && i < storyboardShots.value.length; i++) {
    elapsed += estimateShotDuration(storyboardShots.value[i]);
  }
  return elapsed;
}

function seekPreview(timeInSeconds) {
  const safeTime = Math.max(0, Number(timeInSeconds) || 0);
  const preview = studioPreviewRef.value;
  preview?.seek?.(safeTime);
  const video = preview?.previewVideo?.value || preview?.previewVideo;
  if (video && Number.isFinite(safeTime)) {
    video.currentTime = safeTime;
  }
}

function syncActiveSceneFromFrame(frame) {
  const currentFrame = Math.max(0, Math.round(Number(frame) || 0));
  const videoClips = (timeline.value?.clips || [])
    .filter((clip) => (clip.track_type || "Video") === "Video")
    .sort((a, b) => (a.timeline_start_frame || 0) - (b.timeline_start_frame || 0));
  if (videoClips.length) {
    const clip = videoClips.find(
      (item) => currentFrame >= Number(item.timeline_start_frame || 0) && currentFrame < Number(item.timeline_end_frame || 0)
    );
    if (clip) {
      const index = storyboardShots.value.findIndex(
        (shot) => shot.name === clip.shot || shot.shot_number === clip.shot_number
      );
      if (index >= 0) selectedShotIndex.value = index;
      return;
    }
  }

  const currentFps = fps.value || 24;
  const seekTime = currentFrame / currentFps;
  let elapsed = 0;
  for (let i = 0; i < storyboardShots.value.length; i++) {
    const duration = estimateShotDuration(storyboardShots.value[i]);
    if (seekTime >= elapsed && seekTime < elapsed + duration) {
      selectedShotIndex.value = i;
      return;
    }
    elapsed += duration;
  }
}

function onSelectShot(shot, index) {
  selectedShotIndex.value = index;
  selectedTarget.value = "shot";
  inspectorOpen.value = true;

  const currentFps = fps.value || 24;

  if (finalVideo.value?.file) {
    // Persistent master player: seek master to shot start time
    previewSelection.value = "master";
    const startTime = getShotStartTime(index);
    playheadFrame.value = Math.round(startTime * currentFps);
    seekPreview(startTime);
  } else {
    // Pre-master stage: preview individual shot video starting from 0s
    previewSelection.value = "shot";
    playheadFrame.value = 0;
    studioPreviewRef.value?.seek(0);
  }
}

function onVideoTimeUpdate(payload) {
  const currentTime = payload?.currentTime ?? payload?.target?.currentTime ?? 0;
  const currentFps = fps.value || 24;

  if (finalVideo.value?.file && studioPreview.value?.type === "master") {
    // Persistent master player: currentTime IS global timeline time!
    playheadFrame.value = Math.round(currentTime * currentFps);
    syncActiveSceneFromFrame(playheadFrame.value);
  } else if (studioPreview.value?.type === "shot") {
    // Pre-master: local time (0..dur) within individual shot
    const shotStart = getShotStartTime(selectedShotIndex.value);
    playheadFrame.value = Math.round((shotStart + currentTime) * currentFps);
  } else {
    playheadFrame.value = Math.round(currentTime * currentFps);
  }
}

function onSeekPlayhead(frame) {
  playheadFrame.value = frame;
  const currentFps = fps.value || 24;
  const seekTime = frame / currentFps;

  if (finalVideo.value?.file && studioPreview.value?.type === "master") {
    seekPreview(seekTime);
  }

  syncActiveSceneFromFrame(frame);
}

function jumpToNextShot() {
  if (selectedShotIndex.value < storyboardShots.value.length - 1) {
    const nextIdx = selectedShotIndex.value + 1;
    onSelectShot(storyboardShots.value[nextIdx], nextIdx);
  }
}

function jumpToPrevShot() {
  if (selectedShotIndex.value > 0) {
    const prevIdx = selectedShotIndex.value - 1;
    onSelectShot(storyboardShots.value[prevIdx], prevIdx);
  }
}

function onSelectKeyframe(shot, index, targetRole) {
  selectedShotIndex.value = index;
  selectedTarget.value = targetRole === "start" ? "keyframe-start" : "keyframe-end";
  inspectorOpen.value = true;
}

function onSelectAssetTarget(asset) {
  selectedAsset.value = asset;
  selectedTarget.value = "asset";
  inspectorOpen.value = true;
}

function onSelectClip(clip) {
  selectedClipName.value = clip.name;
  inspectorOpen.value = true;

  if (finalVideo.value?.file) {
    previewSelection.value = "master";
    const clipStartFrame = clip.timeline_start_frame || 0;
    const currentFps = fps.value || 24;
    playheadFrame.value = clipStartFrame;
    seekPreview(clipStartFrame / currentFps);

    if (clip.shot_number) {
      const idx = storyboardShots.value.findIndex(
        (s) => s.shot_number === clip.shot_number || s.name === clip.shot
      );
      if (idx >= 0) selectedShotIndex.value = idx;
    }
  } else {
    previewSelection.value = "clip";
  }
}

function onSetKeyframeFromPicker(asset) {
  if (!activeSelectedShot.value) return;
  setShotKeyframe({
    shot: activeSelectedShot.value,
    frameRole: selectedTarget.value === "keyframe-start" ? "first_frame" : "last_frame",
    asset,
  });
}

async function changeShotDuration(shot, delta) {
  const current = estimateShotDuration(shot);
  const next = Math.max(1, Math.min(20, current + delta));
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.update_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
      duration_seconds: next,
    });
    shot.duration_seconds = next;
  } catch (err) {
    toast({ title: "Error", text: err?.message || "Failed to update duration.", type: "error" });
  }
}

async function toggleContinuityMode() {
  const nextMode = videoSettings.value.generation_mode === "Continuous" ? "Multi-shot" : "Continuous";
  await saveVideoSettings({
    ...videoSettings.value,
    generation_mode: nextMode,
  });
}

async function saveActiveShot() {
  const shot = activeSelectedShot.value;
  if (!shot?.name) return;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.update_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
      generation_prompt: shot.generation_prompt,
    });
  } catch (_) {}
}

async function regenerateCurrentShot() {
  const shot = activeSelectedShot.value;
  if (!shot?.name) return;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.regenerate_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
    });
    await fetchWorkspace();
    toast({ title: "Shot regenerating", text: `Generating new video for Shot ${shot.shot_number}.`, type: "success" });
  } catch (err) {
    toast({ title: "Error", text: err?.message || "Failed to regenerate shot.", type: "error" });
  }
}

function onAskAiRewriteShot(instruction) {
  const shot = activeSelectedShot.value;
  if (!shot?.name) return;
  reviseShotWithAi(shot.name, instruction);
}

function applyAssetToShot(asset, shot) {
  if (!asset?.asset_version || !shot?.name) return;
  setShotKeyframe({
    shot,
    frameRole: "first_frame",
    asset,
  });
}

function onClipTransitionChange(transition) {
  if (!selectedClip.value) return;
  setTransition(selectedClip.value, transition, selectedClip.value.transition_frames || 12);
}

function onClipTransitionFramesChange(frames) {
  if (!selectedClip.value) return;
  setTransition(selectedClip.value, selectedClip.value.transition_to_next || "Cut", frames);
}

function splitClipAtPlayhead() {
  if (!selectedClip.value) return;
  splitClip(selectedClip.value, playheadFrame.value);
}

function onUpdateSourceForClip() {
  if (!selectedClipSourceShot.value) return;
  updateSourceForShot(selectedClipSourceShot.value.name);
}

function onRegenerateSourceForClip() {
  if (!selectedClipSourceShot.value) return;
  regenerateCurrentShot();
}

function onReorderShots(fromIdx, toIdx) {
  // Local reorder
  const arr = [...storyboardShots.value];
  const [moved] = arr.splice(fromIdx, 1);
  arr.splice(toIdx, 0, moved);
  arr.forEach((s, idx) => {
    s.shot_number = idx + 1;
  });
  if (workspace.value?.storyboard) {
    workspace.value.storyboard.shots = arr;
  }
}

// Lifecycle Hooks
onMounted(async () => {
  await fetchWorkspace();
  await fetchVideoStyles();
  await loadTimeline(true);
  if (finalVideo.value?.file && clips.value?.length) {
    studioMode.value = "edit";
  }
  // sync video idea prompt if present in project
  if (workspace.value?.project?.video_idea) {
    videoIdeaPrompt.value = workspace.value.project.video_idea;
  }
});

onUnmounted(() => {
  stopPolling();
});
</script>
