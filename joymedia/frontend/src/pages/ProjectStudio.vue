<template>
  <div class="project-studio-root relative flex flex-col w-screen h-screen overflow-hidden bg-surface-base text-ink-primary">
    <ClientWorkspace v-if="!advancedMode" :project="projectName" :title="projectTitle" :current-lang="currentLang" :workspace="workspace" :loading="workspaceLoading" v-model:prompt="videoIdeaPrompt" :shots="storyboardShots" :frames="clientFrames.rows.value" :video="finalVideo" :review-revision="reviewRevision" :review-version="reviewVersion" :review-focused="reviewFocused || String(route.query.feedback || '')" :review-start-frame="reviewStartFrame" @feedback-saved="reviewRevision++" @review-close="closeVideoReview" :action="clientNextAction" :busy="clientActionBusy || isGenerating || isProductionActive || isFinishing || isExporting || clientFrames.drawingAll.value || Boolean(clientFrames.drawingShot.value)" :error="productionError || postProduction.error"
      @working-edit="edit=>router.push(`/projects/${edit}`)" @back="router.push('/projects')" @history="shot => { historyShot=shot || ''; historyOpen=true; }" @advanced="setEditorMode(true)" @settings="showSettings=true" @continue="continueClientJourney" @approve="(shot, approved)=>clientFrames.approve(shot,approved)" @redraw="shot=>clientFrames.draw([shot])" @restore="restoreClientProject" @refresh="fetchWorkspace" @assemble="assembleClientPreview" @review="(version,frame,feedback)=>{reviewStartFrame=Number.isInteger(frame)?frame:null;reviewFocused=feedback || '';reviewVersion=version;}" />
    <div v-if="advancedMode" class="flex items-center justify-between px-4 py-2 border-b border-outline-border text-xs"><span>{{ currentLang==='vi'?'Trình chỉnh sửa nâng cao':'Advanced editor' }}</span><button class="text-indigo-500 underline" data-test="back-to-simple" @click="setEditorMode(false)">{{ currentLang==='vi'?'Quay lại video':'Back to video' }}</button></div>
    <!-- 1. Single Studio Header (Full width across top: Projects | Title | Media | Export) -->
    <StudioHeader v-if="advancedMode"
      :project-name="projectName"
      :project-title="projectTitle"
      :edit-label="workspace?.family?.edit_label"
      :project-status="projectStatus"
      :timeline-ready="timelineReady"
      :has-unexported-edits="hasUnexportedEdits"
      :is-exporting="isExporting"
      :is-finishing="isFinishing"
      :brand-ready="Boolean(workspace?.storyboard?.length) && workspace.storyboard.every(shot => !shot.brand_review?.required || shot.brand_review.status === 'Approved')"
      :post-production-step="postProduction.step"
      :export-status="exportStatus"
      :current-output-asset-version="currentOutputAssetVersion"
      :media-drawer-open="mediaDrawerOpen"
      :project-assets-count="projectAssets.length"
      :production="currentRun"
      :current-lang="currentLang"
      :user="user"
      @open-history="historyOpen = true"
      @go-back="router.push('/projects')"
      @save-project-name="updateProjectName"
      @toggle-media-drawer="mediaDrawerOpen = !mediaDrawerOpen"
      @toggle-lang="toggleLang"
      @open-settings="showSettings = true"
      @export-timeline="exportAndRefresh"
      @export-release="exportAndRefresh('release')"
      @finish-film="finishFilm"
      @replace-music="replaceMusic"
      @retry-generation="handleGenerationRetry"
      @stop-generation="cancelGeneration"
      @cancel-finishing="cancelFinishing"
      @select-shot="selectShotFromActivity"
    />

    <div v-if="advancedMode && workspace?.family && !workspace.family.is_working_edit" class="px-4 py-2 bg-indigo-500/10 border-b border-outline-border text-xs flex items-center justify-between gap-2">
      <span>{{ currentLang==='vi'?'Bạn đang xem một bản dựng khác:':'Viewing an alternate edit:' }} {{ workspace.family.edit_label }}</span>
      <button type="button" class="text-indigo-400 font-semibold" @click="router.push(`/projects/${workspace.family.current_edit}`)">{{ currentLang==='vi'?'Mở bản đang dùng':'Open working edit' }}</button>
    </div>

    <!-- 2. Studio Workspace Body: Media Drawer + Canvas + Contextual Inspector -->
    <div v-if="advancedMode" class="flex-1 flex min-h-0 w-full overflow-hidden relative">
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
            :is-muted="isMuted"
            :is-production-active="isProductionActive"
            :production="currentRun"
            :production-error="productionError"
            :production-status="projectStatus"
            :project-assets="projectAssets"
            :settings-format="videoSettings.delivery_preset"
            :final-video="finalVideo"
            :selected-shot-index="selectedShotIndex"
            :current-lang="currentLang"
            :caption="previewCaption"
            :is-outdated="isOutdated"
            :get-shot-timestamp-range="getShotTimestampRange"
            @toggle-play-pause="handleTogglePlayback"
            @toggle-mute="handleToggleMute"
            @play="isPlaying = true"
            @pause="isPlaying = false"
            @ended="onPreviewEnded"
            @loadedmetadata="onPreviewLoadedMetadata"
            @timeupdate="onVideoTimeUpdate"
            @step-frame="stepPlayhead"
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
          v-if="finalVideo?.file && finalVideo?.is_current && storyboardShots.length === 0"
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
            :generation-phase="generationPhase"
            :sync-error="syncError"
            :is-improving-prompt="improvingIdea"
            :is-saving-prompt="isSavingIdea"
            :from-sheet="Boolean(workspace?.project?.follows_sheet)"
            :duration-seconds="videoSettings.duration || 15"
            :delivery-preset="videoSettings.delivery_preset || 'Landscape'"
            :current-lang="currentLang"
            :next-action="clientNextAction"
            :action-busy="clientActionBusy"
            @continue="continueClientJourney"
			@import-storyboard="importStoryboardWorkbook"
            @open-media-picker="openPicker"
            @open-settings="showSettings = true"
            @improve-prompt="improveVideoIdea"
            @remove-reference="removeReference"
          />

          <!-- What is still needed before generating; refreshes from Frappe realtime events -->
          <ReadinessChecklist :has-storyboard="Boolean(storyboardShots.length)" :project-name="projectName" @changed="fetchWorkspace" />

          <!-- First frame of each scene, approved before any video is made -->

          <!-- Scene Filmstrip / Storyboard Track -->
          <SceneStrip
            ref="sceneStripRef"
            :frames="clientFrames"
            :project-name="projectName"
            :shots="storyboardShots"
            :selected-shot-index="selectedShotIndex"
            :selected-target="selectedTarget"
            :total-duration-seconds="videoSettings.duration || 15"
            :has-storyboard="Boolean(storyboardShots.length)"
            :from-sheet="Boolean(workspace?.project?.follows_sheet)"
            :storyboard-approved="workspace?.project?.storyboard_approval_status === 'Approved'"
            :portrait="videoSettings.delivery_preset === 'Portrait'"
            :is-generating="isGenerating || isProductionActive"
            :generation-phase="generationPhase"
            :sync-error="syncError"
            :is-revising="isRevising"
            :revision-error="revisionError"
            :expected-shot-count="storyboardShots.length || currentRun?.total_tasks || 0"
            :production="currentRun"
            :current-lang="currentLang"
            :busy-shots="workspace?.project?.busy_shots || []"
            :estimate-shot-duration="estimateShotDuration"
            :format-shot-keyframe-time="formatShotKeyframeTime"
            :get-shot-video-file="getShotVideoFile"
            :get-shot-first-frame="getShotFirstFrame"
            @select-shot="onSelectShot"
            @edit-shot="editStoryboardShot"
            @delete-shot="removeStoryboardShot"
            @select-keyframe="onSelectKeyframe"
            @change-shot-duration="changeShotDuration"
            @revise-storyboard="reviseStoryboard"
            @reorder-shots="onReorderShots"
            @add-scene="openAddScenePopover"
            @regenerate-shot="regenerateCurrentShot"
            @select-take="selectShotTake"
            @update-caption="updateShotCaption"
			@update-continuity="updateShotContinuity"
			@update-references="updateShotReferences"
			@place-cue-audio="startCueAudio"
			@generate-voiceover="generateVoiceover"
			@review-brand="reviewBrand"
            @check-scene="checkScene"
            @review-findings="sceneCheckShot = $event"
			@repair-source-art="repairMode = 'video'; repairShot = $event"
            @repair-opening-art="repairMode = 'image'; repairShot = $event"
            @guide-motion="guidedShot = $event"
            :guided-enabled="workspace?.project?.can_guide_motion || false"
			:brand-busy-shot="brandBusyShot"
			:narration-busy-shot="narrationBusyShot"
			:audio-plan="audioPlan"
			:project-references="projectReferences"
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
            :canvas-total-frames="timeline?.canvas_total_frames || timeline?.total_frames || 0"
            :render-total-frames="timeline?.render_total_frames || timeline?.total_frames || 0"
            :current-lang="currentLang"
            :can-undo="canUndo"
            :can-redo="canRedo"
            :markers="timelineMarkers"
            @select-clip="onSelectClip"
            @update:playhead-frame="onSeekPlayhead"
            @trim="handleTrimClip"
            @split="handleSplitClip"
            @duplicate="duplicateClip"
            @delete="deleteClip"
            @reorder="handleReorderClip"
            @move="handleMoveClip"
            @select-transition="setTransition"
            @open-inspector="openClipInspector"
            @open-audio-picker="openAudioPicker"
            @add-scene="openAddScenePopover"
            @undo="undo"
            @redo="redo"
            @set-audio-clip-enabled="onSetAudioClipEnabled"
          />
          <TimelineComments
            class="mt-3"
            :project-name="projectName"
            :video-clips="videoClips"
            :shots="storyboardShots"
            :fps="fps"
            :playhead-frame="playheadFrame"
            :busy-shots="workspace?.project?.busy_shots || []"
            @seek="onSeekPlayhead"
            @markers="timelineMarkers = $event"
            @applied="onReviewChanged"
          />
        </template>
      </div>
    </div>

    <!-- Contextual Inspector Drawer -->
    <StudioInspector
      v-if="inspectorOpen && hasInspectorSelection && (studioMode !== 'edit' || selectedClip?.track_type === 'Audio')"
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
      :project-name="projectName"
      :busy-shots="workspace?.project?.busy_shots || []"
      :current-lang="currentLang"
      :estimate-shot-duration="estimateShotDuration"
      :format-shot-keyframe-time="formatShotKeyframeTime"
      @change-transition="onClipTransitionChange"
      @change-transition-frames="onClipTransitionFramesChange"
      @split-clip="splitClipAtPlayhead"
      @duplicate-clip="duplicateClip(selectedClip)"
      @delete-clip="deleteClip(selectedClip)"
      @update-audio-clip="onUpdateAudioClip"
      @fit-audio-clip-to-video="onFitAudioClipToVideo"
      @fit-audio-clip-to-full-video="onFitAudioClipToFullVideo"
      @set-source-audio-enabled="onSetSourceAudioEnabled"
      @use-full-audio-source="onUseFullAudioSource"
      @set-audio-clip-enabled="onSetAudioClipEnabled"
      @update-source-for-selected-clip="onUpdateSourceForClip"
      @regenerate-source-for-selected-clip="onRegenerateSourceForClip"
      @apply-asset-to-shot="applyAssetToShot"
      @remove-asset="removeReference"
      @update-asset-role="updateReferenceRole"
      @update-asset-identity="updateReferenceIdentity"
      @update-asset-size="updateReferenceSize"
      @select-keyframe-target="onSelectKeyframe"
      @toggle-generation-mode="toggleContinuityMode"
      @change-shot-duration="changeShotDuration"
      @regenerate-current-shot="regenerateCurrentShot"
      @save-scene-description="saveActiveShot"
      @ask-ai="onAskAiRewriteShot"
      @review-changed="onReviewChanged"
      @open-settings="showSettings = true"
      @open-media-picker="openPicker"
    />

    <div v-if="addScenePopoverOpen" class="absolute right-4 top-14 z-40">
      <AddScenePopover
        :open="addScenePopoverOpen"
        :after-shot="addSceneAfterShot"
        :current-lang="currentLang"
        :busy="isGenerating"
        :error="appendSceneError"
        @close="closeAddScenePopover"
        @submit="handleAddSceneRequest"
      />
    </div>
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
      @asset-updated="onMediaAssetUpdated"
    />

    <!-- Which sheet of a multi-sheet workbook to import -->
    <Dialog v-model="sheetPicker.open" :title="currentLang === 'vi' ? 'Chọn trang để nhập' : 'Choose the sheet to import'" size="md">
      <template #default>
        <FormControl
          v-model="sheetPicker.choice" type="select"
          :options="sheetPicker.demos.map((d) => ({ label: `${d.name}${d.product_name ? ' — ' + d.product_name : ''} (${d.scene_count})`, value: d.name }))"
        />
      </template>
      <template #actions>
        <Button variant="solid" @click="importSheet(sheetPicker.file, sheetPicker.choice)">{{ currentLang === 'vi' ? 'Nhập' : 'Import' }}</Button>
      </template>
    </Dialog>

    <!-- Modal: Secondary Video Settings (Format, duration, style, instructions) -->
    <ProjectSettingsModal
      v-if="showSettings"
      :settings="videoSettings"
      :saving="savingSettings"
      :current-lang="currentLang"
      @close="showSettings = false"
      @save="saveVideoSettings"
    />
    <VideoReviewDialog v-if="reviewVersion && advancedMode" :key="reviewVersion" :project="projectName" :asset-version="reviewVersion" @saved="reviewRevision++" :initial-frame="reviewStartFrame" :focused-name="reviewFocused || String(route.query.feedback || '')" @close="closeVideoReview" />
    <ProjectHistory @review="version=>{historyOpen=false;reviewVersion=version;reviewFocused='';reviewStartFrame=null;}" v-if="historyOpen" :project="projectName" :source-edit="projectName" :current-lang="currentLang" :simple="!advancedMode" :initial-shot="historyShot" @close="historyOpen=false" @changed="fetchWorkspace" @open="name => { historyOpen=false; router.push(`/projects/${name}`); }" />
    <SceneCheckFindings v-if="sceneCheckShot" :project="projectName" :shot="sceneCheckShot" @close="sceneCheckShot = null" />
    <GuidedCandidate v-if="guidedShot" :project="projectName" :shot="guidedShot" :assets="workspace?.assets || []" @close="guidedShot = null" @done="guidedShot = null; fetchWorkspace(); loadTimeline(true)" />
    <SourceArtRepair v-if="repairShot" :project="projectName" :shot="repairShot" :mode="repairMode" :assets="workspace?.assets || []" @close="repairShot = null" @done="repairShot = null; fetchWorkspace(); loadTimeline(true)" />
  </div>
