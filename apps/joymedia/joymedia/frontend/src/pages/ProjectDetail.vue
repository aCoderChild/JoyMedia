<template>
  <div class="project-studio-page flex-1 flex overflow-hidden w-full h-full min-h-[calc(100vh-52px)] bg-surface-base">
    <!-- Center Stage: Cinema Canvas & Scene Builder -->
    <main class="gflow-center-canvas">
      <!-- Top Studio Control Strip (Inside Canvas View) -->
      <div class="flex items-center justify-between gap-3 mb-2 px-3 py-2 rounded-xl bg-surface-card border border-outline-border shadow-xs">
        <!-- Left: Project Name & Back to Campaigns -->
        <div class="flex items-center gap-2 min-w-0">
          <button
            type="button"
            class="text-xs text-ink-muted hover:text-ink-primary flex items-center gap-1 font-semibold shrink-0 cursor-pointer px-1.5 py-1 rounded-lg hover:bg-surface-hover transition-colors"
            @click="goBack"
          >
            <span>←</span>
            <span>{{ currentLang === 'vi' ? 'Chiến dịch' : 'Campaigns' }}</span>
          </button>
          <span class="text-ink-muted">/</span>
          <input
            v-if="editingProjectName"
            v-model="projectNameDraft"
            class="gflow-project-name-input"
            type="text"
            maxlength="140"
            autofocus
            @keydown.enter.prevent="saveProjectName"
            @keydown.esc="cancelProjectNameEdit"
            @blur="saveProjectName"
          />
          <button
            v-else
            type="button"
            class="text-xs font-bold text-ink-primary truncate cursor-text hover:text-indigo-400 transition-colors"
            :title="currentLang === 'vi' ? 'Bấm để đổi tên dự án' : 'Click to rename project'"
            @click="startProjectNameEdit"
          >
            {{ displayProjectTitle }}
          </button>
          <span
            v-if="workspace?.project?.status"
            class="text-[10px] px-2 py-0.5 rounded-md font-bold uppercase tracking-wider bg-surface-muted border border-outline-border text-indigo-400"
          >
            {{ workspace.project.status === 'Generating' ? (currentLang === 'vi' ? 'Đang chạy' : 'Generating') : (currentLang === 'vi' ? 'Bản nháp' : 'Draft') }}
          </span>
        </div>

        <!-- Right: Studio Mode Switch, Settings Gear & Primary Generate Button -->
        <div class="flex items-center gap-2">
          <!-- Studio Mode Switch: Scenes vs Edit -->
          <div class="studio-mode-switch">
            <button
              type="button"
              :class="{ active: studioMode === 'scene' }"
              @click="studioMode = 'scene'"
            >
              Scenes
            </button>

            <button
              type="button"
              :class="{ active: studioMode === 'edit' }"
              :disabled="!timelineReady"
              :title="!timelineReady ? (currentLang === 'vi' ? 'Cần tạo video xong để mở trình chỉnh sửa Edit' : 'Generate video to enable Edit mode') : ''"
              @click="studioMode = 'edit'"
            >
              Edit
            </button>
          </div>

          <!-- In Edit Mode: Dirty Edit Badge & Context-Dependent Export Button -->
          <div v-if="studioMode === 'edit'" class="flex items-center gap-2">
            <span
              v-if="hasUnexportedEdits"
              class="flex items-center gap-1.5 text-[11px] font-semibold text-amber-400 px-2.5 py-1 rounded-xl bg-amber-500/10 border border-amber-500/20"
            >
              <span class="size-1.5 rounded-full bg-amber-400 animate-pulse" />
              {{ currentLang === 'vi' ? 'Chưa xuất bản dựng mới' : 'Unexported changes' }}
            </span>
            <span
              v-else-if="workspace?.project?.current_output_asset_version"
              class="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-400 px-2.5 py-1 rounded-xl bg-emerald-500/10 border border-emerald-500/20"
            >
              ✓ {{ currentLang === 'vi' ? 'Bản dựng mới nhất' : 'Export up to date' }}
            </span>

            <button
              type="button"
              class="jm-btn-primary !py-1.5 !px-3 text-xs flex items-center gap-1.5 shadow-sm transition-all"
              :class="{
                '!bg-emerald-600 hover:!bg-emerald-500': !hasUnexportedEdits && !isExporting && workspace?.project?.current_output_asset_version
              }"
              :disabled="timelineBusy || isExporting"
              @click="handleExportTimeline"
            >
              <span v-if="isExporting || timelineBusy" class="lucide-refresh-cw size-3 animate-spin" />
              <span v-else-if="!hasUnexportedEdits && workspace?.project?.current_output_asset_version">✓</span>
              <span v-else>💾</span>
              <span>
                {{
                  isExporting
                    ? (exportStatus === 'Queued'
                        ? (currentLang === 'vi' ? 'Đang chờ xuất...' : 'Queued...')
                        : (currentLang === 'vi' ? 'Đang kết xuất...' : 'Rendering...'))
                    : (!hasUnexportedEdits && workspace?.project?.current_output_asset_version
                        ? (currentLang === 'vi' ? 'Đã xuất video' : 'Exported')
                        : (currentLang === 'vi' ? 'Xuất video' : 'Export video'))
                }}
              </span>
            </button>
          </div>

          <button
            v-if="studioMode === 'scene'"
            type="button"
            class="text-xs text-ink-muted hover:text-ink-primary px-2.5 py-1.5 rounded-xl hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer flex items-center gap-1.5 font-semibold bg-surface-muted shadow-xs"
            :title="currentLang === 'vi' ? 'Cài đặt video (Tỉ lệ, Thời lượng, Phong cách)' : 'Video settings (Aspect, Duration, Style)'"
            @click="showSettings = true"
          >
            <span>⚙</span>
            <span class="text-[11px]">{{ currentLang === 'vi' ? 'Cài đặt' : 'Settings' }}</span>
          </button>

          <button
            v-if="studioMode === 'scene'"
            type="button"
            class="jm-btn-primary shadow-md shadow-indigo-600/20 !py-1.5 !px-3 text-xs"
            :class="{ 'animate-pulse': isAutoGenerating || isProductionActive }"
            :disabled="!hasInputAsset || isAutoGenerating || isProductionActive"
            @click="handleMagicGenerateClick"
          >
            <span v-if="isAutoGenerating" class="lucide-refresh-cw size-3 animate-spin" />
            <span v-else class="lucide-sparkles size-3" />
            <span>{{ generateButtonText }}</span>
          </button>
        </div>
      </div>

      <!-- Collapsible Product Assets Pill (Saves vertical space) -->
      <div v-if="projectAssets.length" class="mb-2">
        <div class="flex items-center justify-between py-1 px-3 rounded-xl bg-surface-card border border-outline-border text-xs">
          <button
            type="button"
            class="flex items-center gap-2 font-semibold text-ink-primary hover:text-indigo-400 transition-colors cursor-pointer"
            @click="assetsExpanded = !assetsExpanded"
          >
            <span>📦 {{ currentLang === 'vi' ? 'Tư liệu sản phẩm' : 'Product assets' }} · {{ projectAssets.length }}</span>
            <div class="flex items-center -space-x-1.5 overflow-hidden">
              <img
                v-for="asset in projectAssets.slice(0, 3)"
                :key="asset.name"
                :src="asset.file"
                class="size-5 rounded-full object-cover border border-outline-border bg-black/10"
              />
            </div>
            <span class="text-[10px] text-ink-muted font-normal">
              {{ assetsExpanded ? (currentLang === 'vi' ? '▲ Thu gọn' : '▲ Collapse') : (currentLang === 'vi' ? '▼ Xem tất cả' : '▼ Expand') }}
            </span>
          </button>
          <button
            type="button"
            class="text-xs font-semibold text-indigo-500 hover:text-indigo-400 px-2 py-0.5 rounded-lg hover:bg-indigo-500/10 transition-colors cursor-pointer"
            @click="openMediaPicker"
          >
            + {{ currentLang === 'vi' ? 'Thêm' : 'Add' }}
          </button>
        </div>
        <!-- Expanded asset strip -->
        <div v-if="assetsExpanded" class="mt-1.5 flex items-center gap-2 overflow-x-auto p-2 rounded-xl bg-surface-muted border border-outline-border">
          <div
            v-for="asset in projectAssets"
            :key="asset.asset_version"
            class="group relative flex items-center gap-2 shrink-0 px-2.5 py-1.5 pr-7 rounded-lg bg-surface-card border transition-all cursor-pointer"
            :class="selectedTarget === 'asset' && selectedAsset?.asset_version === asset.asset_version ? 'border-indigo-500 ring-2 ring-indigo-500/20' : 'border-outline-border hover:border-indigo-500/40'"
            @click="selectAssetTarget(asset)"
          >
            <img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" class="size-7 rounded object-cover" />
            <div class="min-w-0">
              <span class="block max-w-[120px] truncate text-[11px] text-ink-primary font-medium">{{ asset.asset_name }}</span>
              <span class="block text-[9px] text-ink-muted">{{ asset.asset_category }}</span>
            </div>
            <button
              type="button"
              class="absolute right-1 top-1/2 -translate-y-1/2 size-5 rounded-full text-ink-muted hover:text-rose-500 hover:bg-rose-500/10 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
              :title="currentLang === 'vi' ? 'Xóa khỏi dự án' : 'Remove from project'"
              @click.stop="removeProjectAsset(asset)"
            >
              ×
            </button>
          </div>
        </div>
      </div>

      <!-- Persistent generation error -->
      <div v-if="productionError" class="mb-2 p-2.5 rounded-xl border border-rose-500/40 bg-rose-500/10 shadow-xs">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="text-xs font-bold text-rose-400">
              {{ currentLang === 'vi' ? 'Không thể tạo video' : 'Video generation failed' }}
            </p>
            <p class="mt-1 text-xs text-rose-200 break-words whitespace-pre-wrap">{{ productionError }}</p>
            <p v-if="production?.status" class="mt-1 text-[11px] text-ink-muted">
              {{ currentLang === 'vi' ? 'Trạng thái' : 'Status' }}: {{ productionStatus }}
            </p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button
              v-if="!magicGenerateError"
              type="button"
              class="px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
              :disabled="retryingFailedScenes"
              @click="retryFailedScenes"
            >
              {{ retryingFailedScenes ? 'Đang thử lại...' : (currentLang === 'vi' ? 'Thử lại' : 'Retry') }}
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold cursor-pointer"
              @click="refresh"
            >
              {{ currentLang === 'vi' ? 'Làm mới' : 'Refresh' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Outdated Timeline Revision Alert Banner -->
      <div
        v-if="studioMode === 'edit' && isOutdated && !dismissOutdatedBanner"
        class="mb-3 p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs shadow-sm"
      >
        <div class="flex items-start gap-2.5">
          <span class="text-amber-400 text-base leading-none">⚠️</span>
          <div>
            <h4 class="font-bold text-amber-300">
              {{ currentLang === 'vi' ? 'Đã có phiên bản kết xuất mới hơn.' : 'A newer generated version is available.' }}
            </h4>
            <p class="text-ink-secondary mt-0.5">
              {{ currentLang === 'vi'
                ? `Timeline biên tập này dựa trên Phiên bản ${timelineSpecVersion || 1}. Các cảnh mới tạo của bạn là Phiên bản ${latestSpecVersion || 2}.`
                : `This edit timeline is based on Version ${timelineSpecVersion || 1}. Your latest generated scenes are Version ${latestSpecVersion || 2}.`
              }}
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <button
            type="button"
            class="px-3 py-1.5 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-secondary border border-outline-border text-xs font-semibold cursor-pointer transition-colors"
            @click="dismissOutdatedBanner = true"
          >
            {{ currentLang === 'vi' ? 'Giữ bản chỉnh sửa hiện tại' : 'Keep current edit' }}
          </button>
          <button
            type="button"
            class="px-3 py-1.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold shadow-xs cursor-pointer transition-colors"
            @click="confirmUpdateTimelineModal = true"
          >
            {{ currentLang === 'vi' ? 'Cập nhật timeline' : 'Update timeline' }}
          </button>
        </div>
      </div>

      <!-- Cinema Viewport Window (Visual Hero: Dominant Center via StudioPreview) -->
      <div class="flex-1 flex flex-col items-center justify-center min-h-[440px] w-full">
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
          :timeline-total-seconds="timelineTotalSeconds"
          :current-timeline-position-label="currentTimelinePositionLabel"
          :is-playing="isPlaying"
          :is-production-active="isProductionActive"
          :is-auto-generating="isAutoGenerating"
          :auto-generate-step="autoGenerateStep"
          :production="production"
          :production-error="productionError"
          :production-status="productionStatus"
          :expected-shot-count="expectedShotCount"
          :estimated-finish-label="estimatedFinishLabel"
          :project-assets="projectAssets"
          :input-asset-categories="inputAssetCategories"
          :upload-category="uploadCategory"
          :settings-format="settingsForm.format"
          :is-playhead-at-keyframe="isPlayheadAtKeyframe"
          :final-video="finalVideo"
          :retrying-failed-scenes="retryingFailedScenes"
          :uploading-images="uploadingImages"
          :selected-shot-index="selectedShotIndex"
          :current-lang="currentLang"
          :is-outdated="isOutdated"
          :get-shot-timestamp-range="getShotTimestampRange"
          @toggle-play-pause="togglePlayPause"
          @loadedmetadata="onPreviewLoadedMetadata"
          @timeupdate="onPreviewTimeUpdate"
          @play="isPlaying = true"
          @pause="isPlaying = false"
          @ended="onPreviewEnded"
          @select-full-video="selectFullVideo"
          @select-clip="previewSelection = 'clip'"
          @select-shot-target="selectShotTarget"
          @jump-to-prev-keyframe="jumpToPrevKeyframe"
          @jump-to-next-keyframe="jumpToNextKeyframe"
          @toggle-keyframe-at-playhead="toggleKeyframeAtPlayhead"
          @retry-failed-scenes="retryFailedScenes"
          @refresh="refresh"
          @open-media-picker="openMediaPicker"
          @upload-selected-images="uploadSelectedImages"
          @update:upload-category="uploadCategory = $event"
        />
      </div>

      <!-- Scene Builder & CapCut Timeline Architecture -->
      <div v-if="studioMode === 'scene'" class="capcut-timeline-container mt-3">
        <!-- Timeline Header -->
        <div class="flex items-center justify-between mb-2 px-1">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
              <span>🎞️</span>
              <span>{{ t('scene_builder') }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
              {{ allShotsList.length }} {{ currentLang === 'vi' ? 'Cảnh' : 'Shots' }} · {{ totalDurationSeconds }}s
            </span>
            <span
              class="hidden sm:inline-flex text-[10px] px-2 py-0.5 rounded-md font-semibold bg-surface-muted text-ink-secondary border border-outline-border cursor-pointer hover:border-indigo-400 transition-colors"
              :title="currentLang === 'vi' ? 'Bấm để đổi chế độ nối cảnh' : 'Click to toggle continuity mode'"
              @click="toggleContinuityMode"
            >
              🔗 {{ settingsForm.continuity_mode === 'Continuous' ? 'Continuous (Chained)' : 'Multi-shot' }}
            </span>
          </div>

          <div class="flex items-center gap-2">
            <span class="text-xs font-mono font-bold text-ink-primary bg-surface-muted px-2 py-0.5 rounded-md border border-outline-border">
              {{ currentTimelinePositionLabel }} / {{ totalDurationSeconds }}s
            </span>
            <button
              v-if="!hasStoryboard"
              type="button"
              class="jm-btn-primary text-xs !py-1 !px-2.5 shadow-xs"
              @click="handleMagicGenerateClick"
            >
              {{ currentLang === 'vi' ? 'Tạo video' : 'Generate video' }}
            </button>
            <button
              v-else
              type="button"
              class="jm-btn-secondary text-xs !py-1 !px-2.5 shadow-xs"
              @click="createAnotherVersion"
            >
              {{ t('btn_new_version') }}
            </button>
          </div>
        </div>

        <!-- CapCut Time Ruler with Playhead (Click to Scrub) -->
        <div class="capcut-ruler cursor-pointer" :title="currentLang === 'vi' ? 'Bấm vào thước đo để tua playhead' : 'Click ruler to scrub playhead'" @click="seekTimelineToPercent($event)">
          <div class="capcut-ruler-ticks">
            <span v-for="tick in timelineTicks" :key="tick">{{ tick }}</span>
          </div>
          <!-- Playhead needle positioned at active shot/keyframe -->
          <div
            class="capcut-playhead"
            :style="{ left: `${playheadPercent}%` }"
          />
        </div>

        <!-- Horizontal Connected Filmstrip Clip Track -->
        <div v-if="allShotsList.length" class="capcut-track">
          <template v-for="(shot, index) in allShotsList" :key="shot.name || shot.shot_number">
            <!-- Shot Clip Item with spatial flex-grow based on duration -->
            <div
              class="capcut-clip"
              :class="{ 'is-selected': isShotSelected(shot, index) && selectedTarget !== 'asset' }"
              :style="{ flex: `${estimateShotDuration(shot)} 1 0%`, minWidth: '140px' }"
              draggable="true"
              @dragstart="startShotDrag(shot, index, $event)"
              @dragover.prevent
              @drop.prevent="dropShot(shot, index)"
              @click="selectShotTarget(shot, index)"
            >
              <!-- Clip Header Bar (Scene name & duration) -->
              <div class="flex items-center justify-between text-[11px] font-bold text-ink-primary mb-1">
                <span>{{ t('shot_n', { n: shot.shot_number }) }}</span>
                <div class="flex items-center gap-1">
                  <button type="button" class="capcut-trim-button" :title="currentLang === 'vi' ? 'Giảm 0,5 giây' : 'Trim 0.5 seconds'" @click.stop="changeShotDuration(shot, -0.5)">−</button>
                  <span class="text-ink-muted font-mono text-[10px] min-w-[34px] text-center">{{ estimateShotDuration(shot) }}s</span>
                  <button type="button" class="capcut-trim-button" :title="currentLang === 'vi' ? 'Tăng 0,5 giây' : 'Extend 0.5 seconds'" @click.stop="changeShotDuration(shot, 0.5)">+</button>
                </div>
              </div>

              <!-- Clip Visual Thumbnail Body (Clean, CapCut/Premiere style without awkward trim handles) -->
              <div class="relative w-full aspect-video rounded-lg overflow-hidden bg-black flex items-center justify-center group shadow-xs">
                <template v-if="getShotVideoFile(shot)">
                  <video
                    :src="getShotVideoFile(shot)"
                    :poster="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file || shot.last_frame_image || undefined"
                    class="w-full h-full object-cover pointer-events-none"
                    preload="auto"
                    autoplay
                    muted
                    loop
                    playsinline
                  />
                  <div class="absolute inset-0 bg-black/25 flex items-center justify-center pointer-events-none">
                    <span class="size-6 rounded-full bg-white/95 text-indigo-600 flex items-center justify-center text-xs shadow font-bold">▶</span>
                  </div>
                </template>
                <img
                  v-else-if="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file"
                  :src="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file"
                  class="w-full h-full object-cover"
                />
                <span v-else class="text-[10px] text-ink-muted font-mono">{{ t('shot_n', { n: shot.shot_number }) }}</span>
              </div>

              <!-- CapCut / Adobe Premiere / Google Flow Keyframe Track Lane -->
              <div class="capcut-keyframe-track-lane mt-1.5 pt-1 border-t border-outline-border/60 relative flex items-center justify-between px-1">
                <!-- Keyframe Interpolation Rail (connecting line) -->
                <div class="absolute left-3 right-3 h-[2px] bg-outline-border rounded-full" />
                <div
                  class="absolute left-3 right-3 h-[2px] bg-gradient-to-r from-indigo-500/80 to-indigo-400/80 rounded-full transition-all"
                  :class="{ 'opacity-100': isShotSelected(shot, index), 'opacity-40': !isShotSelected(shot, index) }"
                />

                <!-- Start Keyframe Node (0.0s / In) -->
                <button
                  type="button"
                  class="capcut-kf-node relative z-10 cursor-pointer transition-transform hover:scale-125"
                  :class="{
                    'is-active': selectedTarget === 'keyframe-start' && selectedShotIndex === index,
                    'is-shot-active': isShotSelected(shot, index)
                  }"
                  :title="currentLang === 'vi' ? `Keyframe Khởi đầu (In): ${formatShotKeyframeTime(index, 0)} - Bấm để xem và sửa` : `Start Keyframe (In): ${formatShotKeyframeTime(index, 0)}`"
                  @click.stop="selectKeyframeTarget(shot, index, 'start')"
                >
                  <span class="capcut-kf-diamond capcut-kf-in" />
                  <span class="capcut-kf-time-badge">In · {{ formatShotKeyframeTime(index, 0) }}</span>
                </button>

                <!-- End Keyframe Node (Duration / Out / Continuity Bridge) -->
                <button
                  type="button"
                  class="capcut-kf-node relative z-10 cursor-pointer transition-transform hover:scale-125"
                  :class="{
                    'is-active': selectedTarget === 'keyframe-end' && selectedShotIndex === index,
                    'is-shot-active': isShotSelected(shot, index)
                  }"
                  :title="currentLang === 'vi' ? `Keyframe Kết thúc (Out): ${formatShotKeyframeTime(index, 1)} - Bấm để xem và sửa` : `End Keyframe (Out): ${formatShotKeyframeTime(index, 1)}`"
                  @click.stop="selectKeyframeTarget(shot, index, 'end')"
                >
                  <span
                    class="capcut-kf-diamond"
                    :class="shot.last_frame_image || settingsForm.continuity_mode === 'Continuous' ? 'capcut-kf-out-set' : 'capcut-kf-out-empty'"
                  />
                  <span class="capcut-kf-time-badge">Out · {{ formatShotKeyframeTime(index, 1) }}</span>
                </button>
              </div>
            </div>

            <!-- CapCut Transition Connector Node Between Shots -->
            <div v-if="index < allShotsList.length - 1" class="capcut-transition-node">
              <button
                type="button"
                class="capcut-transition-pill"
                :title="settingsForm.continuity_mode === 'Continuous'
                  ? (currentLang === 'vi' ? 'Chế độ Nối liền: Frame cuối Cảnh ' + shot.shot_number + ' là Frame đầu Cảnh ' + (shot.shot_number + 1) : 'Continuous: End frame of Shot ' + shot.shot_number + ' chains to next shot')
                  : (currentLang === 'vi' ? 'Chế độ Cắt cảnh độc lập (Multi-shot)' : 'Multi-shot independent cut')"
                @click="toggleContinuityMode"
              >
                <span>{{ settingsForm.continuity_mode === 'Continuous' ? '⫸' : '⧉' }}</span>
                <span class="hidden md:inline">{{ settingsForm.continuity_mode === 'Continuous' ? (currentLang === 'vi' ? 'Nối liền' : 'Continuous') : (currentLang === 'vi' ? 'Cắt cảnh' : 'Cut') }}</span>
              </button>
            </div>
          </template>
        </div>

        <div v-else class="text-center py-6 text-xs text-ink-muted">
          {{ currentLang === 'vi' ? 'Kịch bản phân cảnh sẽ tự động xuất hiện sau khi bạn bấm Tạo Video.' : 'Storyboard scenes will automatically appear after you click Generate Video.' }}
        </div>
      </div>

      <!-- Edit Mode: Post-Generation Persistent Editorial Track -->
      <div v-else class="mt-3">
        <EditTimelineTrack
          :clips="timelineClips"
          :fps="timelineFps"
          :selected-clip-name="selectedClipName"
          :playhead-frame="playheadFrame"
          :busy="timelineBusy"
          :total-frames="timeline?.total_frames || 0"
          :total-seconds="timeline?.total_seconds || 0"
          @select-clip="handleSelectClip"
          @update:playhead-frame="handleEditSeek"
          @trim="handleClipTrim"
          @split="handleClipSplit"
          @duplicate="duplicateClip"
          @delete="deleteClip"
          @reorder="handleClipReorder"
          @select-transition="handleSelectTransition"
        />
      </div>

      <!-- Footer Disclaimer -->
      <footer class="mt-3 text-center text-[11px] text-ink-muted">
        {{ t('disclaimer') }}
      </footer>
    </main>

    <!-- Right Panel: Studio Inspector Component -->
    <StudioInspector
      v-model:active-tab="activeRightTab"
      v-model:selected-target="selectedTarget"
      v-model:prompt-input="promptInput"
      :studio-mode="studioMode"
      :selected-clip="selectedClip"
      :selected-clip-source-shot="selectedClipSourceShot"
      :timeline-busy="timelineBusy"
      :selected-asset="selectedAsset"
      :active-selected-shot="activeSelectedShot"
      :selected-shot-frame="selectedShotFrame"
      :selected-shot-index="selectedShotIndex"
      :continuity-mode="settingsForm.continuity_mode || 'Multi-shot'"
      :current-lang="currentLang"
      :regenerating-source="regeneratingSource"
      :is-production-active="isProductionActive"
      :is-storyboard-draft="isStoryboardDraft"
      :saving-shot="savingShot"
      :duration-seconds="Number(settingsForm.duration) || 15"
      :product-name="campaign.data?.project?.product_name || ''"
      :has-storyboard="hasStoryboard"
      :expected-shot-count="expectedShotCount"
      :is-auto-generating="generatingVideo || retryingFailedScenes || revisingStoryboard"
      :has-input-asset="Boolean(campaign.data?.assets?.length)"
      :estimate-shot-duration="estimateShotDuration"
      :format-shot-keyframe-time="formatShotKeyframeTime"
      :get-shot-video-file="getShotVideoFile"
      @go-back="goBack"
      @change-transition="handleTransitionChange"
      @change-transition-frames="handleTransitionFramesChange"
      @split-clip="splitClipAtCurrentPlayhead"
      @duplicate-clip="duplicateClip"
      @delete-clip="deleteClip"
      @regenerate-source-for-selected-clip="regenerateSourceForSelectedClip"
      @apply-asset-to-shot="applyAssetToShot"
      @select-keyframe-target="handleSelectKeyframeTarget"
      @open-media-picker="openMediaPicker"
      @toggle-continuity-mode="toggleContinuityMode"
      @change-shot-duration="changeShotDuration"
      @regenerate-current-shot="regenerateCurrentShot"
      @copy-prompt="copyPrompt"
      @save-active-shot="saveActiveShot"
      @magic-generate="handleMagicGenerateClick"
    />

    <!-- Global media library picker for this project -->
    <div v-if="showMediaPicker" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs" @click.self="showMediaPicker = false">
      <div class="w-full max-w-3xl max-h-[80vh] overflow-hidden bg-surface-card border border-outline-border rounded-2xl shadow-2xl flex flex-col">
        <div class="flex items-center justify-between p-4 border-b border-outline-border">
          <div>
            <h3 class="text-sm font-bold text-ink-primary">{{ currentLang === 'vi' ? 'Thêm tư liệu' : 'Add Media' }}</h3>
            <p class="text-xs text-ink-muted mt-1">{{ currentLang === 'vi' ? 'Chọn tư liệu từ thư viện Media.' : 'Choose media from the Media Library.' }}</p>
          </div>
          <button type="button" class="text-ink-muted hover:text-ink-primary p-1 cursor-pointer" @click="showMediaPicker = false">✕</button>
        </div>
        <div class="p-4 overflow-y-auto">
          <div v-if="mediaCandidatesLoading" class="py-10 text-center text-xs text-ink-muted">
            <span class="lucide-refresh-cw size-5 animate-spin inline-block" />
          </div>
          <div v-else-if="mediaCandidates.length" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            <button
              v-for="asset in mediaCandidates"
              :key="asset.name"
              type="button"
              class="text-left p-2 rounded-xl border transition-colors cursor-pointer"
              :class="asset.selected ? 'border-indigo-500 bg-indigo-500/10' : 'border-outline-border bg-surface-muted hover:border-indigo-500/60'"
              :disabled="(asset.selected && selectedTarget !== 'keyframe-start' && selectedTarget !== 'keyframe-end') || selectingMedia"
              @click="selectMediaAsset(asset)"
            >
              <img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" class="w-full aspect-video rounded-lg object-cover bg-black/10" />
              <div v-else class="w-full aspect-video rounded-lg bg-surface-hover flex items-center justify-center text-xs text-ink-muted">No preview</div>
              <span class="block truncate mt-2 text-xs font-semibold text-ink-primary">{{ asset.asset_name }}</span>
              <span class="block mt-0.5 text-[10px] text-ink-muted">{{ asset.asset_category }}</span>
            </button>
          </div>
          <div v-else class="py-10 text-center text-xs text-ink-muted">
            {{ currentLang === 'vi' ? 'Chưa có tư liệu hình ảnh trong thư viện.' : 'No image assets are available in the library.' }}
          </div>
        </div>
      </div>
    </div>

    <!-- Settings Modal -->
    <div v-if="showSettings" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs" @click.self="showSettings = false">
      <div class="w-full max-w-lg bg-surface-card border border-outline-border rounded-2xl p-6 shadow-2xl space-y-4 text-xs">
        <div class="flex items-center justify-between pb-3 border-b border-outline-border">
          <h3 class="text-sm font-bold text-ink-primary">{{ t('settings_modal_title') }}</h3>
          <button type="button" class="text-ink-muted hover:text-ink-primary cursor-pointer p-1" @click="showSettings = false">✕</button>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-ink-secondary mb-1 font-semibold">{{ t('settings_duration_label') }}</label>
            <input
              v-model.number="settingsForm.duration"
              type="number"
              min="3"
              max="120"
              class="w-full px-3 py-1.5 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary font-mono font-bold focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label class="block text-ink-secondary mb-1 font-semibold">{{ t('settings_aspect_label') }}</label>
            <div class="grid grid-cols-3 gap-1 mt-0.5">
              <button
                type="button"
                class="py-2 px-1 rounded-xl border text-center transition-all cursor-pointer"
                :class="settingsForm.format === 'Landscape' ? 'bg-indigo-600 text-white border-indigo-600 font-bold shadow-xs' : 'bg-surface-muted text-ink-secondary border-outline-border hover:border-indigo-400'"
                @click="settingsForm.format = 'Landscape'"
              >
                <span class="block text-xs font-bold">16:9</span>
                <span class="block text-[9px] opacity-80">Ngang</span>
              </button>
              <button
                type="button"
                class="py-2 px-1 rounded-xl border text-center transition-all cursor-pointer"
                :class="settingsForm.format === 'Portrait' ? 'bg-indigo-600 text-white border-indigo-600 font-bold shadow-xs' : 'bg-surface-muted text-ink-secondary border-outline-border hover:border-indigo-400'"
                @click="settingsForm.format = 'Portrait'"
              >
                <span class="block text-xs font-bold">9:16</span>
                <span class="block text-[9px] opacity-80">Dọc</span>
              </button>
              <button
                type="button"
                class="py-2 px-1 rounded-xl border text-center transition-all cursor-pointer"
                :class="settingsForm.format === 'Square' ? 'bg-indigo-600 text-white border-indigo-600 font-bold shadow-xs' : 'bg-surface-muted text-ink-secondary border-outline-border hover:border-indigo-400'"
                @click="settingsForm.format = 'Square'"
              >
                <span class="block text-xs font-bold">1:1</span>
                <span class="block text-[9px] opacity-80">Vuông</span>
              </button>
            </div>
          </div>
        </div>

        <div>
          <label class="block text-ink-secondary mb-1 font-semibold">{{ t('settings_continuity_label') }}</label>
          <FormControl
            v-model="settingsForm.continuity_mode"
            type="select"
            :options="[
              { label: t('opt_multishot'), value: 'Multi-shot' },
              { label: t('opt_continuous'), value: 'Continuous' },
            ]"
          />
        </div>

        <div>
          <label class="block text-ink-secondary mb-1 font-semibold">{{ t('settings_style_label') }}</label>
          <FormControl
            v-model="settingsForm.video_style"
            type="select"
            :options="(videoStyles.data || []).map(s => ({ label: s.client_name, value: s.workflow_key }))"
          />
        </div>

        <div class="flex items-center justify-end gap-2.5 pt-3 border-t border-outline-border">
          <button
            type="button"
            class="px-3.5 py-2 rounded-xl text-xs font-semibold bg-surface-muted hover:bg-surface-hover text-ink-primary border border-outline-border transition-all cursor-pointer"
            @click="showSettings = false"
          >
            {{ t('btn_close') }}
          </button>
          <button
            type="button"
            class="px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all cursor-pointer flex items-center gap-1.5"
            :disabled="savingSettings"
            @click="saveSettings"
          >
            <span v-if="savingSettings" class="lucide-refresh-cw size-3 animate-spin" />
            <span>{{ t('btn_save_settings') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Confirmation Dialog: Update Timeline from Latest Generated Specification -->
    <div
      v-if="confirmUpdateTimelineModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
      @click.self="confirmUpdateTimelineModal = false"
    >
      <div class="w-full max-w-md bg-surface-card border border-outline-border rounded-2xl p-5 shadow-2xl space-y-4">
        <div class="flex items-center gap-3">
          <div class="size-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center text-lg shrink-0">
            ⚠️
          </div>
          <div>
            <h3 class="text-sm font-bold text-ink-primary">
              {{ currentLang === 'vi' ? 'Cập nhật dòng thời gian dựng?' : 'Update edit timeline?' }}
            </h3>
            <p class="text-xs text-ink-muted">
              {{ currentLang === 'vi' ? 'Đã có phiên bản kịch bản phân cảnh mới hơn.' : 'A newer generated scene specification is available.' }}
            </p>
          </div>
        </div>

        <p class="text-xs text-ink-secondary leading-relaxed bg-surface-muted p-3 rounded-xl border border-outline-border">
          {{ currentLang === 'vi'
            ? 'Cập nhật timeline sẽ thay thế các điểm cắt (trims), thứ tự clip, tách clip và hiệu ứng chuyển cảnh hiện tại bằng các cảnh mới tạo nhất.'
            : 'Updating the edit timeline will replace your current trims, clip order, splits and transitions with the newest generated scenes.' }}
        </p>

        <div class="flex items-center justify-end gap-2.5 pt-2">
          <button
            type="button"
            class="px-3.5 py-2 rounded-xl text-xs font-semibold bg-surface-muted hover:bg-surface-hover text-ink-primary border border-outline-border transition-colors cursor-pointer"
            :disabled="timelineBusy"
            @click="confirmUpdateTimelineModal = false"
          >
            {{ currentLang === 'vi' ? 'Hủy' : 'Cancel' }}
          </button>
          <button
            type="button"
            class="px-4 py-2 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white shadow-md shadow-amber-600/20 transition-all cursor-pointer flex items-center gap-1.5"
            :disabled="timelineBusy"
            @click="handleConfirmUpdateTimeline"
          >
            <span v-if="timelineBusy" class="lucide-refresh-cw size-3 animate-spin" />
            <span>{{ currentLang === 'vi' ? 'Cập nhật timeline' : 'Update timeline' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Button, FormControl, call, createResource, toast, upload as uploadFile } from "frappe-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "../stores/i18n";
import { useProjectTimeline } from "../composables/useProjectTimeline";
import EditTimelineTrack from "../components/studio/EditTimelineTrack.vue";
import StudioPreview from "../components/studio/StudioPreview.vue";
import StudioInspector from "../components/studio/StudioInspector.vue";

const { t, currentLang } = useI18n();

const route = useRoute();
const projectName = computed(() => route.params.name);

// Studio Mode: 'scene' (pre-generation / storyboard) vs 'edit' (post-generation NLE)
const studioMode = ref("scene");
const exporting = ref(false);

// Timeline State & Editorial Service Controller
const {
  timeline,
  clips: timelineClips,
  fps: timelineFps,
  busy: timelineBusy,
  exportStatus,
  exportError,
  isExporting,
  isOutdated,
  latestSpecVersion,
  timelineSpecVersion,
  selectedClip,
  selectedClipName,
  playheadFrame,
  loadTimeline,
  trimClip,
  reorderClip,
  splitClip,
  duplicateClip,
  deleteClip,
  setTransition,
  resetTimeline,
  exportTimeline,
} = useProjectTimeline(projectName);

const timelineReady = computed(() => Boolean(timeline.value?.ready));

// Backend Resources
const campaign = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_project_workspace",
  params: { name: projectName.value },
  auto: true,
});
const productionResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_project_production",
  params: { name: projectName.value },
  auto: true,
});
const videoStyles = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_video_styles",
  auto: true,
});

