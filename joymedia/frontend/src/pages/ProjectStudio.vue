<template>
  <div class="project-studio-root relative flex w-screen h-screen overflow-hidden bg-surface-base text-ink-primary">
    <!-- Slim Creative Tool Rail (Google Flow / Runway single-chrome design) -->
    <aside class="w-14 shrink-0 flex flex-col items-center justify-between border-r border-outline-border bg-surface-card py-3 select-none z-20">
      <!-- Top Rail Tools -->
      <div class="flex flex-col items-center gap-3">
        <!-- Brand Mark (Navigates to Projects Home) -->
        <button
          type="button"
          class="brand-mark size-9 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center font-bold text-base shadow-sm transition-transform hover:scale-105 cursor-pointer"
          :title="currentLang === 'vi' ? 'Quay lại danh sách dự án' : 'JoyMedia Projects'"
          @click="router.push('/campaigns')"
        >
          ✦
        </button>

        <div class="w-8 h-px bg-outline-border my-0.5" />

        <!-- Media Drawer Toggle -->
        <button
          type="button"
          class="studio-rail-button relative"
          :class="{ active: mediaDrawerOpen }"
          :title="currentLang === 'vi' ? 'Mở tư liệu tham chiếu' : 'Project Media'"
          @click="mediaDrawerOpen = !mediaDrawerOpen"
        >
          <span class="text-base">▧</span>
          <small class="text-[9px] font-bold">Media</small>
          <span
            v-if="projectAssets.length"
            class="absolute -top-1 -right-1 size-4 rounded-full bg-indigo-600 text-white text-[9px] font-mono font-bold flex items-center justify-center shadow-xs"
          >
            {{ projectAssets.length }}
          </span>
        </button>

        <!-- Scenes Mode Button -->
        <button
          type="button"
          class="studio-rail-button"
          :class="{ active: studioMode === 'scene' }"
          :title="currentLang === 'vi' ? 'Chế độ kịch bản phân cảnh' : 'Scene Builder'"
          @click="studioMode = 'scene'"
        >
          <span class="text-base">▤</span>
          <small class="text-[9px] font-bold">Scenes</small>
        </button>

        <!-- Edit Mode Button -->
        <button
          type="button"
          class="studio-rail-button"
          :class="[
            { active: studioMode === 'edit' },
            timelineReady ? 'cursor-pointer' : 'opacity-40 cursor-not-allowed'
          ]"
          :disabled="!timelineReady"
          :title="timelineReady ? (currentLang === 'vi' ? 'Trình dựng Edit' : 'Edit Timeline') : (currentLang === 'vi' ? 'Tạo video để kích hoạt chế độ Edit' : 'Generate video to enable Edit mode')"
          @click="studioMode = 'edit'"
        >
          <span class="text-base">✂</span>
          <small class="text-[9px] font-bold">Edit</small>
        </button>
      </div>

      <!-- Bottom Rail Navigation & Preferences -->
      <div class="flex flex-col items-center gap-2.5">
        <!-- Media Library Link -->
        <button
          type="button"
          class="p-2 rounded-xl text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Thư viện Media chung' : 'Media Library'"
          @click="router.push('/assets')"
        >
          <span class="text-base">🖼️</span>
        </button>

        <!-- Language Switcher -->
        <button
          type="button"
          class="p-1.5 rounded-xl text-xs font-mono font-bold text-ink-muted hover:text-ink-primary hover:bg-surface-hover border border-outline-border/60 transition-colors cursor-pointer select-none"
          :title="currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'"
          @click="toggleLang"
        >
          {{ currentLang.toUpperCase() }}
        </button>

        <!-- User Avatar -->
        <div
          class="size-8 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 text-white flex items-center justify-center text-xs font-bold shadow-xs select-none"
          :title="user || 'Creator'"
        >
          {{ (user || 'C').charAt(0).toUpperCase() }}
        </div>
      </div>
    </aside>

    <!-- Media Drawer (Collapsible) -->
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

    <!-- Center Stage Canvas: Header + Viewport + Timeline -->
    <div class="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-surface-base">
      <!-- 1. Single Studio Header -->
      <StudioHeader
        :project-name="projectName"
        :project-title="projectTitle"
        :project-status="projectStatus"
        :studio-mode="studioMode"
        :timeline-ready="timelineReady"
        :has-unexported-edits="hasUnexportedEdits"
        :is-exporting="isExporting"
        :export-status="exportStatus"
        :current-output-asset-version="currentOutputAssetVersion"
        :inspector-open="inspectorOpen"
        :current-lang="currentLang"
        @go-back="router.push('/campaigns')"
        @save-project-name="updateProjectName"
        @update:studio-mode="studioMode = $event"
        @update:inspector-open="inspectorOpen = $event"
        @open-settings="showSettings = true"
        @export-timeline="exportTimeline"
      />

      <!-- 2. Scrollable Studio Canvas -->
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
            @click="retryFailedScenes"
          >
            {{ currentLang === 'vi' ? 'Thử lại' : 'Retry' }}
          </button>
        </div>

        <!-- Cinema Viewport Hero (StudioPreview) -->
        <div class="flex flex-col items-center justify-center min-h-[380px] w-full">
          <StudioPreview
            :studio-mode="studioMode"
            :studio-preview="studioPreview"
            :selected-target="selectedTarget"
            :selected-asset="selectedAsset"
            :active-selected-shot="activeSelectedShot"
            :selected-clip="selectedClip"
            :selected-shot-frame="selectedShotFrame"
            :preview-selection="previewSelection"
            :timeline-total-seconds="timelineTotalSeconds"
            :current-timeline-position-label="currentTimelinePositionLabel"
            :is-playing="isPlaying"
            :is-production-active="isProductionActive"
            :is-auto-generating="isGenerating"
            :auto-generate-step="currentRun?.status ? `Generating (${currentRun.status})...` : ''"
            :production="currentRun"
            :production-error="productionError"
            :production-status="projectStatus"
            :expected-shot-count="storyboardShots.length || 4"
            :estimated-finish-label="'...'"
            :project-assets="projectAssets"
            :input-asset-categories="[]"
            :upload-category="'Product'"
            :settings-format="videoSettings.delivery_preset"
            :is-playhead-at-keyframe="false"
            :final-video="finalVideo"
            :retrying-failed-scenes="false"
            :uploading-images="uploadingMedia"
            :selected-shot-index="selectedShotIndex"
            :current-lang="currentLang"
            :is-outdated="isOutdated"
            :get-shot-timestamp-range="getShotTimestampRange"
            @toggle-play-pause="isPlaying = !isPlaying"
            @play="isPlaying = true"
            @pause="isPlaying = false"
            @select-full-video="previewSelection = 'full'"
            @select-clip="previewSelection = 'clip'"
            @select-shot-target="onSelectShot"
            @retry-failed-scenes="retryFailedScenes"
            @refresh="fetchWorkspace"
            @open-media-picker="openPicker"
          />
        </div>

        <!-- 3. SCENE MODE: Simple Generation Composer + Scene Filmstrip -->
        <template v-if="studioMode === 'scene'">
          <!-- Generation Composer (Describe video + reference chips + Generate button) -->
          <GenerationComposer
            v-model:prompt="videoIdeaPrompt"
            :project-assets="projectAssets"
            :is-generating="isGenerating || isProductionActive"
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
            :expected-shot-count="storyboardShots.length || 4"
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

        <!-- 4. EDIT MODE: Editorial Tracks (Video 0 + Audio 0) -->
        <template v-else>
          <EditTimeline
            :clips="clips"
            :fps="fps"
            :selected-clip-name="selectedClipName"
            :playhead-frame="playheadFrame"
            :busy="timelineBusy"
            :total-frames="timeline?.total_frames || 0"
            :total-seconds="timeline?.total_seconds || 0"
            :current-lang="currentLang"
            @select-clip="onSelectClip"
            @update:playhead-frame="playheadFrame = $event"
            @trim="trimClip"
            @split="splitClip"
            @duplicate="duplicateClip"
            @delete="deleteClip"
            @reorder="reorderClip"
            @select-transition="setTransition"
          />
        </template>
      </div>
    </div>

    <!-- Right Side: Selection-driven Contextual Inspector -->
    <StudioInspector
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

    <!-- Modal: Explicit Role Reference Picker -->
    <MediaPicker
      v-if="showMediaPicker"
      :candidates="mediaCandidates"
      :loading="candidatesLoading"
      :saving="savingReference"
      :uploading="uploadingMedia"
      :is-keyframe-target="selectedTarget === 'keyframe-start' || selectedTarget === 'keyframe-end'"
      :current-lang="currentLang"
      @close="showMediaPicker = false"
      @select-reference="addReference"
      @set-keyframe="onSetKeyframeFromPicker"
      @upload-files="uploadAndAddFiles"
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
  openPicker,
  addReference,
  updateReferenceRole,
  removeReference,
  setShotKeyframe,
  uploadAndAddFiles,
} = useProjectReferences(projectName, fetchWorkspace);