</template>

<script setup>
import VideoReviewDialog from '../components/studio/VideoReviewDialog.vue';
import ClientWorkspace from '../components/studio/ClientWorkspace.vue';
import ProjectHistory from '../components/studio/ProjectHistory.vue';
import GuidedCandidate from '../components/studio/GuidedCandidate.vue';
import SceneCheckFindings from '../components/studio/SceneCheckFindings.vue';
import SourceArtRepair from '../components/studio/SourceArtRepair.vue';
import { cachedClipUrl } from "../composables/useClipCache";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Button, Dialog, FormControl, call, upload as uploadFile } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useSession } from "../stores/session";
import { useI18n } from "../stores/i18n";

// Composables
import { useProjectWorkspace } from "../composables/useProjectWorkspace";
import { useProjectReferences } from "../composables/useProjectReferences";
import { useProjectGeneration } from "../composables/useProjectGeneration";
import { useProjectTimeline } from "../composables/useProjectTimeline";
import { useTimelinePreviewEngine } from "../composables/useTimelinePreviewEngine";

// Studio Components
import StudioHeader from "../components/studio/StudioHeader.vue";
import MediaDrawer from "../components/studio/MediaDrawer.vue";
import GenerationComposer from "../components/studio/GenerationComposer.vue";
import StudioPreview from "../components/studio/StudioPreview.vue";
import SceneStrip from "../components/studio/SceneStrip.vue";
import { useKeyframes } from "../composables/useKeyframes";
import { clientJourney } from "../utils/clientJourney";
import ReadinessChecklist from "../components/studio/ReadinessChecklist.vue";
import EditTimeline from "../components/studio/EditTimeline.vue";
import StudioInspector from "../components/studio/StudioInspector.vue";
import MediaPicker from "../components/studio/MediaPicker.vue";
import ProjectSettingsModal from "../components/studio/ProjectSettingsModal.vue";
import AddScenePopover from "../components/studio/AddScenePopover.vue";
import TimelineComments from "../components/studio/TimelineComments.vue";