// UI State
const plan = ref(null);
const showSettings = ref(false);
const savingSettings = ref(false);
const generatingVideo = ref(false);
const retryingFailedScenes = ref(false);
const revisingStoryboard = ref(false);
const uploadingImages = ref(false);
const showMediaPicker = ref(false);
const mediaCandidates = ref([]);
const mediaCandidatesLoading = ref(false);
const selectingMedia = ref(false);
const editingProjectName = ref(false);
const projectNameDraft = ref("");
const uploadCategory = ref("Product");
const selectedShotIndex = ref(0);
const draggedShot = ref(null);
const activeCanvasPreview = ref(null);
const previewSelection = ref("full");
const promptInput = ref("");
const showAdvancedPrompt = ref(false);

// Contextual Selection-Based Editor State
const selectedTarget = ref("scene"); // 'scene' | 'asset' | 'keyframe-start' | 'keyframe-end' | 'full'
const selectedAsset = ref(null);
const assetsExpanded = ref(false);
const isPlaying = ref(false);
const studioPreviewRef = ref(null);
const previewVideo = computed(() => studioPreviewRef.value?.previewVideo || null);
const confirmUpdateTimelineModal = ref(false);
const dismissOutdatedBanner = ref(false);

const hasUnexportedEdits = computed(() =>
  studioMode.value === "edit" &&
  timelineReady.value &&
  !workspace.value?.project?.current_output_asset_version
);