// 3. Generation composable
const {
  isGenerating,
  isRevising,
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
  fps,
  busy: timelineBusy,
  selectedClip,
  selectedClipName,
  playheadFrame,
  exportStatus,
  isExporting,
  isOutdated,
  loadTimeline,
  trimClip,
  reorderClip,
  splitClip,
  duplicateClip,
  deleteClip,
  setTransition,
  updateSourceForShot,
  exportTimeline,
} = useProjectTimeline(projectName);

// Studio Local State
const mediaDrawerOpen = ref(false);
const isPlaying = ref(false);
const previewSelection = ref("shot"); // "shot" | "full" | "clip"

const timelineReady = computed(() => Boolean(clips.value?.length));
const hasUnexportedEdits = computed(() => isOutdated.value);

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

const timelineTotalSeconds = computed(() => {
  return Number(timeline.value?.total_seconds || videoSettings.value.duration || 15);
});

const currentTimelinePositionLabel = computed(() => {
  const f = playheadFrame.value || 0;
  const currentFps = fps.value || 24;
  const sec = (f / currentFps).toFixed(1);
  return `${sec}s`;
});

// Viewport Media computation
const studioPreview = computed(() => {
  if (studioMode.value === "edit" && selectedClip.value?.source_file) {
    return {
      type: "clip",
      url: selectedClip.value.source_file,
      clip: selectedClip.value,
      isVideo: true,
      title: `Clip ${selectedClip.value.clip_order || 1}`,
    };
  }

  if (previewSelection.value === "full" && finalVideo.value?.file) {
    return {
      type: "master",
      url: finalVideo.value.file,
      isVideo: true,
      title: "Final Output",
    };
  }

  if (selectedTarget.value === "asset" && selectedAsset.value?.file) {
    const isVid = selectedAsset.value.media_type === "Video";
    return {
      type: "asset",
      url: selectedAsset.value.file,
      isVideo: isVid,
      title: selectedAsset.value.asset_name,
    };
  }

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

  if (finalVideo.value?.file) {
    return {
      type: "master",
      url: finalVideo.value.file,
      isVideo: true,
      title: "Master Output",
    };
  }

  return null;
});

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
function onSelectShot(shot, index) {
  selectedShotIndex.value = index;
  selectedTarget.value = "scene";
  previewSelection.value = "shot";
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
  previewSelection.value = "clip";
  inspectorOpen.value = true;
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
  await loadTimeline(false);
  // sync video idea prompt if present in project
  if (workspace.value?.project?.video_idea) {
    videoIdeaPrompt.value = workspace.value.project.video_idea;
  }
});

onUnmounted(() => {
  stopPolling();
});
</script>