const route = useRoute();
const router = useRouter();
const { user, access } = useSession();
const { currentLang, toggleLang } = useI18n();

const projectName = computed(() => route.params.name);
const historyOpen = ref(false);
const historyShot = ref('');
const reviewRevision=ref(0);
const reviewStartFrame=ref(null),reviewFocused=ref('');
const reviewVersion = ref(typeof route.query.review === 'string' ? route.query.review : '');
function closeVideoReview() {
  reviewVersion.value='';
  if (route.query.review) {
    const query={...route.query};delete query.review;delete query.feedback;
    router.replace({path:route.path,query});
  }
}
const advancedMode = computed(() => access.value.can_use_advanced_editor && route.query.editor === 'advanced');
function setEditorMode(advanced) {
  const query={...route.query};
  if (advanced && access.value.can_use_advanced_editor) query.editor='advanced'; else delete query.editor;
  router.replace({path:route.path,query});
}
async function restoreClientProject() {
  if (clientActionBusy.value) return;
  clientActionBusy.value = true;
  try {
    const root = workspace.value?.family?.root;
    if (root && root !== projectName.value && workspace.value?.family?.archived) {
      await call('joymedia.api.projects.restore_project', { project_name: root });
    }
    await call('joymedia.api.projects.restore_project', { project_name: projectName.value });
    await fetchWorkspace();
  } catch(error) {
    notify({title:'Error',text:errorMessage(error,'Could not restore video'),type:'error'});
  } finally {
    clientActionBusy.value = false;
  }
}
async function assembleClientPreview() {
  if (clientActionBusy.value) return;
  clientActionBusy.value=true;
  try { await loadTimeline(true); await exportAndRefresh(); }
  finally {clientActionBusy.value=false;}
}

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
  savingSettings,
  projectTitle,
  projectStatus,
  projectAssets,
  storyboard,
  storyboardShots,
  currentOutputAssetVersion,
  postProduction,
  finalVideo,
  isOutdated: generationOutputOutdated,
  videoSettings,
  fetchWorkspace,
  applyWorkspaceSnapshot,
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
  updateReferenceIdentity,
  updateReferenceSize,
  removeReference,
  archiveMediaAsset,
  setShotKeyframe,
  uploadFilesToLibrary,
  fetchCandidates,
} = useProjectReferences(projectName, fetchWorkspace);

// Names and categories show in the picker, the reference chips and the scene panel.
async function onMediaAssetUpdated() {
  await Promise.all([fetchCandidates(), fetchWorkspace()]);
}

// 3. Generation composable
const {
  isGenerating,
  isRevising,
  revisionError,
  improvingIdea,
  isSavingIdea,
  aiRevisionLoading,
  productionError,
  getFrappeErrorMessage,
  videoIdeaPrompt,
  currentRun,
  isProductionActive,
  generationPhase,
  syncError,
  resumeProduction,
  generateVideo,
  appendScenes,
  retryFailedScenes,
  handleGenerationRetry,
  cancelGeneration,
  reviseStoryboard,
  reviseShotWithAi,
  improveVideoIdea,
  stopPolling,
} = useProjectGeneration(projectName, refreshStudioGenerationState);

const clientFrames = useKeyframes(projectName.value);
const clientActionBusy = ref(false);
const sceneCheckShot = ref(null);
const sceneStripRef = ref(null);
const clientNextAction = computed(() => clientJourney({
  hasStory: Boolean(videoIdeaPrompt.value?.trim()),
  shots: storyboardShots.value,
  approved: workspace.value?.project?.storyboard_approval_status === "Approved",
  frames: clientFrames.rows.value.length ? clientFrames.rows.value : null,
  framesError: Boolean(clientFrames.error.value),
  busy: isGenerating.value || isProductionActive.value || clientFrames.drawingAll.value || Boolean(workspace.value?.project?.busy_shots?.length),
  finishing: isFinishing.value,
  hasVideo: (shot) => Boolean(getShotVideoFile(shot)) && !shot.is_outdated,
}));

async function prepareMissingPreviews() {
  const names = clientFrames.needed.value.filter(row => !row.url || row.stale).map(row => row.shot);
  if (names.length) await clientFrames.draw(names);
}