function applyAssetToShot(asset) {
  if (!activeSelectedShot.value || !asset) return;
  activeSelectedShot.value.reference_image = asset.file;
  activeSelectedShot.value.reference_asset_name = asset.asset_name;
  selectedTarget.value = "scene";
}

function handleSelectKeyframeTarget(target) {
  if (!activeSelectedShot.value) return;
  selectKeyframeTarget(activeSelectedShot.value, selectedShotIndex.value, target);
}


async function handleConfirmUpdateTimeline() {
  try {
    const success = await resetTimeline();
    if (success) {
      toast({
        title: currentLang.value === "vi" ? "Đã cập nhật dòng thời gian" : "Timeline updated",
        text: currentLang.value === "vi"
          ? "Đã đồng bộ các cảnh mới nhất vào dòng thời gian dựng."
          : "Timeline synchronized with the latest generated scenes.",
        type: "success",
      });
      confirmUpdateTimelineModal.value = false;
      dismissOutdatedBanner.value = false;
      campaign.reload();
    }
  } catch (err) {
    toast({
      title: currentLang.value === "vi" ? "Lỗi cập nhật" : "Update failed",
      text: err.message || "Failed to update timeline",
      type: "error",
    });
  }
}
const playheadSeconds = ref(0);
const openAccordion = reactive({
  subject: false,
  motion: false,
  camera: false,
  audio: false,
});

function toggleAccordion(key) {
  openAccordion[key] = !openAccordion[key];
}

function formatSecondsLabel(s) {
  const num = Number(s) || 0;
  const mins = Math.floor(num / 60);
  const secs = num % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function getShotTimestampRange(shot) {
  const list = allShotsList.value;
  const idx = list.indexOf(shot) >= 0 ? list.indexOf(shot) : selectedShotIndex.value;
  const startSec = list.slice(0, idx).reduce((sum, item) => sum + Number(estimateShotDuration(item)), 0);
  const endSec = startSec + Number(estimateShotDuration(list[idx] || shot));
  return `${formatSecondsLabel(startSec)}–${formatSecondsLabel(endSec)}`;
}

async function togglePlayPause() {
  const video = previewVideo.value;
  if (!video) {
    isPlaying.value = false;
    return;
  }
  if (video.paused) {
    await video.play().catch(() => {
      isPlaying.value = false;
    });
  } else {
    video.pause();
  }
}

function selectAssetTarget(asset) {
  selectedTarget.value = "asset";
  selectedAsset.value = asset;
  activeCanvasPreview.value = {
    title: asset.asset_name,
    url: asset.file,
    isVideo: false,
  };
  activeRightTab.value = "shot";
}

function selectShotTarget(shot, index) {
  selectedTarget.value = "scene";
  selectShot(shot, index);
}

function selectKeyframeTarget(shot, index, type) {
  selectedTarget.value = type === "start" ? "keyframe-start" : "keyframe-end";
  selectedShotIndex.value = index;
  playheadSeconds.value = shotStartSeconds(index) + (type === "end" ? Number(estimateShotDuration(shot)) : 0);
  previewKeyframe(shot, type);
}

// 1-Click Auto Generation State
const isAutoGenerating = ref(false);
const autoGenerateStep = ref("");
const magicGenerateError = ref("");

const settingsForm = reactive({ duration: 15, format: "Landscape", video_style: "", continuity_mode: "Multi-shot" });
const totalDurationSeconds = computed(() => Number(settingsForm.duration) || 15);
const durationOptions = [5, 8, 10, 15, 20, 30, 45, 60];
const availableDurations = computed(() => {
  const current = Number(settingsForm.duration);
  if (current && !durationOptions.includes(current)) {
    return [...durationOptions, current].sort((a, b) => a - b);
  }
  return durationOptions;
});
const inputAssetCategories = ["Product", "Character", "Background", "Brand", "Style", "Reference"];
const workspace = computed(() => campaign.data);
const settings = computed(() => workspace.value?.video_settings);
// Keep a separate, explicit snapshot for production state.  The workspace
// response is useful as an initial fallback, but it must not remain the
// source of truth after a new generation run starts.
const productionSnapshot = ref(null);
const productionSnapshotLoaded = ref(false);
const production = computed(() => {
  if (productionSnapshotLoaded.value && productionSnapshot.value) {
    return productionSnapshot.value;
  }
  return productionResource.data || workspace.value?.production || null;
});
const finalVideo = computed(() => timeline.value?.final_video || production.value?.final_video || workspace.value?.final_video || null);
const timelineTotalSeconds = computed(() => {
  if (studioMode.value === "edit") {
    return Number(timeline.value?.total_seconds || totalDurationSeconds.value);
  }
  return totalDurationSeconds.value;
});
const projectAssets = computed(() => workspace.value?.assets || []);
const hasInputAsset = computed(() => projectAssets.value.some((asset) => asset.file && asset.media_type === "Image"));

const displayProjectTitle = computed(() => {
  const pName = workspace.value?.project?.project_name;
  if (pName && pName.trim() && pName.trim().toLowerCase() !== "untitled") {
    return pName.trim();
  }
  const prodName = workspace.value?.project?.product_name;
  const dur = totalDurationSeconds.value;
  if (prodName && prodName.trim()) {
    return `${prodName.trim()} – ${dur}s Product Showcase`;
  }
  return currentLang.value === "vi" ? `Dự án video ${dur}s` : `Video Project ${dur}s`;
});

const generateButtonText = computed(() => {
  if (isAutoGenerating.value) {
    return autoGenerateStep.value || (currentLang.value === "vi" ? "Đang khởi chạy..." : "Starting...");
  }
  const status = production.value?.status;
  if (status === "Running") {
    const comp = Number(production.value?.completed_jobs || 0);
    const tot = Number(production.value?.total_jobs || 0);
    const pct = production.value?.progress_percent ?? production.value?.progress;
    if (pct >= 100 || (tot > 0 && comp >= tot)) {
      return currentLang.value === "vi" ? "Đang hoàn thiện..." : "Finalizing...";
    }
    return `${pct || 0}% ${currentLang.value === "vi" ? "Đang xử lý..." : "Rendering..."}`;
  }
  if (status === "Completed") {
    return currentLang.value === "vi" ? "✓ Hoàn tất" : "✓ Completed";
  }
  if (status === "Failed") {
    return currentLang.value === "vi" ? "Thử lại" : "Retry";
  }
  if (hasStoryboard.value) {
    return currentLang.value === "vi" ? "Tạo video" : "Generate video";
  }
  return currentLang.value === "vi" ? "Tạo video" : "Generate video";
});

const timelineTicks = computed(() => {
  const total = totalDurationSeconds.value;
  let interval = 5;
  if (total <= 10) interval = 2;
  else if (total <= 20) interval = 3;
  else if (total <= 35) interval = 5;
  else interval = 10;

  const ticks = [];
  for (let s = 0; s <= total; s += interval) {
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    const label = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    ticks.push(label);
  }
  return ticks;
});

const playheadPercent = computed(() => {
  const total = totalDurationSeconds.value;
  return total ? Math.min(100, Math.max(0, (playheadSeconds.value / total) * 100)) : 0;
});

const currentTimelinePositionLabel = computed(() => {
  if (studioMode.value === "edit") {
    const fps = Number(timelineFps.value || 24);
    const totalSecs = Math.max(0, Math.floor(Number(playheadFrame.value || 0) / fps));
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return formatSecondsLabel(Math.round(playheadSeconds.value));
});

const isPlayheadAtKeyframe = computed(() => {
  return selectedTarget.value === "keyframe-start" || selectedTarget.value === "keyframe-end";
});

function jumpToPrevKeyframe() {
  const count = allShotsList.value.length || 1;
  if (selectedTarget.value === "keyframe-end") {
    selectKeyframeTarget(activeSelectedShot.value, selectedShotIndex.value, "start");
  } else if (selectedTarget.value === "keyframe-start") {
    if (selectedShotIndex.value > 0) {
      const prevIdx = selectedShotIndex.value - 1;
      const prevShot = allShotsList.value[prevIdx];
      selectKeyframeTarget(prevShot, prevIdx, "end");
    }
  } else {
    selectKeyframeTarget(activeSelectedShot.value, selectedShotIndex.value, "start");
  }
}

function jumpToNextKeyframe() {
  const count = allShotsList.value.length || 1;
  if (selectedTarget.value === "keyframe-start") {
    selectKeyframeTarget(activeSelectedShot.value, selectedShotIndex.value, "end");
  } else if (selectedTarget.value === "keyframe-end") {
    if (selectedShotIndex.value < count - 1) {
      const nextIdx = selectedShotIndex.value + 1;
      const nextShot = allShotsList.value[nextIdx];
      selectKeyframeTarget(nextShot, nextIdx, "start");
    }
  } else {
    selectKeyframeTarget(activeSelectedShot.value, selectedShotIndex.value, "end");
  }
}

function toggleKeyframeAtPlayhead() {
  if (isPlayheadAtKeyframe.value) {
    selectedTarget.value = "scene";
  } else {
    selectKeyframeTarget(activeSelectedShot.value, selectedShotIndex.value, "start");
  }
}

function formatShotKeyframeTime(index, position) {
  const list = allShotsList.value;
  const start = list.slice(0, index).reduce((sum, shot) => sum + Number(estimateShotDuration(shot)), 0);
  const s = position === 0
    ? Math.round(start)
    : Math.round(start + Number(estimateShotDuration(list[index])));
  return formatSecondsLabel(s);
}

function seekTimelineToPercent(event) {
  const ruler = event.currentTarget;
  if (!ruler) return;
  const rect = ruler.getBoundingClientRect();
  const clickX = event.clientX - rect.left;
  const pct = Math.max(0, Math.min(100, (clickX / rect.width) * 100));

  const seconds = (pct / 100) * totalDurationSeconds.value;
  seekTimeline(seconds);
}

function shotStartSeconds(index) {
  return allShotsList.value
    .slice(0, index)
    .reduce((sum, shot) => sum + Number(estimateShotDuration(shot)), 0);
}

function seekTimeline(seconds) {
  const list = allShotsList.value;
  if (!list.length) return;
  const clamped = Math.max(0, Math.min(Number(seconds) || 0, totalDurationSeconds.value));
  let elapsed = 0;
  let index = list.length - 1;
  for (let i = 0; i < list.length; i += 1) {
    const duration = Number(estimateShotDuration(list[i]));
    if (clamped <= elapsed + duration || i === list.length - 1) {
      index = i;
      break;
    }
    elapsed += duration;
  }
  selectedShotIndex.value = index;
  selectedTarget.value = "scene";
  activeCanvasPreview.value = null;
  previewSelection.value = "shot";
  playheadSeconds.value = clamped;
  nextTick(syncPreviewToPlayhead);
}

function syncPreviewToPlayhead() {
  const video = previewVideo.value;
  const shot = activeSelectedShot.value;
  if (!video || !shot) return;
  const localTime = Math.max(0, playheadSeconds.value - shotStartSeconds(selectedShotIndex.value));
  if (Math.abs(video.currentTime - localTime) > 0.05) video.currentTime = localTime;
}

function handlePreviewTimeUpdate() {
  if (previewSelection.value !== "shot" || !previewVideo.value) return;
  playheadSeconds.value = Math.min(
    totalDurationSeconds.value,
    shotStartSeconds(selectedShotIndex.value) + previewVideo.value.currentTime,
  );
}

async function handleShotEnded() {
  const nextIndex = selectedShotIndex.value + 1;
  if (nextIndex >= allShotsList.value.length) {
    isPlaying.value = false;
    playheadSeconds.value = totalDurationSeconds.value;
    return;
  }
  selectedShotIndex.value = nextIndex;
  selectedTarget.value = "scene";
  activeCanvasPreview.value = null;
  previewSelection.value = "shot";
  playheadSeconds.value = shotStartSeconds(nextIndex);
  await nextTick();
  const video = previewVideo.value;
  if (video) {
    video.currentTime = 0;
    await video.play().catch(() => { isPlaying.value = false; });
  }
}

const productionError = computed(() => {
  if (magicGenerateError.value) return magicGenerateError.value;
  if (!production.value) return "";
  if (production.value.error_summary) return production.value.error_summary;
  const failedJob = (production.value.jobs || []).find(
    (job) => job.status === "Failed" && job.error_summary
  );
  if (failedJob?.error_summary) return failedJob.error_summary;
  if (production.value.status === "Failed" || production.value.failed_jobs > 0) {
    return currentLang.value === "vi"
      ? "Một hoặc nhiều cảnh không thể tạo. Vui lòng thử lại."
      : "One or more shots could not be generated. Please retry.";
  }
  return "";
});
const productionStatus = computed(() => {
  if (productionError.value) return "Failed";
  return production.value?.status || "";
});
const expectedShotCount = computed(() => {
  const productionTotal = Number(production.value?.total_jobs || 0);
  if (productionTotal > 0) return productionTotal;

  const storyboardCount = Number(workspace.value?.storyboard?.length || 0);
  if (storyboardCount > 0) return storyboardCount;

  const automaticCount = Number(workspace.value?.video_settings?.automatic_shot_count || 0);
  return automaticCount > 0 ? automaticCount : 1;
});

const hasStoryboard = computed(() => Boolean(workspace.value?.storyboard?.length));

const allShotsList = computed(() => {
  if (plan.value?.shots?.length) return plan.value.shots;
  return workspace.value?.storyboard || [];
});

const activeSelectedShot = computed(() => {
  const list = allShotsList.value;
  if (!list.length) return null;
  return list[selectedShotIndex.value] || list[0];
});

const selectedShotFrame = computed(() => {
  if (!activeSelectedShot.value) return null;
  return getShotFirstFrame(activeSelectedShot.value, Boolean(plan.value?.shots?.length));
});

const activeCanvasMedia = computed(() => {
  if (activeCanvasPreview.value) return activeCanvasPreview.value;
  if (previewSelection.value === "full" && finalVideo.value?.file) {
    return { title: "Master Deliverable", url: finalVideo.value.file, isVideo: true, isMaster: true };
  }
  if (activeSelectedShot.value) {
    const outputVideo = getShotVideoFile(activeSelectedShot.value);
    if (outputVideo) {
      return { title: `Cảnh ${activeSelectedShot.value.shot_number}`, url: outputVideo, isVideo: true };
    }
    const frame = selectedShotFrame.value;
    if (frame?.file) {
      return { title: `Cảnh ${activeSelectedShot.value.shot_number}`, url: frame.file, isVideo: false };
    }
  }
  return null;
});

const studioPreview = computed(() => {
  if (
    studioMode.value === "edit" &&
    selectedClip.value?.source_file
  ) {
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
      title: "Master Deliverable",
    };
  }

  if (activeCanvasMedia.value?.url) {
    return {
      type: "shot",
      url: activeCanvasMedia.value.url,
      isVideo: Boolean(activeCanvasMedia.value.isVideo),
      media: activeCanvasMedia.value,
      title: activeCanvasMedia.value.title,
    };
  }

  return null;
});

const selectedClipSourceShot = computed(() => {
  if (!selectedClip.value) return null;
  return (
    allShotsList.value.find(
      (s) =>
        s.name === selectedClip.value.shot_specification ||
        s.shot_number === selectedClip.value.shot_number
    ) || null
  );
});

const activeRightTab = ref("director");
const savingShot = ref(false);
const regeneratingSource = ref(false);

const isStoryboardDraft = computed(() => {
  return settings.value?.status === "Draft" || !production.value;
});

function isShotSelected(shot, index) {
  return selectedShotIndex.value === index;
}

function startProjectNameEdit() {
  projectNameDraft.value = workspace.value?.project?.project_name || "";
  editingProjectName.value = true;
}

function cancelProjectNameEdit() {
  editingProjectName.value = false;
  projectNameDraft.value = "";
}

async function saveProjectName() {
  if (!editingProjectName.value) return;
  const nextName = projectNameDraft.value.trim();
  if (!nextName || nextName === workspace.value?.project?.project_name) {
    cancelProjectNameEdit();
    return;
  }
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.update_project_name", {
      media_project: projectName.value,
      project_name: nextName,
    });
    await campaign.reload();
    toast({ title: "Đã cập nhật tên dự án", text: nextName, type: "success" });
  } catch (error) {
    toast({ title: "Lỗi cập nhật tên", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    cancelProjectNameEdit();
  }
}

function selectShot(shot, index) {
  selectedShotIndex.value = index;
  activeCanvasPreview.value = null;
  previewSelection.value = "shot";
  activeRightTab.value = "shot";
  playheadSeconds.value = shotStartSeconds(index);
  nextTick(syncPreviewToPlayhead);
}

function selectFullVideo() {
  previewSelection.value = "full";
  activeCanvasPreview.value = null;
}

function togglePreviewFullOrShot() {
  if (previewSelection.value === "full") {
    previewSelection.value = "shot";
    activeCanvasPreview.value = null;
  } else {
    previewSelection.value = "full";
    activeCanvasPreview.value = null;
  }
}

function previewKeyframe(shot, type) {
  if (type === "start") {
    const frame = getShotFirstFrame(shot, Boolean(plan.value?.shots?.length));
    if (frame?.file) {
      activeCanvasPreview.value = {
        title: `Cảnh ${shot.shot_number} · Frame đầu (Keyframe In)`,
        url: frame.file,
        isVideo: false,
      };
      previewSelection.value = "shot";
      toast({
        title: currentLang.value === "vi" ? "Khung hình mẫu đầu (In)" : "Start Keyframe (In)",
        text: currentLang.value === "vi" ? `Xem khung hình mẫu cảnh ${shot.shot_number}.` : `Viewing start frame of shot ${shot.shot_number}.`,
        type: "info",
      });
      return;
    }
  } else if (type === "end") {
    if (shot.last_frame_image) {
      activeCanvasPreview.value = {
        title: `Cảnh ${shot.shot_number} · Frame cuối (Keyframe Out)`,
        url: shot.last_frame_image,
        isVideo: false,
      };
      previewSelection.value = "shot";
      toast({
        title: currentLang.value === "vi" ? "Khung hình mẫu cuối (Out)" : "End Keyframe (Bridge)",
        text: currentLang.value === "vi" ? `Xem khung hình nối cảnh ${shot.shot_number}.` : `Viewing bridge frame of shot ${shot.shot_number}.`,
        type: "info",
      });
      return;
    }
  }
  const idx = allShotsList.value.findIndex((s) => (s.name && s.name === shot.name) || s.shot_number === shot.shot_number);
  selectShot(shot, idx >= 0 ? idx : 0);
}

async function toggleContinuityMode() {
  settingsForm.continuity_mode = settingsForm.continuity_mode === "Continuous" ? "Multi-shot" : "Continuous";
  await saveSettings();
  toast({
    title: currentLang.value === "vi" ? "Chế độ nối cảnh" : "Continuity Mode",
    text: settingsForm.continuity_mode === "Continuous"
      ? (currentLang.value === "vi" ? "Đã chuyển sang Nối liền (Continuous)" : "Switched to Continuous")
      : (currentLang.value === "vi" ? "Đã chuyển sang Cắt cảnh (Multi-shot)" : "Switched to Multi-shot"),
    type: "info",
  });
}

function shotStatus(shot) {
  if (getShotVideoFile(shot)) return "Ready";
  if (isProductionActive.value || isAutoGenerating.value) return "Generating";
  return "Draft";
}

function shotStatusClass(shot) {
  const status = shotStatus(shot);
  if (status === "Approved" || status === "Ready") return "text-emerald-500";
  if (status === "Failed" || status === "Rejected") return "text-rose-500";
  if (status === "Generating" || status === "Pending") return "text-amber-500";
  return "text-ink-muted";
}

async function saveActiveShot() {
  const shot = activeSelectedShot.value;
  if (!shot || !shot.name) return;
  savingShot.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.update_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
      values: {
        subject_identity: shot.subject_identity,
        action_plot: shot.action_plot,
        camera_direction: shot.camera_direction,
        environment: shot.environment,
        audio_direction: shot.audio_direction,
      },
    });
    toast({ title: "Đã lưu cảnh", text: `Đã cập nhật Cảnh ${shot.shot_number}.`, type: "success" });
    await refresh();
  } catch (error) {
    toast({ title: "Lỗi lưu cảnh", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    savingShot.value = false;
  }
}

function copyPrompt(text) {
  if (!text) return;
  if (navigator?.clipboard?.writeText) {
    navigator.clipboard.writeText(text);
  }
  toast({ title: "Đã sao chép prompt", text: "Prompt đã được lưu vào clipboard.", type: "success" });
}

// Playback and Editorial Timeline Handlers
function seekClipStart() {
  if (!previewVideo.value || !selectedClip.value) return;
  const fps = Number(timelineFps.value) || 24;
  previewVideo.value.currentTime = Number(selectedClip.value.source_in_frame || 0) / fps;
}

function onPreviewLoadedMetadata() {
  if (studioMode.value === "edit") {
    seekClipStart();
  } else {
    syncPreviewToPlayhead();
  }
}

function onPreviewTimeUpdate() {
  if (studioMode.value === "edit") {
    if (!previewVideo.value || !selectedClip.value) return;
    const fps = Number(timelineFps.value) || 24;
    const currentFrame = previewVideo.value.currentTime * fps;

    // Sync playhead frame in timeline
    const clipOffset = currentFrame - Number(selectedClip.value.source_in_frame || 0);
    playheadFrame.value = Math.max(
      selectedClip.value.timeline_start_frame,
      Math.min(selectedClip.value.timeline_end_frame, Math.round(selectedClip.value.timeline_start_frame + clipOffset))
    );

    if (currentFrame >= Number(selectedClip.value.source_out_frame || 0)) {
      previewVideo.value.pause();
      previewVideo.value.currentTime = Number(selectedClip.value.source_in_frame || 0) / fps;
      isPlaying.value = false;
    }
  } else {
    handlePreviewTimeUpdate();
  }
}

function onPreviewEnded() {
  isPlaying.value = false;
  if (studioMode.value === "scene") {
    handleShotEnded();
  }
}

watch(
  () => selectedClip.value?.name,
  (clipName) => {
    if (studioMode.value === "edit" && clipName) {
      nextTick(() => {
        seekClipStart();
      });
    }
  }
);

function handleSelectClip(clip, sourceFrame = null) {
  selectedClipName.value = clip.name;
  previewSelection.value = "clip";
  activeRightTab.value = "shot";
  const fps = Number(timelineFps.value) || 24;
  if (sourceFrame !== null && previewVideo.value) {
    previewVideo.value.currentTime = sourceFrame / fps;
  } else {
    nextTick(seekClipStart);
  }
}

function handleEditSeek(frame) {
  playheadFrame.value = frame;
  if (selectedClip.value && previewVideo.value) {
    const fps = Number(timelineFps.value) || 24;
    const clipStart = selectedClip.value.timeline_start_frame;
    const clipEnd = selectedClip.value.timeline_end_frame;
    if (frame >= clipStart && frame <= clipEnd) {
      const offset = frame - clipStart;
      previewVideo.value.currentTime = (Number(selectedClip.value.source_in_frame || 0) + offset) / fps;
    }
  }
}

function handleClipTrim({ clip, sourceIn, sourceOut }) {
  trimClip(clip, sourceIn, sourceOut);
}

function handleClipSplit({ clip, frame }) {
  splitClip(clip, frame);
}

function splitClipAtCurrentPlayhead() {
  if (!selectedClip.value) return;
  const clip = selectedClip.value;
  let sourceSplitFrame;
  if (playheadFrame.value >= clip.timeline_start_frame && playheadFrame.value <= clip.timeline_end_frame) {
    const offset = playheadFrame.value - clip.timeline_start_frame;
    sourceSplitFrame = clip.source_in_frame + offset;
  } else {
    sourceSplitFrame = Math.round((clip.source_in_frame + clip.source_out_frame) / 2);
  }
  splitClip(clip, sourceSplitFrame);
}

function handleClipReorder({ clip, targetOrder }) {
  reorderClip(clip, targetOrder);
}

function handleSelectTransition(clip) {
  selectedClipName.value = clip.name;
  activeRightTab.value = "shot";
}

function handleTransitionChange(transition) {
  if (!selectedClip.value) return;
  const frames = selectedClip.value.transition_frames || 12;
  setTransition(selectedClip.value, transition, transition === "Cut" ? 0 : frames);
}

function handleTransitionFramesChange(frames) {
  if (!selectedClip.value) return;
  setTransition(selectedClip.value, selectedClip.value.transition_to_next || "Dissolve", frames);
}

async function regenerateSourceForSelectedClip() {
  const shot = selectedClipSourceShot.value;
  if (!shot) return;
  studioMode.value = "scene";
  const idx = allShotsList.value.findIndex(
    (s) => s.name === shot.name || s.shot_number === shot.shot_number
  );
  if (idx >= 0) {
    selectShot(shot, idx);
  }
  await regenerateCurrentShot();
}

async function handleExportTimeline() {
  if (exporting.value || timelineBusy.value) return;
  exporting.value = true;
  try {
    const result = await exportTimeline();
    if (result) {
      toast({
        title: currentLang.value === "vi" ? "Xuất video thành công" : "Timeline exported successfully",
        text: currentLang.value === "vi" ? "Video đã được cập nhật với các chỉnh sửa mới nhất." : "Final video updated with current timeline edits.",
        type: "success",
      });
      await refresh();
    }
  } catch (error) {
    toast({
      title: currentLang.value === "vi" ? "Xuất video thất bại" : "Export failed",
      text: error?.message || "Please try again.",
      type: "error",
    });
  } finally {
    exporting.value = false;
  }
}

async function regenerateCurrentShot() {
  const shot = activeSelectedShot.value;
  if (!shot || !shot.name) return;
  regeneratingSource.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.regenerate_project_shot", {
      project_name: projectName.value,
      shot_name: shot.name,
    });
    toast({ title: "Đang tạo lại cảnh", text: `AI đang kết xuất lại cảnh ${shot.shot_number}.`, type: "success" });
    await refresh();
  } catch (error) {
    toast({ title: "Lỗi tạo lại", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    regeneratingSource.value = false;
  }
}

async function retryFailedScenes() {
  retryingFailedScenes.value = true;
  productionSnapshot.value = null;
  productionSnapshotLoaded.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.retry_project_failed_jobs", {
      project_name: projectName.value,
    });
    toast({ title: "Đang thử lại", text: "Đang xử lý lại các cảnh chưa hoàn thành.", type: "success" });
    await refresh();
  } catch (error) {
    toast({ title: "Lỗi thử lại", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    retryingFailedScenes.value = false;
  }
}

function estimateShotDuration(shot) {
  if (shot?.duration_seconds) return Number(shot.duration_seconds).toFixed(1);
  const count = allShotsList.value.length || 3;
  const total = Number(settingsForm.duration) || 15;
  return (total / count).toFixed(1);
}

async function changeShotDuration(shot, delta) {
  const current = Number(estimateShotDuration(shot));
  const next = Math.max(1, Math.min(60, current + delta));
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.update_project_shot_timing", {
      project_name: projectName.value,
      shot_name: shot.name,
      duration_seconds: next,
    });
    await refresh();
    toast({ title: currentLang.value === "vi" ? "Đã lưu thời lượng" : "Timing saved", text: `${next.toFixed(1)}s`, type: "success" });
  } catch (error) {
    toast({ title: currentLang.value === "vi" ? "Không thể đổi thời lượng" : "Could not change timing", text: error.message || "", type: "error" });
  }
}