async function continueClientJourney() {
  if (clientActionBusy.value) return;
  clientActionBusy.value = true;
  try {
    const action = clientNextAction.value;
    if (action === "approve") {
      if (!(await approveStoryboard())) return;
      await clientFrames.reload();
      if (clientFrames.needed.value.some(row => !row.url || row.stale)) await prepareMissingPreviews();
    } else if (action === "previews") {
      await prepareMissingPreviews();
    } else if (action === "retry") {
      await clientFrames.reload();
    } else if (action === "review") {
      sceneStripRef.value?.$el?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (action === "watch") {
      studioMode.value = "edit";
    } else if (["brief", "plan", "render"].includes(action)) {
      await generateVideo();
    }
  } finally {
    clientActionBusy.value = false;
  }
}

const appendSceneError = ref("");

async function approveStoryboard() {
	const warnings = workspace.value?.project?.storyboard_timing_warnings || [];
	const acknowledge = !warnings.length || window.confirm(
		currentLang.value === "vi"
			? `Kịch bản có ${warnings.length} khoảng trống/chồng chéo thời lượng. Xác nhận duyệt để giữ các cảnh nguồn không thay đổi?`
			: `This storyboard has ${warnings.length} timing gap/overlap warning(s). Approve while preserving the authored scenes?`
	);
	if (!acknowledge) return false;
	try {
		await call("joymedia.api.storyboard.approve_project_storyboard", {
			project_name: projectName.value,
			acknowledge_timing_warnings: Boolean(warnings.length),
		});
		await fetchWorkspace();
		notify({
			title: currentLang.value === "vi" ? "Đã duyệt kịch bản" : "Storyboard approved",
			text: currentLang.value === "vi" ? "Đang chuẩn bị ảnh xem trước. Kiểm tra sản phẩm, logo và nhân vật trước khi tạo video." : "Preparing previews. Review the product, logo and character before creating the video.",
			type: "success",
		});
        return true;
	} catch (err) {
		notify({ title: "Storyboard", text: errorMessage(err, "Unable to approve storyboard."), type: "error" });
        return false;
	}
}

// An uploaded sheet is read first; a workbook with several sheets asks which one to import.
const sheetPicker = ref({ open: false, file: null, demos: [], choice: "" });

async function importStoryboardWorkbook(file) {
	try {
		const uploaded = await uploadFile(file, { private: true });
		if (!uploaded?.name) throw new Error("Storyboard upload failed.");
		const { demos } = await call("joymedia.services.intake.project.preview_workbook", { workbook_file: uploaded.name });
		const usable = demos.filter((demo) => demo.can_create);
		if (!usable.length) {
			const missing = demos[0]?.missing_required?.join(", ");
			throw new Error(currentLang.value === "vi" ? `Bảng còn thiếu các mục bắt buộc: ${missing}.` : `The sheet is missing must-have fields: ${missing}.`);
		}
		if (usable.length === 1) return await importSheet(uploaded.name, usable[0].name);
		sheetPicker.value = { open: true, file: uploaded.name, demos: usable, choice: usable[0].name };
	} catch (err) {
		notify({ title: "Storyboard", text: errorMessage(err, "Unable to import storyboard."), type: "error" });
	}
}

async function importSheet(workbookFile, demoName) {
	try {
		const result = await call("joymedia.api.storyboard.import_storyboard_workbook", {
			project_name: projectName.value,
			workbook_file: workbookFile,
			demo_name: demoName,
		});
		sheetPicker.value.open = false;
		await fetchWorkspace();
		notify({
			title: currentLang.value === "vi" ? "Đã nhập kịch bản" : "Storyboard imported",
			text: `${result.shot_count} scene(s) imported. Review and approve before generation.`,
			type: "success",
		});
	} catch (err) {
		notify({ title: "Storyboard", text: errorMessage(err, "Unable to import storyboard."), type: "error" });
	}
}

// Workspace polling is the source of truth for terminal run state.  A local
// optimistic flag can survive a browser refresh or a worker finishing between
// polls, which previously left the storyboard showing “Generating” after all
// tasks had failed.
watch(
  () => workspace.value?.production?.status,
  (status) => {
    if (!status) return;
    if (!['Queued', 'Running'].includes(status) && isGenerating.value) {
      resumeProduction(workspace.value?.production, workspace.value?.project?.planning_status);
    }
  },
);

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
  fitAudioClipToVideo,
  fitAudioClipToFullVideo,
  useFullAudioSource,
  setAudioClipEnabled,
  setSourceAudioEnabled,
  canUndo,
  canRedo,
  undo,
  redo,
  moveClip,
  addAudioClip,
  exportTimeline,
} = useProjectTimeline(projectName);