function startShotDrag(shot, index, event) {
  draggedShot.value = { shot, index };
  event.dataTransfer.effectAllowed = "move";
}

async function dropShot(targetShot, targetIndex) {
  const dragged = draggedShot.value;
  draggedShot.value = null;
  if (!dragged || dragged.index === targetIndex) return;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.reorder_project_shot", {
      project_name: projectName.value,
      shot_name: dragged.shot.name,
      target_shot_number: targetIndex + 1,
    });
    await refresh();
    toast({ title: currentLang.value === "vi" ? "Đã sắp xếp lại cảnh" : "Shot reordered", type: "success" });
  } catch (error) {
    toast({ title: currentLang.value === "vi" ? "Không thể sắp xếp cảnh" : "Could not reorder shot", text: error.message || "", type: "error" });
  }
}

function quickSelectAspect(format) {
  settingsForm.format = format;
  saveSettings();
}

function getShotFirstFrame(shot, isPlan = false) {
  if (isPlan) {
    const index = Number(shot.first_frame_reference_image_index ?? shot.reference_image_index);
    const asset = index > 0 ? workspace.value?.assets?.[index - 1] : null;
    return { file: asset?.file || null, name: asset?.asset_name || null };
  }
  return { file: shot.reference_image || null, name: shot.reference_asset_name || null };
}

function getShotVideoFile(shot) {
  return shot?.selected_output_file || shot?.output_video || null;
}

// Watch settings updates
watch(settings, (value) => {
  if (!value) return;
  settingsForm.duration = Number(value.duration) || 15;
  settingsForm.format = value.delivery_preset || "Landscape";
  settingsForm.video_style = value.video_style || settingsForm.video_style;
  settingsForm.continuity_mode = value.continuity_mode || "Multi-shot";
}, { immediate: true });

// Production Polling Logic
const ACTIVE_STATUSES = new Set(["Queued", "Running"]);
let pollTimer = null;
const isProductionActive = computed(() => ACTIVE_STATUSES.has(production.value?.status));
const nowTick = ref(Date.now());

const productionElapsedSeconds = computed(() => {
  if (!production.value) return 0;
  const startedAt = production.value.started_at;
  if (!startedAt) return 0;
  const text = String(startedAt).replace(" ", "T");
  const date = new Date(text.endsWith("Z") ? text : `${text}Z`);
  const start = Number.isNaN(date.getTime()) ? nowTick.value : date.getTime();
  return Math.max(0, Math.floor((nowTick.value - start) / 1000));
});

const estimatedFinishLabel = computed(() => {
  const comp = Number(production.value?.completed_jobs || 0);
  const tot = Number(production.value?.total_jobs || 0);
  const rem = tot - comp;
  if (!rem) return "hoàn thành";
  if (!comp || !productionElapsedSeconds.value) return "ước tính...";
  const s = Math.ceil((productionElapsedSeconds.value / comp) * rem);
  return `~${s}s`;
});