async function downloadFile(url) {
  if (!url) throw new Error("The exported video has no download URL.");

  // Asset files may be private Frappe files. A plain anchor lets the browser
  // navigate to the file instead of downloading it (and fails in Safari when
  // the response does not expose Content-Disposition). Fetch with the active
  // session, then download the authenticated blob.
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`The exported video could not be downloaded (${response.status}).`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = "edited-video.mp4";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

const isFinishing = computed(() => ["Queued", "Running"].includes(postProduction.value.status));
let finishPollTimer = null;

async function finishFilm() {
  const withMusic = (videoSettings.value?.soundtrack_mode || "Sound effects only") === "Full soundtrack";
  const confirmed = window.confirm(
    currentLang.value === "vi"
      ? `Dựng lại phim${withMusic ? " với nhạc nền" : " từ các cảnh đã duyệt"}? Các chỉnh sửa thủ công trên timeline sẽ bị thay thế.`
      : `Rebuild the film${withMusic ? " with the soundtrack" : " from the approved scenes"}? Manual timeline edits will be replaced.`
  );
  if (!confirmed) return;
  try {
    await call("joymedia.services.editing.post_production.queue_post_production", { project_name: projectName.value });
    await fetchWorkspace();
  } catch (err) {
    notify({ title: currentLang.value === "vi" ? "Không thể hoàn thiện phim" : "Could not finish the film", text: errorMessage(err, ""), type: "error" });
  }
}

async function replaceMusic() {
  try {
    await call("joymedia.services.editing.post_production.queue_music_bed", { project_name: projectName.value });
    await fetchWorkspace();
  } catch (err) {
    notify({ title: currentLang.value === "vi" ? "Không thể tạo nhạc nền" : "Could not replace music", text: errorMessage(err, ""), type: "error" });
  }
}

async function cancelFinishing() {
  try {
    await call("joymedia.services.editing.post_production.cancel_post_production", { project_name: projectName.value });
    if (finishPollTimer) clearTimeout(finishPollTimer);
    finishPollTimer = null;
    await fetchWorkspace();
    notify({ title: currentLang.value === "vi" ? "Đã dừng hoàn thiện phim" : "Finishing stopped", type: "success" });
  } catch (err) {
    notify({ title: currentLang.value === "vi" ? "Không thể dừng hoàn thiện phim" : "Could not stop finishing", text: errorMessage(err, ""), type: "error" });
  }
}

async function pollFinishing() {
  finishPollTimer = null;
  const previous = postProduction.value.status;
  try {
    // Reports a finishing job that died (worker restart) as Failed instead of Running forever.
    await call("joymedia.services.editing.post_production.get_post_production_status", { project_name: projectName.value });
  } catch {
    // the next poll retries; the workspace fetch below shows the stored state
  }
  await fetchWorkspace();
  const { status, error } = postProduction.value;
  if (["Queued", "Running"].includes(status)) {
    finishPollTimer = setTimeout(pollFinishing, 10000);
    return;
  }
  if (!["Queued", "Running"].includes(previous)) return;
  await loadTimeline(true);
  if (status === "Completed") {
    notify({
      title: currentLang.value === "vi" ? "Đã hoàn thiện phim" : "Film finished",
      text: currentLang.value === "vi"
        ? "Phim đã được dựng lại. Bấm Xuất & tải xuống."
        : "The film is rebuilt. Click Export & download.",
      type: "success",
    });
  } else if (status === "Failed") {
    notify({ title: currentLang.value === "vi" ? "Hoàn thiện phim thất bại" : "Finishing failed", text: error, type: "error" });
  }
}

watch(isFinishing, (finishing) => {
  if (finishing && !finishPollTimer) finishPollTimer = setTimeout(pollFinishing, 10000);
}, { immediate: true });

onUnmounted(() => {
  if (finishPollTimer) clearTimeout(finishPollTimer);
});

async function exportAndRefresh(purpose = 'review') {
  try {
    // Download is deliberately a separate direct click once an export exists.
    // Safari blocks downloads initiated after a long asynchronous export.
    if (purpose !== 'release' && currentOutputAssetVersion.value && !hasUnexportedEdits.value && finalVideo.value?.file) {
      await downloadFile(finalVideo.value.file);
      return;
    }
    const result = await exportTimeline(purpose);
    if (!result) return;
    // The export replaces the project's final video, which only the workspace reports.
    await fetchWorkspace();
    notify({
      title: currentLang.value === "vi" ? "Đã xuất video" : "Video exported",
      text: currentLang.value === "vi" ? "Bấm Tải video để lưu toàn bộ video." : "Click Download video to save the complete video.",
      type: "success",
    });
  } catch (err) {
    notify({ title: "Timeline export failed", text: errorMessage(err, "Export failed."), type: "error" });
  }
}

async function refreshStudioGenerationState(snapshot = null) {
  if (snapshot) {
    applyWorkspaceSnapshot(snapshot);
  } else {
    await fetchWorkspace();
  }
  const totalTasks = Number(currentRun.value?.total_tasks || 0);
  const completedTasks = Number(currentRun.value?.completed_tasks || 0);
  const hasGeneratedShots = storyboardShots.value.some((shot) => Boolean(getShotVideoFile(shot)));
  if (studioMode.value === "edit" || hasGeneratedShots || (totalTasks > 0 && completedTasks === totalTasks)) {
    await loadTimeline(true);
  }
}

// Studio Local State
const studioPreviewRef = ref(null);
const mediaDrawerOpen = ref(false);
const isPlaying = ref(false);
const isMuted = ref(false);
const previewSelection = ref("master"); // "master" | "shot" | "clip-source"
const mediaPickerFilter = ref("All");
const addScenePopoverOpen = ref(false);
const addSceneAfterShot = ref(null);

const {
  syncAtFrame: syncTimelineAudio,
  playAtFrame: playTimelineAudio,
  pauseAll: pauseTimelineAudio,
  syncTimelineVideo,
} = useTimelinePreviewEngine({
  videoClips,
  audioClips,
  fps,
  isPlaying,
  isMuted,
  studioMode,
  playheadFrame,
  timelineTotalFrames: computed(() => Number(timeline.value?.canvas_total_frames || timeline.value?.total_frames || 0)),
  renderTotalFrames: computed(() => Number(timeline.value?.render_total_frames || timeline.value?.total_frames || 0)),
  onTimelineFrame: (frame) => {
    playheadFrame.value = frame;
    syncActiveSceneFromFrame(frame);
  },
  onTimelineEnd: () => {
    isPlaying.value = false;
  },
  getVideo: () => {
    const preview = studioPreviewRef.value;
    return preview?.previewVideo?.value || preview?.previewVideo || null;
  },
});

function handleTogglePlayback() {
  const willPlay = !isPlaying.value;

  if (!willPlay) {
    isPlaying.value = false;
    pauseTimelineAudio();
    return;
  }

  if (studioMode.value === "edit") {
    playTimelineAudio(playheadFrame.value);
  }

  isPlaying.value = true;
}

function handleToggleMute() {
  isMuted.value = !isMuted.value;
  if (isMuted.value) pauseTimelineAudio();
}

async function onPreviewEnded() {
  if (studioMode.value !== "edit" || !isPlaying.value) return;

  const clip = activeTimelineVideoClip.value;
  const totalFrames = Number(
    timeline.value?.render_total_frames || timeline.value?.total_frames || 0,
  );
  const nextFrame = Number(clip?.timeline_end_frame ?? playheadFrame.value + 1);

  if (!clip || nextFrame >= totalFrames) {
    playheadFrame.value = totalFrames || playheadFrame.value;
    isPlaying.value = false;
    return;
  }

  // The video element represents one source clip, while the editor represents
  // one continuous timeline. Advance the global clock explicitly so Vue swaps
  // to the next clip and keeps the same play command alive.
  playheadFrame.value = nextFrame;
  syncActiveSceneFromFrame(nextFrame);
  syncTimelineAudio(nextFrame);
  await nextTick();
  if (isPlaying.value) {
    const video = studioPreviewRef.value?.previewVideo?.value || studioPreviewRef.value?.previewVideo;
    video?.play?.().catch(() => {});
  }
}

// Automatically transition to Edit mode only when an active generation run finishes
watch(
  () => isProductionActive.value,
  async (active, prev) => {
    if (!prev || active) return;
    await fetchWorkspace();
    await loadTimeline(true);
    if (hasCurrentMaster.value) {
      previewSelection.value = "master";
      selectedTarget.value = "scene";
      playheadFrame.value = 0;
      previewDuration.value = 0;
      isPlaying.value = false;
      await nextTick();
      seekPreview(0);
    }
  }
);

const pendingAudioRole = ref(null);

// Storyboard voice-over / sound cues and whether audio is scheduled for each.
const audioPlan = ref([]);
const pendingCue = ref(null);
const narrationBusyShot = ref('');
const brandBusyShot = ref('');
const repairShot = ref(null);
const repairMode = ref('video');
const guidedShot = ref(null);

async function checkScene(shot) {
  try {
    await call('joymedia.services.review.consistency.request_scene_check', {
      project_name: projectName.value, shot_name: shot.name, expected_take: shot.selected_output_asset_version,
    });
    await fetchWorkspace();
    notify({ title: currentLang.value === 'vi' ? 'Đang kiểm tra cảnh' : 'Scene check queued', text: currentLang.value === 'vi' ? 'Kết quả kiểm tra mẫu không thay thế việc duyệt thương hiệu.' : 'Sampled checks do not replace brand review.', type: 'success' });
  } catch (err) {
    notify({ title: 'Scene check', text: errorMessage(err, ''), type: 'error' });
  }
}

async function reviewBrand(shot, approved) {
  brandBusyShot.value = shot.name;
  try {
    await call('joymedia.services.review.brand.approve_scene_brand', {
      project_name: projectName.value, shot_name: shot.name,
      expected_take: shot.selected_output_asset_version, approved,
    });
    await fetchWorkspace();
  } catch (err) {
    notify({ title: 'Brand review could not be saved', text: errorMessage(err, ''), type: 'error' });
  } finally {
    brandBusyShot.value = '';
  }
}

async function generateVoiceover(shot) {
  narrationBusyShot.value = shot.name;
  try {
    await call('joymedia.services.audio.speech.generate_voiceover', { project_name: projectName.value, shot_name: shot.name });
    await loadTimeline(true);
    await fetchAudioPlan();
    notify({ title: currentLang.value === 'vi' ? 'Đã thêm lời đọc vào cảnh' : 'Narration added to scene', type: 'success' });
  } catch (err) {
    notify({ title: currentLang.value === 'vi' ? 'Không tạo được lời đọc' : 'Could not generate narration', text: errorMessage(err, ''), type: 'error' });
  } finally {
    narrationBusyShot.value = '';
  }
}

async function fetchAudioPlan() {
  try {
    audioPlan.value = await call("joymedia.services.audio.plan.get_audio_plan", { project_name: projectName.value });
  } catch (err) {
    audioPlan.value = [];
  }
}

watch(() => workspace.value, () => { if (advancedMode.value) fetchAudioPlan(); });

function startCueAudio(shot, role) {
  pendingCue.value = { shot: shot.name, role };
  mediaPickerFilter.value = "Audio";
  openPicker();
}

function openAudioPicker(role = "BGM") {
  pendingAudioRole.value = role;
  mediaPickerFilter.value = "Audio";
  openPicker();
}

async function onUpdateAudioClip(clip, settings) {
  await updateAudioClip(clip, settings);
}

async function onFitAudioClipToVideo(clip) {
  await fitAudioClipToVideo(clip);
}

async function onFitAudioClipToFullVideo(clip) {
  await fitAudioClipToFullVideo(clip);
}

async function onSetSourceAudioEnabled(clip, enabled) {
  const videoClip = videoClips.value.find((item) => item.name === clip.linked_video_clip);
  if (videoClip) await setSourceAudioEnabled(videoClip, enabled);
}

async function onUseFullAudioSource(clip) {
  await useFullAudioSource(clip);
}

async function onSetAudioClipEnabled(clip, enabled) {
  await setAudioClipEnabled(clip, enabled);
}

async function handleSelectReference({ asset, role }) {
  if (pendingCue.value) {
    const cue = pendingCue.value;
    pendingCue.value = null;
    try {
      await call("joymedia.services.audio.plan.place_cue_audio", {
        project_name: projectName.value,
        shot_name: cue.shot,
        role: cue.role,
        asset_version_name: asset.asset_version || asset.name,
      });
      await fetchAudioPlan();
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to place audio for this cue."), type: "error" });
    }
    showMediaPicker.value = false;
    return;
  }
  // If user opened picker specifically to add an audio clip to a timeline track:
  if (pendingAudioRole.value) {
    const chosenRole = pendingAudioRole.value;
    pendingAudioRole.value = null;
    const assetVersion = asset.asset_version || asset.name;
    if (assetVersion) {
      const startFrame = chosenRole === "BGM" ? 0 : playheadFrame.value || 0;
      await addAudioClip(assetVersion, startFrame, chosenRole);
      notify({
        title: "Audio added",
        text: currentLang.value === "vi" ? `Đã thêm ${asset.asset_name || "âm thanh"} vào rãnh ${chosenRole}.` : `Added ${asset.asset_name || "audio"} to the ${chosenRole} track.`,
        type: "success",
      });
    }
    showMediaPicker.value = false;
    return;
  }

  // Otherwise, user is adding project generation references
  await addReference({ asset, role });

  // Help complete a blank brief when the user chooses a product reference.
  if (
    !workspace.value?.project?.product_name &&
    (role === "Product" || asset.asset_category === "Product") &&
    asset.asset_name
  ) {
    try {
      await call("joymedia.api.projects.update_project_brief", {
        project_name: projectName.value,
        product_name: asset.asset_name,
      });
      if (workspace.value?.project) {
        workspace.value.project.product_name = asset.asset_name;
      }
    } catch (err) {
      notify({ title: "Product name", text: errorMessage(err, "Could not save the product name."), type: "error" });
    }
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

const activeTimelineVideoClip = computed(() => {
  if (studioMode.value !== "edit") return null;
  const frame = Number(playheadFrame.value || 0);
  return videoClips.value.find(
    (clip) => frame >= Number(clip.timeline_start_frame || 0) && frame < Number(clip.timeline_end_frame || 0),
  ) || videoClips.value.at(-1) || null;
});

// Use the same per-scene caption source as the export cue builder.
const previewCaption = computed(() => {
  if (!Number(videoSettings.value?.show_captions ?? 1)) return "";
  const shotName = studioMode.value === "edit" ? activeTimelineVideoClip.value?.shot : activeSelectedShot.value?.name;
  return storyboardShots.value.find((shot) => shot.name === shotName)?.caption || "";
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
const mediaCurrentSeconds = ref(0);

const hasCurrentMaster = computed(() => Boolean(finalVideo.value?.file && finalVideo.value?.is_current !== false));

function onPreviewLoadedMetadata({ duration }) {
  if (duration && Number.isFinite(duration) && duration > 0) {
    previewDuration.value = duration;
  }
}

// Player displayed media total duration (Strictly distinct from project target duration setting)
const playerTotalSeconds = computed(() => {
  if (studioMode.value === "edit") {
    return Number(timeline.value?.render_total_seconds || timeline.value?.total_seconds || 0);
  }
  if (studioPreview.value?.type === "master") {
    return Number(timeline.value?.render_total_seconds || timeline.value?.total_seconds || 0);
  }
  if (previewDuration.value > 0) {
    return previewDuration.value;
  }
  return 0;
});

const currentTimelinePositionLabel = computed(() => {
  const currentFps = fps.value || 24;
  const totalSec = studioMode.value === "edit"
    ? Math.max(0, (playheadFrame.value || 0) / currentFps)
    : studioPreview.value?.type === "master"
    ? Math.max(0, (playheadFrame.value || 0) / currentFps)
    : Math.max(0, mediaCurrentSeconds.value || 0);
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

  // Edit mode previews the active Timeline Clip directly. The editor does not
  // require a project-level master export to play generated shots.
  if (studioMode.value === "edit" && activeTimelineVideoClip.value?.source_file) {
    return {
      type: "timeline-clip",
      url: cachedClipUrl(activeTimelineVideoClip.value.source_file),
      clip: activeTimelineVideoClip.value,
      isVideo: true,
      title: `Timeline: Shot ${activeTimelineVideoClip.value.shot_number || activeTimelineVideoClip.value.clip_order || ""}`,
    };
  }

  // 3. PERSISTENT MASTER/FINAL VIDEO (OpenSlop unified player model)
  // When final/master video exists, IT IS THE PERSISTENT PLAYER
  if (hasCurrentMaster.value) {
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
  () => [studioPreview.value?.type, studioPreview.value?.url],
  async ([type], [previousType] = []) => {
    previewDuration.value = 0;
    mediaCurrentSeconds.value = 0;
    if (type !== "timeline-clip" || previousType !== "timeline-clip") isPlaying.value = false;
    if (type === "timeline-clip") {
      await nextTick();
      syncTimelineVideo(playheadFrame.value);
    }
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
  const timelineClip = timeline.value?.clips?.find(
    (clip) => clip.track_type === "Video" && (clip.shot === shot?.name || clip.shot_number === shot?.shot_number),
  );
  if (timelineClip && fps.value > 0) {
    return Number(timelineClip.duration_frames || 0) / fps.value;
  }
  if (shot?.planned_frame_count && fps.value) {
    return Number(shot.planned_frame_count) / Number(fps.value);
  }
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
      if (studioMode.value === "edit") selectedClipName.value = clip.name;
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
  inspectorOpen.value = false;

  const currentFps = fps.value || 24;

  if (hasCurrentMaster.value) {
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

function selectShotFromActivity(shotNumber) {
  const index = storyboardShots.value.findIndex((shot) => Number(shot.shot_number) === Number(shotNumber));
  if (index < 0) return;
  onSelectShot(storyboardShots.value[index], index);
}

function openAddScenePopover() {
  addSceneAfterShot.value = storyboardShots.value.at(-1) || null;
  appendSceneError.value = "";
  addScenePopoverOpen.value = true;
}

function closeAddScenePopover() {
  addScenePopoverOpen.value = false;
  appendSceneError.value = "";
}

async function handleAddSceneRequest(request) {
  appendSceneError.value = "";
  try {
    await appendScenes(request);
    addScenePopoverOpen.value = false;
    notify({
      title: "Scenes queued",
      text: request.instruction
        ? "Generating your continuation."
        : "AI Director planned the continuation and started generation.",
      type: "success",
    });
  } catch (err) {
    appendSceneError.value = getFrappeErrorMessage(err, "Unable to add scenes.");
  }
}

async function removeStoryboardShot(shot) {
  const request = {
    project_name: projectName.value,
    shot_name: shot.name,
    confirm_continuation: false,
  };
  try {
    let result = await call(
      "joymedia.api.storyboard.remove_project_scene",
      request,
    );
    if (result?.requires_confirmation) {
      const confirmed = window.confirm(
        `${result.message}\n\n${currentLang.value === 'vi' ? 'Bạn vẫn muốn xóa cảnh này?' : 'Remove this scene anyway?'}`
      );
      if (!confirmed) return;
      result = await call(
        "joymedia.api.storyboard.remove_project_scene",
        { ...request, confirm_continuation: true },
      );
    }
    if (!result?.removed) return;
    inspectorOpen.value = false;
    selectedShotIndex.value = 0;
    await fetchWorkspace();
    await loadTimeline(true);
    notify({
      title: currentLang.value === 'vi' ? 'Đã xóa cảnh' : 'Scene removed',
      text: currentLang.value === 'vi' ? 'Cảnh đã được gỡ khỏi storyboard và timeline.' : 'The scene was removed from the storyboard and timeline.',
      type: "success",
    });
  } catch (err) {
    notify({ title: "Unable to remove scene", text: errorMessage(err, "Unable to remove scene."), type: "error" });
  }
}

function editStoryboardShot(shot, index) {
  selectedShotIndex.value = index;
  selectedTarget.value = "shot";
  inspectorOpen.value = true;
}

function onVideoTimeUpdate(payload) {
	if (studioMode.value === "edit") return;
  const currentTime = payload?.currentTime ?? payload?.target?.currentTime ?? 0;
  const currentFps = fps.value || 24;

  mediaCurrentSeconds.value = currentTime;
  if (hasCurrentMaster.value && studioPreview.value?.type === "master") {
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
  if (studioMode.value === "edit") syncTimelineAudio(playheadFrame.value);
}

function onSeekPlayhead(frame) {
	const totalFrames = Number(timeline.value?.canvas_total_frames || timeline.value?.total_frames || 0);
	playheadFrame.value = Math.max(0, Math.min(totalFrames || frame, Math.round(frame)));
	const currentFps = fps.value || 24;
	const seekTime = playheadFrame.value / currentFps;

	if (hasCurrentMaster.value && studioPreview.value?.type === "master") {
    seekPreview(seekTime);
  }

	syncActiveSceneFromFrame(playheadFrame.value);
  if (studioMode.value === "edit") syncTimelineAudio(playheadFrame.value);
}

function stepPlayhead(delta) {
	onSeekPlayhead(playheadFrame.value + Number(delta || 0));
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

function onSelectClip(clip, sourceFrame = null) {
  selectedClipName.value = clip.name;
  selectedTarget.value = "clip";

	if (hasCurrentMaster.value) {
		previewSelection.value = "master";

    if (clip.shot_number) {
      const idx = storyboardShots.value.findIndex(
        (s) => s.shot_number === clip.shot_number || s.name === clip.shot
      );
      if (idx >= 0) selectedShotIndex.value = idx;
    }
	} else {
		previewSelection.value = "clip-source";
	}
}

function openClipInspector(clip) {
  if (!clip) return;
  selectedClipName.value = clip.name;
  selectedTarget.value = "clip";
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
    const result = await call("joymedia.api.storyboard.update_project_shot_timing", {
      project_name: projectName.value,
      shot_name: shot.name,
      duration_seconds: next,
    });
    const shots = result?.shots || [];
    if (shots.length) {
      shots.forEach((updated) => {
        const target = storyboardShots.value.find((item) => item.name === updated.name);
        if (target) Object.assign(target, updated);
      });
    } else {
      shot.duration_seconds = next;
    }
  } catch (err) {
    notify({ title: "Error", text: errorMessage(err, "Failed to update duration."), type: "error" });
  }
}

async function toggleContinuityMode() {
  const nextMode = videoSettings.value.generation_mode === "Continuous" ? "Multi-shot" : "Continuous";
  await saveVideoSettings({
    ...videoSettings.value,
    generation_mode: nextMode,
  });
}

// Visual project references that can be assigned to a scene.
const projectReferences = computed(() =>
	(workspace.value?.assets || []).filter((asset) => asset.media_type === "Image" && asset.reference_key)
);

async function updateShotReferences(shot, referenceKeys) {
	if (!shot?.name) return;
	try {
		await call("joymedia.api.storyboard.set_project_shot_references", {
			project_name: projectName.value,
			shot_name: shot.name,
			reference_keys: JSON.stringify(referenceKeys),
		});
		await fetchWorkspace();
	} catch (err) {
		notify({ title: "Error", text: errorMessage(err, "Failed to update scene references."), type: "error" });
	}
}

async function updateShotContinuity(shot, continuityMode) {
	if (!shot?.name) return;
	try {
		const result = await call("joymedia.api.storyboard.update_project_shot", {
			project_name: projectName.value,
			shot_name: shot.name,
			values: { continuity_mode: continuityMode },
		});
		Object.assign(shot, result);
		await fetchWorkspace();
	} catch (err) {
		notify({ title: "Error", text: errorMessage(err, "Failed to update scene continuity."), type: "error" });
	}
}

async function saveActiveShot(shotName, generationPrompt, done = () => {}) {
  const shot = storyboardShots.value.find((item) => item.name === shotName) || activeSelectedShot.value;
  if (!shot?.name || !String(generationPrompt || '').trim()) { done(); return; }
  try {
    const prompt = String(generationPrompt).trim();
    const result = await call("joymedia.api.storyboard.update_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
      // This inspector exposes one scene description used by both Flux and
      // video generation. A human edit also updates the authored storyboard action.
      values: { storyboard_action: prompt, generation_prompt: prompt, image_prompt: prompt },
    });
    Object.assign(shot, result, { authored_action: prompt });
    notify({ title: currentLang.value === 'vi' ? 'Đã lưu mô tả cảnh' : 'Scene description saved', text: currentLang.value === 'vi' ? 'Tạo lại cảnh để dùng mô tả mới.' : 'Regenerate the scene to use the new description.', type: 'success' });
  } catch (err) {
    notify({ title: "Error", text: errorMessage(err, "Failed to save scene."), type: "error" });
  } finally {
    done();
  }
}

async function regenerateCurrentShot(target = null) {
  const shot = target?.name ? target : activeSelectedShot.value;
  if (!shot?.name) return;
  const vi = currentLang.value === "vi";
  try {
    await call("joymedia.services.generation.takes.regenerate_scene", {
      project_name: projectName.value,
      shot_name: shot.name,
    });
    await fetchWorkspace();
    resumeProduction(workspace.value?.production, workspace.value?.project?.planning_status);
    notify({
      title: vi ? `Đang tạo lại cảnh ${shot.shot_number}` : `Regenerating scene ${shot.shot_number}`,
      text: vi
        ? "Bản hiện tại vẫn được giữ. Bản mới sẽ thay thế khi dựng xong, chuyển cảnh và nhạc được làm lại tự động."
        : "The current take is kept. The new take replaces it when ready; transitions and music are redone automatically.",
      type: "success",
    });
  } catch (err) {
    notify({
      title: vi ? "Không thể tạo lại cảnh" : "Could not regenerate the scene",
      text: errorMessage(err, ""),
      type: "error",
    });
  }
}

async function updateShotCaption(shot, caption) {
  try {
    const result = await call("joymedia.api.storyboard.update_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
      values: { caption },
    });
    shot.caption = result.caption;
  } catch (err) {
    notify({
      title: currentLang.value === "vi" ? "Không thể lưu chữ" : "Could not save the caption",
      text: errorMessage(err, ""),
      type: "error",
    });
  }
}

async function selectShotTake(shot, takeIndex) {
  const vi = currentLang.value === "vi";
  try {
    await call("joymedia.services.generation.takes.select_scene_take", {
      project_name: projectName.value,
      shot_name: shot.name,
      take_index: takeIndex,
    });
    await fetchWorkspace();
    notify({
      title: vi ? `Cảnh ${shot.shot_number}: phiên bản ${takeIndex}` : `Scene ${shot.shot_number}: take ${takeIndex}`,
      text: vi ? "Đang làm lại chuyển cảnh và nhạc nền." : "Redoing the transitions and music.",
      type: "success",
    });
  } catch (err) {
    notify({
      title: vi ? "Không thể đổi phiên bản" : "Could not switch takes",
      text: errorMessage(err, ""),
      type: "error",
    });
  }
}

function onAskAiRewriteShot(instruction) {
  const shot = activeSelectedShot.value;
  if (!shot?.name) return;
  reviseShotWithAi(shot.name, instruction);
}

const timelineMarkers = ref([]);

// A comment was added, changed or applied; applying also starts a new take, so follow its render.
async function onReviewChanged(event = {}) {
  await fetchWorkspace();
  if (event.regenerating) resumeProduction(workspace.value?.production, workspace.value?.project?.planning_status);
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
  const clip = selectedClip.value;
  if (!clip) return;
  const localFrame = Math.round(playheadFrame.value) - Number(clip.timeline_start_frame || 0);
  const sourceSplitFrame = Number(clip.source_in_frame || 0) + localFrame;
  if (sourceSplitFrame <= Number(clip.source_in_frame || 0) || sourceSplitFrame >= Number(clip.source_out_frame || 0)) {
    return;
  }
  splitClip(clip, sourceSplitFrame);
}

function handleSplitClip({ clip, sourceSplitFrame }) {
  if (!clip || sourceSplitFrame == null) return;
  return splitClip(clip, sourceSplitFrame);
}

function handleTrimClip({ clip, sourceInFrame, sourceOutFrame }) {
  if (!clip || sourceInFrame == null || sourceOutFrame == null) return;
  return trimClip(clip, sourceInFrame, sourceOutFrame);
}

function handleReorderClip({ clip, targetOrder }) {
  if (!clip || targetOrder == null) return;
  return reorderClip(clip, targetOrder);
}

function handleMoveClip({ clip, timelineStartFrame, trackIndex = null }) {
  if (!clip || timelineStartFrame == null) return;
  return moveClip(clip, timelineStartFrame, trackIndex);
}

function onUpdateSourceForClip() {
  if (!selectedClipSourceShot.value) return;
  updateSourceForShot(selectedClipSourceShot.value.name);
}

function onRegenerateSourceForClip() {
  if (!selectedClipSourceShot.value) return;
  regenerateCurrentShot();
}

async function onReorderShots(fromIdx, toIdx) {
  const previous = [...storyboardShots.value];
  const moved = previous[fromIdx];
  if (!moved) return;
  // Optimistic local reorder; persisted below and reverted if the server rejects it.
  const arr = [...previous];
  arr.splice(fromIdx, 1);
  arr.splice(toIdx, 0, moved);
  arr.forEach((s, idx) => {
    s.shot_number = idx + 1;
  });
  if (workspace.value?.storyboard) {
    workspace.value.storyboard.shots = arr;
  }
  try {
    await call("joymedia.api.storyboard.reorder_project_shot", {
      project_name: projectName.value,
      shot_name: moved.name,
      target_shot_number: toIdx + 1,
    });
  } catch (err) {
    if (workspace.value?.storyboard) {
      workspace.value.storyboard.shots = previous;
    }
    notify({ title: "Error", text: errorMessage(err, "Failed to reorder scenes."), type: "error" });
  }
}

// Lifecycle Hooks
let studioDisposed = false;
onMounted(async () => {
  await fetchWorkspace();
  if (studioDisposed) return;
  videoIdeaPrompt.value = workspace.value?.project?.video_idea || '';
  if (workspace.value?.family?.archived || workspace.value?.project?.status === 'Archived') return;
  resumeProduction(workspace.value?.production, workspace.value?.project?.planning_status);
  if (advancedMode.value) await loadTimeline(true);
});

onUnmounted(() => {
  studioDisposed = true;
  stopPolling();
});
</script>