onMounted(async () => {
  await loadTimeline(false);
});

watch(() => production.value?.status, async (status, previousStatus) => {
	if (pollTimer) clearInterval(pollTimer);
	pollTimer = null;
	if (ACTIVE_STATUSES.has(status)) {
    pollTimer = setInterval(() => {
      reloadProduction().catch(() => {});
      nowTick.value = Date.now();
    }, 4000);
	} else if (status === "Completed" && previousStatus !== "Completed") {
		await refresh();
		previewSelection.value = "full";
		autoGenerateStep.value = "";
	}
}, { immediate: true });

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
});

async function refresh() {
  plan.value = null;
  await campaign.reload();
  await reloadProduction();
  await loadTimeline(false);
}

async function reloadProduction() {
  const latest = await call("joymedia.joymedia.doctype.media_project.media_project.get_project_production", {
    name: projectName.value,
  });
  // A null response must not erase a completed production already returned
  // by the workspace payload during reload.
  if (latest) {
    productionSnapshot.value = latest;
    productionSnapshotLoaded.value = true;
  }
  return latest;
}

// Use the resource only as the first-render fallback. Once a fresh snapshot
// has been loaded, an older resource response can no longer overwrite it.
watch(() => productionResource.data, (value) => {
  if (!productionSnapshotLoaded.value && value) {
    productionSnapshot.value = value;
    productionSnapshotLoaded.value = true;
  }
}, { immediate: true });

// Avoid showing a stale failed run when the page is opened.
reloadProduction().catch(() => {});

async function openMediaPicker() {
  showMediaPicker.value = true;
  mediaCandidatesLoading.value = true;
  try {
    mediaCandidates.value = await call("joymedia.joymedia.doctype.media_project.media_project.get_project_reference_candidates", {
      media_project: projectName.value,
    });
  } catch (error) {
    mediaCandidates.value = [];
    toast({ title: "Lỗi tải thư viện", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    mediaCandidatesLoading.value = false;
  }
}

async function selectMediaAsset(asset) {
  if (!asset?.name || selectingMedia.value) return;
  selectingMedia.value = true;
  try {
    if ((selectedTarget.value === "keyframe-start" || selectedTarget.value === "keyframe-end") && activeSelectedShot.value) {
      await call("joymedia.joymedia.doctype.media_project.media_project.set_project_shot_keyframe", {
		project_name: projectName.value,
        shot_name: activeSelectedShot.value.name,
        frame_role: selectedTarget.value === "keyframe-start" ? "first_frame" : "last_frame",
        asset_version: asset.asset_version,
      });
      showMediaPicker.value = false;
      await refresh();
      toast({ title: "Đã lưu keyframe", text: `Đã gán ảnh cho Cảnh ${activeSelectedShot.value.shot_number}.`, type: "success" });
      return;
    }
    if (asset.selected) return;
    await call("joymedia.joymedia.doctype.media_project.media_project.select_project_reference", {
      media_project: projectName.value,
      asset_name: asset.name,
    });
    asset.selected = true;
    await refresh();
    toast({ title: "Đã thêm tư liệu", text: "Tư liệu đã được chọn cho dự án.", type: "success" });
  } catch (error) {
    toast({ title: "Lỗi chọn tư liệu", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    selectingMedia.value = false;
  }
}

async function uploadSelectedImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;

  uploadingImages.value = true;
  try {
    for (const file of files) {
      const uploadedFile = await uploadFile(file, { private: true });
      if (!uploadedFile?.file_url) throw new Error("Không thể tải lên file.");
      const created = await call("joymedia.services.media_asset_service.create_media_asset", {
        asset_name: file.name.replace(/\.[^/.]+$/, ""),
        asset_category: uploadCategory.value,
        file_url: uploadedFile.file_url,
      });
      await call("joymedia.joymedia.doctype.media_project.media_project.select_project_reference", {
        media_project: projectName.value,
        asset_name: created.media_asset,
      });
    }
    await refresh();
    toast({ title: "Đã tải ảnh lên", text: `Đã thêm ${files.length} ảnh sản phẩm vào dự án.`, type: "success" });
  } catch (error) {
    toast({ title: "Lỗi tải ảnh", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    uploadingImages.value = false;
  }
}

async function removeProjectAsset(asset) {
  if (!asset?.asset_version) return;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.remove_project_reference", {
      media_project: projectName.value,
      asset_version: asset.asset_version,
    });
    if (selectedAsset.value?.asset_version === asset.asset_version) {
      selectedAsset.value = null;
      selectedTarget.value = "scene";
    }
    await refresh();
    toast({
      title: currentLang.value === "vi" ? "Đã bỏ tư liệu" : "Media removed",
      text: currentLang.value === "vi" ? "Tư liệu vẫn được giữ trong Thư viện Media." : "The asset remains in the Media Library.",
      type: "success",
    });
  } catch (error) {
    toast({
      title: currentLang.value === "vi" ? "Lỗi bỏ tư liệu" : "Unable to remove media",
      text: error.message || "Please try again.",
      type: "error",
    });
  }
}

async function saveSettings() {
  savingSettings.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.save_project_video_settings", {
		project_name: projectName.value,
      total_duration_seconds: settingsForm.duration,
      delivery_preset: settingsForm.format,
      video_style: settingsForm.video_style,
      continuity_mode: settingsForm.continuity_mode,
    });
    showSettings.value = false;
    await refresh();
  } catch (error) {
    toast({ title: "Lỗi lưu cài đặt", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    savingSettings.value = false;
  }
}

function extractFrappeError(error) {
  if (error?.messages?.length) return error.messages.join(" ");
  if (error?._server_messages) {
    try {
      const messages = JSON.parse(error._server_messages);
      const message = messages
        .map((item) => typeof item === "string" ? item : item.message)
        .filter(Boolean)
        .join(" ");
      if (message) return message;
    } catch (parseError) {
      // Fall through to the regular error message.
    }
  }
  return error?.message || (currentLang.value === "vi" ? "Không thể tạo video." : "Video generation failed.");
}

async function handleMagicGenerateClick() {
  if (!hasInputAsset.value) {
    toast({
      title: currentLang.value === "vi" ? "Chưa có tư liệu sản phẩm" : "No product media",
      text: currentLang.value === "vi" ? "Tải ảnh lên hoặc chọn ảnh từ Thư viện Media trước khi tạo video." : "Upload an image or choose one from the Media Library before creating a video.",
      type: "error",
    });
		return;
	}
	if (isAutoGenerating.value || isProductionActive.value) {
		return;
	}
	isAutoGenerating.value = true;
	magicGenerateError.value = "";
  // Remove the previous run from the UI immediately. The next snapshot will
  // contain the newly created run and its real status.
  productionSnapshot.value = null;
	productionSnapshotLoaded.value = true;
	try {
		autoGenerateStep.value = currentLang.value === "vi" ? "Đang chuẩn bị video..." : "Preparing your video...";
		const result = await call("joymedia.joymedia.doctype.media_project.media_project.generate_project_video", {
			project_name: projectName.value,
		});
		productionSnapshot.value = {
			...(productionSnapshot.value || {}),
			name: result?.run || productionSnapshot.value?.name,
			status: result?.status || "Queued",
		};
		productionSnapshotLoaded.value = true;
		autoGenerateStep.value = currentLang.value === "vi" ? "Đang tạo video..." : "Generating your video...";
		await refresh();
    promptInput.value = "";
    toast({
      title: currentLang.value === "vi" ? "Đã bắt đầu tạo video!" : "Video Generation Started!",
      text: currentLang.value === "vi" ? "JoyMedia đang tạo các cảnh video cho bạn." : "JoyMedia is rendering video scenes for you.",
      type: "success"
    });
  } catch (error) {
    const message = extractFrappeError(error);
    magicGenerateError.value = message;
    toast({ title: currentLang.value === "vi" ? "Không thể tạo video" : "Video generation failed", text: message, type: "error" });
  } finally {
    isAutoGenerating.value = false;
    autoGenerateStep.value = "";
  }
}

async function createAnotherVersion() {
  revisingStoryboard.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.revise_project_storyboard", {
		project_name: projectName.value,
      use_current_workflow_defaults: true,
    });
    await refresh();
    toast({ title: "Bản sửa đổi mới", text: "Bạn có thể chỉnh sửa các cảnh và tạo lại video.", type: "success" });
  } catch (error) {
    toast({ title: "Lỗi tạo phiên bản", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    revisingStoryboard.value = false;
  }
}

function goBack() {
  window.location.href = "/joymedia/campaigns";
}
</script>
