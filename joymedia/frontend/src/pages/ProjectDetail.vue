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
            v-if="workspace?.campaign?.status"
            class="text-[10px] px-2 py-0.5 rounded-md font-bold uppercase tracking-wider bg-surface-muted border border-outline-border text-indigo-400"
          >
            {{ workspace.campaign.status === 'Active' ? (currentLang === 'vi' ? 'Đang chạy' : 'Active') : (currentLang === 'vi' ? 'Bản nháp' : 'Draft') }}
          </span>
        </div>

        <!-- Right: Settings Gear & Primary Generate Button -->
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="text-xs text-ink-muted hover:text-ink-primary px-2.5 py-1.5 rounded-xl hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer flex items-center gap-1.5 font-semibold bg-surface-muted shadow-xs"
            :title="currentLang === 'vi' ? 'Cài đặt video (Tỉ lệ, Thời lượng, Phong cách)' : 'Video settings (Aspect, Duration, Style)'"
            @click="showSettings = true"
          >
            <span>⚙</span>
            <span class="text-[11px]">{{ currentLang === 'vi' ? 'Cài đặt' : 'Settings' }}</span>
          </button>

          <button
            type="button"
            class="jm-btn-primary shadow-md shadow-indigo-600/20 !py-1.5 !px-3 text-xs"
            :class="{ 'animate-pulse': isAutoGenerating || isProductionActive }"
            :disabled="!hasInputAsset || isAutoGenerating || (production?.status === 'Running' && !isProductionActive)"
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
            :key="asset.name"
            class="flex items-center gap-2 shrink-0 px-2.5 py-1.5 rounded-lg bg-surface-card border transition-all cursor-pointer"
            :class="selectedTarget === 'asset' && selectedAsset?.name === asset.name ? 'border-indigo-500 ring-2 ring-indigo-500/20' : 'border-outline-border hover:border-indigo-500/40'"
            @click="selectAssetTarget(asset)"
          >
            <img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" class="size-7 rounded object-cover" />
            <div class="min-w-0">
              <span class="block max-w-[120px] truncate text-[11px] text-ink-primary font-medium">{{ asset.asset_name }}</span>
              <span class="block text-[9px] text-ink-muted">{{ asset.asset_category }}</span>
            </div>
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
              {{ currentLang === 'vi' ? 'Trạng thái' : 'Status' }}: {{ production.status }}
            </p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button
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

      <!-- Cinema Viewport Window (Visual Hero: Dominant Center) -->
      <div class="flex-1 flex flex-col items-center justify-center min-h-[440px] w-full">
        <div
          class="gflow-canvas-viewport w-full relative"
          :class="{
            'ratio-landscape': settingsForm.format === 'Landscape',
            'ratio-portrait': settingsForm.format === 'Portrait',
            'ratio-square': settingsForm.format === 'Square'
          }"
        >
          <!-- Floating Scene / Target HUD Chip -->
          <div class="viewport-hud-chip">
            <span class="size-2 rounded-full bg-indigo-500 animate-pulse" />
            <span v-if="selectedTarget === 'asset' && selectedAsset">
              🖼️ {{ selectedAsset.asset_name }} · {{ selectedAsset.asset_category }}
            </span>
            <span v-else-if="selectedTarget === 'keyframe-start' && activeSelectedShot">
              ◆ {{ currentLang === 'vi' ? 'Khung đầu (In)' : 'Start Frame' }} · {{ t('shot_n', { n: activeSelectedShot.shot_number }) }}
            </span>
            <span v-else-if="selectedTarget === 'keyframe-end' && activeSelectedShot">
              ◆ {{ currentLang === 'vi' ? 'Khung cuối (Out)' : 'End Frame' }} · {{ t('shot_n', { n: activeSelectedShot.shot_number }) }}
            </span>
            <span v-else-if="previewSelection === 'full'">
              🎬 {{ currentLang === 'vi' ? 'Toàn bộ video' : 'Full Video' }} · 00:00–{{ formatSecondsLabel(settingsForm.duration) }}
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
            <p v-if="production?.status" class="text-[11px] text-ink-muted">{{ currentLang === 'vi' ? 'Trạng thái' : 'Status' }}: {{ production.status }}</p>
            <div class="flex items-center gap-2 pt-2">
              <button type="button" class="px-3.5 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-xs cursor-pointer" :disabled="retryingFailedScenes" @click="retryFailedScenes">
                {{ retryingFailedScenes ? 'Đang thử lại...' : (currentLang === 'vi' ? 'Thử lại' : 'Retry') }}
              </button>
              <button type="button" class="px-3.5 py-1.5 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold shadow-xs cursor-pointer" @click="refresh">
                {{ currentLang === 'vi' ? 'Làm mới' : 'Refresh' }}
              </button>
            </div>
          </div>

          <!-- Master Video if Ready -->
          <video
            v-else-if="finalVideo?.file && previewSelection === 'full'"
            :key="finalVideo.file"
            :src="finalVideo.file"
            class="w-full h-full object-contain"
            controls
            autoplay
            loop
            preload="metadata"
          />

          <!-- Selected Shot Video Preview -->
          <video
            v-else-if="activeCanvasMedia?.isVideo && activeCanvasMedia?.url"
            :key="activeCanvasMedia.url"
            :src="activeCanvasMedia.url"
            class="w-full h-full object-contain"
            controls
            autoplay
            loop
            preload="metadata"
          />

          <!-- Selected Shot Frame or Image -->
          <img
            v-else-if="activeCanvasMedia?.url"
            :key="activeCanvasMedia.url"
            :src="activeCanvasMedia.url"
            :alt="activeCanvasMedia.title"
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
          <div v-else-if="isProductionActive || isAutoGenerating" class="flex flex-col items-center justify-center text-center p-6">
            <div class="relative size-14 mb-3 flex items-center justify-center">
              <span class="lucide-refresh-cw size-9 animate-spin text-indigo-400" />
              <span class="absolute text-[11px] font-bold font-mono text-ink-primary">{{ production?.progress || 0 }}%</span>
            </div>
            <h3 class="text-sm font-semibold text-ink-primary">
              {{ isAutoGenerating ? autoGenerateStep : (currentLang === 'vi' ? 'Đang kết xuất video quảng cáo...' : 'Rendering video ad...') }}
            </h3>
            <p class="text-xs text-ink-muted mt-1">
              {{ production?.completed_jobs || 0 }} / {{ production?.total_jobs || expectedShotCount }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes completed' }} · ETA {{ estimatedFinishLabel }}
            </p>
          </div>

          <!-- Blank Canvas Placeholder Matching Screenshot -->
          <div v-else class="flex flex-col items-center justify-center text-center p-8 text-ink-muted">
            <span class="size-14 rounded-2xl bg-surface-card border border-outline-border flex items-center justify-center mb-3 text-ink-secondary text-xl shadow-md">
              🖼️
            </span>
            <p class="text-sm text-ink-primary font-semibold">{{ currentLang === 'vi' ? 'Thêm tư liệu sản phẩm để bắt đầu' : 'Add product media to get started' }}</p>
            <p class="text-xs text-ink-muted mt-1">{{ currentLang === 'vi' ? 'Tải ảnh mới hoặc chọn từ Thư viện Media.' : 'Upload a new image or choose one from your Media Library.' }}</p>
            <div class="flex items-center gap-2 mt-4">
              <select v-model="uploadCategory" class="px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer" title="Media category">
                <option v-for="category in inputAssetCategories" :key="category" :value="category">{{ category }}</option>
              </select>
              <label class="jm-btn-primary cursor-pointer text-xs">
                {{ currentLang === 'vi' ? 'Tải ảnh lên' : 'Upload Image' }}
                <input class="file-input-hidden" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple :disabled="uploadingImages" @change="uploadSelectedImages" />
              </label>
              <button type="button" class="jm-btn-secondary text-xs cursor-pointer" @click="openMediaPicker">
                {{ currentLang === 'vi' ? 'Thư viện Media' : 'Media Library' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Attached Playback Controls Bar (Directly Under Preview) -->
        <div class="flex items-center justify-between w-full max-w-[880px] mt-1.5 px-3 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-secondary shadow-xs">
          <div class="flex items-center gap-2.5">
            <button
              type="button"
              class="size-6 rounded-lg bg-surface-muted hover:bg-surface-hover flex items-center justify-center font-bold text-ink-primary transition-colors cursor-pointer"
              :title="isPlaying ? (currentLang === 'vi' ? 'Tạm dừng' : 'Pause') : (currentLang === 'vi' ? 'Phát' : 'Play')"
              @click="togglePlayPause"
            >
              <span>{{ isPlaying ? '⏸' : '▶' }}</span>
            </button>
            <span class="font-mono text-[11px] font-semibold text-ink-primary">
              {{ currentTimelinePositionLabel }} / {{ formatSecondsLabel(totalDurationSeconds) }}
            </span>
            <span class="text-ink-muted text-[10px]">·</span>
            <span v-if="activeSelectedShot" class="text-[11px] text-ink-secondary truncate max-w-[180px]">
              {{ t('shot_n', { n: activeSelectedShot.shot_number }) }} ({{ getShotTimestampRange(activeSelectedShot) }})
            </span>
          </div>

          <!-- Keyframe Quick Navigation & Toggle (CapCut & Premiere Style) -->
          <div class="flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-surface-muted border border-outline-border text-xs">
            <button
              type="button"
              class="size-5 rounded flex items-center justify-center text-[10px] text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
              :title="currentLang === 'vi' ? 'Đến Keyframe trước' : 'Previous Keyframe'"
              @click="jumpToPrevKeyframe"
            >
              ◀
            </button>
            <button
              type="button"
              class="size-5 rounded flex items-center justify-center transition-all cursor-pointer"
              :class="isPlayheadAtKeyframe ? 'text-indigo-400 font-bold scale-110' : 'text-ink-muted hover:text-ink-primary'"
              :title="isPlayheadAtKeyframe ? (currentLang === 'vi' ? 'Keyframe đang kích hoạt (Click để xem cảnh)' : 'Active Keyframe at playhead') : (currentLang === 'vi' ? 'Thêm / Đặt Keyframe tại playhead' : 'Add Keyframe at playhead')"
              @click="toggleKeyframeAtPlayhead"
            >
              <span class="text-xs leading-none">{{ isPlayheadAtKeyframe ? '◆' : '◇' }}</span>
            </button>
            <button
              type="button"
              class="size-5 rounded flex items-center justify-center text-[10px] text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
              :title="currentLang === 'vi' ? 'Đến Keyframe tiếp theo' : 'Next Keyframe'"
              @click="jumpToNextKeyframe"
            >
              ▶
            </button>
          </div>

          <div class="flex items-center gap-1.5">
            <button
              v-if="finalVideo?.file"
              type="button"
              class="px-2 py-0.5 rounded-lg text-[10.5px] font-semibold transition-colors cursor-pointer"
              :class="previewSelection === 'full' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-surface-muted hover:bg-surface-hover text-ink-secondary'"
              @click="selectFullVideo"
            >
              {{ currentLang === 'vi' ? 'Toàn bộ video' : 'Full Video' }}
            </button>
            <button
              v-if="activeSelectedShot"
              type="button"
              class="px-2 py-0.5 rounded-lg text-[10.5px] font-semibold transition-colors cursor-pointer"
              :class="previewSelection === 'shot' && selectedTarget !== 'asset' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-surface-muted hover:bg-surface-hover text-ink-secondary'"
              @click="selectShotTarget(activeSelectedShot, selectedShotIndex)"
            >
              {{ currentLang === 'vi' ? `Cảnh ${activeSelectedShot.shot_number}` : `Shot ${activeSelectedShot.shot_number}` }}
            </button>
          </div>
        </div>
      </div>

      <!-- Scene Builder & CapCut Timeline Architecture -->
      <div class="capcut-timeline-container mt-3">
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
              {{ t('btn_ai_script') }}
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
              @click="selectShotTarget(shot, index)"
            >
              <!-- Clip Header Bar (Scene name & duration) -->
              <div class="flex items-center justify-between text-[11px] font-bold text-ink-primary mb-1">
                <span>{{ t('shot_n', { n: shot.shot_number }) }}</span>
                <span class="text-ink-muted font-mono text-[10px]">{{ estimateShotDuration(shot) }}s</span>
              </div>

              <!-- Clip Visual Thumbnail Body (Clean, CapCut/Premiere style without awkward trim handles) -->
              <div class="relative w-full aspect-video rounded-lg overflow-hidden bg-black flex items-center justify-center group shadow-xs">
                <template v-if="getShotReview(shot)?.preview_url">
                  <video :src="getShotReview(shot).preview_url" class="w-full h-full object-cover pointer-events-none" preload="metadata" />
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
                  <span class="capcut-kf-time-badge">In · 0s</span>
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
                  <span class="capcut-kf-time-badge">Out · {{ estimateShotDuration(shot) }}s</span>
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

      <!-- Footer Disclaimer -->
      <footer class="mt-3 text-center text-[11px] text-ink-muted">
        {{ t('disclaimer') }}
      </footer>
    </main>

    <!-- Right Panel: Clean Separation of Inspector & AI Assistant -->
    <aside class="gflow-right-panel">
      <!-- Panel Header with Clear Tabs (Inspector | AI Assistant) -->
      <div class="gflow-director-header">
        <div class="flex items-center gap-1 p-0.5 rounded-xl bg-surface-muted border border-outline-border text-xs">
          <!-- Tab 1: Inspector -->
          <button
            type="button"
            class="px-3 py-1 rounded-lg font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
            :class="activeRightTab === 'shot' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
            @click="activeRightTab = 'shot'"
          >
            <span>🔍</span>
            <span>Inspector</span>
            <span
              v-if="activeSelectedShot && selectedTarget !== 'asset'"
              class="text-[10.5px] text-indigo-400 font-normal"
            >
              · C{{ activeSelectedShot.shot_number }}
            </span>
            <span
              v-else-if="selectedTarget === 'asset' && selectedAsset"
              class="text-[10.5px] text-indigo-400 font-normal"
            >
              · Tư liệu
            </span>
          </button>

          <!-- Tab 2: AI Assistant (Trợ lý AI) -->
          <button
            type="button"
            class="px-3 py-1 rounded-lg font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
            :class="activeRightTab === 'director' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
            @click="activeRightTab = 'director'"
          >
            <span>✨</span>
            <span>{{ t('tab_ai_assistant') }}</span>
          </button>
        </div>

        <div class="flex items-center gap-1 text-ink-muted">
          <button type="button" class="p-1 rounded-lg hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer" :title="currentLang === 'vi' ? 'Đóng panel' : 'Close panel'" @click="goBack">
            ✕
          </button>
        </div>
      </div>

      <!-- Tab 1 Body: Contextual Inspector (Selection-based Editor Model) -->
      <div v-if="activeRightTab === 'shot'">
        <!-- CASE 1: Clicked an Asset -> Show Asset Inspector -->
        <div v-if="selectedTarget === 'asset' && selectedAsset" class="gflow-director-content space-y-3">
          <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-ink-primary">📦 {{ currentLang === 'vi' ? 'Chi tiết tư liệu' : 'Asset Details' }}</span>
              <span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-surface-card text-indigo-400 border border-outline-border">
                {{ selectedAsset.asset_category }}
              </span>
            </div>
            <div class="aspect-video w-full rounded-xl overflow-hidden bg-black border border-outline-border flex items-center justify-center">
              <img :src="selectedAsset.file" :alt="selectedAsset.asset_name" class="w-full h-full object-contain" />
            </div>
            <div>
              <span class="block text-xs font-bold text-ink-primary">{{ selectedAsset.asset_name }}</span>
              <span class="block text-[11px] text-ink-muted mt-0.5">{{ currentLang === 'vi' ? 'Tư liệu hình ảnh trong bộ sưu tập dự án.' : 'Image asset in project collection.' }}</span>
            </div>
            <div class="pt-2 border-t border-outline-border flex items-center gap-2">
              <button
                v-if="activeSelectedShot"
                type="button"
                class="flex-1 jm-btn-primary text-xs"
                @click="activeSelectedShot.reference_image = selectedAsset.file; activeSelectedShot.reference_asset_name = selectedAsset.asset_name; selectedTarget = 'scene'"
              >
                {{ currentLang === 'vi' ? `Gán vào Cảnh ${activeSelectedShot.shot_number}` : `Apply to Shot ${activeSelectedShot.shot_number}` }}
              </button>
              <button
                type="button"
                class="jm-btn-secondary text-xs"
                @click="selectedTarget = 'scene'"
              >
                {{ currentLang === 'vi' ? 'Xem cảnh' : 'View Shot' }}
              </button>
            </div>
          </div>
        </div>

        <!-- CASE 2: Clicked a Keyframe (Start or End) -> Show Keyframe Inspector -->
        <div v-else-if="(selectedTarget === 'keyframe-start' || selectedTarget === 'keyframe-end') && activeSelectedShot" class="gflow-director-content space-y-3">
          <!-- Miniature Start -> End Keyframe Strip -->
          <div class="p-2 rounded-xl bg-surface-muted border border-outline-border flex items-center justify-between gap-2 text-xs">
            <button
              type="button"
              class="flex-1 p-2 rounded-lg border text-center transition-all cursor-pointer"
              :class="selectedTarget === 'keyframe-start' ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400 font-bold shadow-xs' : 'border-outline-border bg-surface-card hover:border-indigo-400 text-ink-secondary'"
              @click="selectKeyframeTarget(activeSelectedShot, selectedShotIndex, 'start')"
            >
              <span class="block text-[10.5px]">◆ Frame đầu (In)</span>
              <span class="block text-[9.5px] text-ink-muted">0.0s</span>
            </button>
            <span class="text-ink-muted">──→</span>
            <button
              type="button"
              class="flex-1 p-2 rounded-lg border text-center transition-all cursor-pointer"
              :class="selectedTarget === 'keyframe-end' ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400 font-bold shadow-xs' : 'border-outline-border bg-surface-card hover:border-emerald-400 text-ink-secondary'"
              @click="selectKeyframeTarget(activeSelectedShot, selectedShotIndex, 'end')"
            >
              <span class="block text-[10.5px]">◆ Frame cuối (Out)</span>
              <span class="block text-[9.5px] text-ink-muted">{{ estimateShotDuration(activeSelectedShot) }}s</span>
            </button>
          </div>

          <!-- Keyframe Preview & Guide -->
          <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
                <span class="text-indigo-400">◆</span>
                <span>{{ selectedTarget === 'keyframe-start' ? (currentLang === 'vi' ? 'Keyframe Khởi đầu (In)' : 'Start Keyframe (In)') : (currentLang === 'vi' ? 'Keyframe Kết thúc (Out)' : 'End Keyframe (Out)') }}</span>
              </span>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-indigo-400 font-bold">
                {{ selectedTarget === 'keyframe-start' ? formatShotKeyframeTime(selectedShotIndex, 0) : formatShotKeyframeTime(selectedShotIndex, 1) }}
              </span>
            </div>

            <!-- Keyframe Visual Frame -->
            <div class="aspect-video w-full rounded-xl overflow-hidden bg-black border border-outline-border flex items-center justify-center relative group">
              <img
                v-if="selectedTarget === 'keyframe-start' && (selectedShotFrame?.file || activeSelectedShot.reference_image)"
                :src="selectedShotFrame?.file || activeSelectedShot.reference_image"
                class="w-full h-full object-cover"
              />
              <img
                v-else-if="selectedTarget === 'keyframe-end' && activeSelectedShot.last_frame_image"
                :src="activeSelectedShot.last_frame_image"
                class="w-full h-full object-cover"
              />
              <span v-else class="text-xs text-ink-muted font-mono">{{ currentLang === 'vi' ? 'Chưa có ảnh keyframe' : 'No keyframe image' }}</span>

              <div class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
                <button
                  type="button"
                  class="jm-btn-primary text-xs !py-1 !px-2.5"
                  @click="openMediaPicker"
                >
                  {{ currentLang === 'vi' ? 'Đổi ảnh tham chiếu' : 'Change Image' }}
                </button>
              </div>
            </div>

            <!-- Keyframe Operational Actions (CapCut / Google Flow Style) -->
            <div class="space-y-1.5 pt-1">
              <button
                type="button"
                class="w-full py-1.5 px-2.5 rounded-xl border border-outline-border bg-surface-card hover:bg-surface-hover text-ink-primary text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                @click="openMediaPicker"
              >
                <span>🖼️</span>
                <span>{{ currentLang === 'vi' ? 'Chọn ảnh Keyframe từ Thư viện' : 'Choose Keyframe from Library' }}</span>
              </button>

              <button
                v-if="selectedTarget === 'keyframe-end'"
                type="button"
                class="w-full py-1.5 px-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                :class="settingsForm.continuity_mode === 'Continuous' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-outline-border bg-surface-card hover:border-indigo-400 text-ink-secondary'"
                @click="toggleContinuityMode"
              >
                <span>🔗</span>
                <span>{{ settingsForm.continuity_mode === 'Continuous' ? (currentLang === 'vi' ? '✓ Đang nối liền với Cảnh sau' : '✓ Chained to Next Shot') : (currentLang === 'vi' ? 'Nối khung này làm Frame đầu Cảnh sau' : 'Bridge to Next Shot In-Frame') }}</span>
              </button>

              <button
                type="button"
                class="w-full jm-btn-secondary text-xs !py-1.5"
                @click="selectedTarget = 'scene'"
              >
                {{ currentLang === 'vi' ? '← Xem thuộc tính toàn bộ Cảnh' : '← Back to Shot Overview' }}
              </button>
            </div>
          </div>
        </div>

        <!-- CASE 3: Active Scene Inspector (Default) -->
        <div v-else-if="activeSelectedShot" class="gflow-director-content space-y-2.5">
          <!-- Miniature Start -> End Keyframe Strip at the very top -->
          <div class="p-2 rounded-xl bg-surface-muted border border-outline-border flex items-center justify-between gap-2 text-xs">
            <button
              type="button"
              class="flex-1 p-1.5 rounded-lg border text-center transition-all cursor-pointer bg-surface-card hover:border-indigo-400 text-ink-secondary"
              :title="currentLang === 'vi' ? 'Bấm để xem Frame đầu' : 'Preview Start Keyframe'"
              @click="selectKeyframeTarget(activeSelectedShot, selectedShotIndex, 'start')"
            >
              <span class="block text-[10px] font-bold text-indigo-400">◆ Frame đầu (In)</span>
              <span class="block text-[9px] text-ink-muted truncate">0.0s · {{ activeSelectedShot.reference_asset_name || 'Tham chiếu' }}</span>
            </button>
            <span class="text-ink-muted text-xs">──→</span>
            <button
              type="button"
              class="flex-1 p-1.5 rounded-lg border text-center transition-all cursor-pointer bg-surface-card hover:border-emerald-400 text-ink-secondary"
              :title="currentLang === 'vi' ? 'Bấm để xem Frame cuối' : 'Preview End Keyframe'"
              @click="selectKeyframeTarget(activeSelectedShot, selectedShotIndex, 'end')"
            >
              <span class="block text-[10px] font-bold text-emerald-400">◆ Frame cuối (Out)</span>
              <span class="block text-[9px] text-ink-muted truncate">{{ estimateShotDuration(activeSelectedShot) }}s · {{ settingsForm.continuity_mode === 'Continuous' ? 'Nối tiếp' : 'Kết cảnh' }}</span>
            </button>
          </div>

          <!-- Quality Review Decision Actions if review exists -->
          <div v-if="activeShotReview" class="p-2.5 rounded-xl bg-surface-muted border border-outline-border space-y-1.5 text-xs">
            <div class="flex items-center justify-between">
              <span class="font-bold text-ink-primary">{{ t('shot_n', { n: activeSelectedShot.shot_number }) }}</span>
              <span
                class="text-[10px] font-bold px-2 py-0.5 rounded uppercase"
                :class="{
                  'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30': activeShotReview.status === 'Approved',
                  'bg-amber-500/20 text-amber-400 border border-amber-500/30': activeShotReview.status === 'Pending',
                  'bg-rose-500/20 text-rose-400 border border-rose-500/30': activeShotReview.status === 'Rejected',
                }"
              >
                {{ activeShotReview.status === 'Approved' ? (currentLang === 'vi' ? 'Đã duyệt' : 'Approved') : (activeShotReview.status === 'Rejected' ? (currentLang === 'vi' ? 'Từ chối' : 'Rejected') : (currentLang === 'vi' ? 'Chờ duyệt' : 'Pending')) }}
              </span>
            </div>
            <div class="flex items-center gap-1.5 pt-1">
              <button type="button" class="flex-1 py-1 px-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-semibold" :disabled="processingReview" @click="approveCurrentShotReview">{{ t('btn_approve') }}</button>
              <button type="button" class="flex-1 py-1 px-2 rounded-lg bg-rose-600/80 hover:bg-rose-600 text-white text-[11px] font-semibold" :disabled="processingReview" @click="rejectCurrentShotReview">{{ t('btn_reject') }}</button>
              <button type="button" class="p-1 px-2 rounded-lg bg-surface-card hover:bg-surface-hover text-ink-secondary text-[11px] border border-outline-border" :disabled="processingReview" @click="regenerateCurrentShot">{{ t('btn_regenerate') }}</button>
            </div>
          </div>

          <!-- Compact Expandable Sections for Scene Attributes -->
          <div class="space-y-1.5 text-xs">
            <!-- Section 1: Subject -->
            <div class="inspector-accordion">
              <button type="button" class="inspector-accordion-header" @click="toggleAccordion('subject')">
                <span class="flex items-center gap-1.5">
                  <span>👤</span>
                  <span>{{ t('subject_identity_label') }}</span>
                </span>
                <div class="flex items-center gap-1.5">
                  <span v-if="!openAccordion.subject && activeSelectedShot.subject_identity" class="text-[10px] text-ink-muted max-w-[120px] truncate">{{ activeSelectedShot.subject_identity }}</span>
                  <span class="text-[9px]">{{ openAccordion.subject ? '▲' : '▼' }}</span>
                </div>
              </button>
              <div v-if="openAccordion.subject" class="inspector-accordion-body">
                <input v-model="activeSelectedShot.subject_identity" :disabled="!isStoryboardDraft" class="gflow-field" :placeholder="t('subject_placeholder')" />
              </div>
            </div>

            <!-- Section 2: Motion / Action -->
            <div class="inspector-accordion">
              <button type="button" class="inspector-accordion-header" @click="toggleAccordion('motion')">
                <span class="flex items-center gap-1.5">
                  <span>🎬</span>
                  <span>{{ t('action_plot_label') }}</span>
                </span>
                <div class="flex items-center gap-1.5">
                  <span v-if="!openAccordion.motion && activeSelectedShot.action_plot" class="text-[10px] text-ink-muted max-w-[120px] truncate">{{ activeSelectedShot.action_plot }}</span>
                  <span class="text-[9px]">{{ openAccordion.motion ? '▲' : '▼' }}</span>
                </div>
              </button>
              <div v-if="openAccordion.motion" class="inspector-accordion-body">
                <textarea v-model="activeSelectedShot.action_plot" :disabled="!isStoryboardDraft" rows="2" class="gflow-field resize-none" :placeholder="t('action_placeholder')" />
              </div>
            </div>

            <!-- Section 3: Camera & Environment -->
            <div class="inspector-accordion">
              <button type="button" class="inspector-accordion-header" @click="toggleAccordion('camera')">
                <span class="flex items-center gap-1.5">
                  <span>🎥</span>
                  <span>{{ t('camera_direction_label') }} & {{ t('environment_label') }}</span>
                </span>
                <span class="text-[9px]">{{ openAccordion.camera ? '▲' : '▼' }}</span>
              </button>
              <div v-if="openAccordion.camera" class="inspector-accordion-body space-y-2">
                <div>
                  <label class="block text-ink-muted text-[10px] mb-1 font-semibold">{{ t('camera_direction_label') }}</label>
                  <input v-model="activeSelectedShot.camera_direction" :disabled="!isStoryboardDraft" class="gflow-field" :placeholder="t('camera_placeholder')" />
                </div>
                <div>
                  <label class="block text-ink-muted text-[10px] mb-1 font-semibold">{{ t('environment_label') }}</label>
                  <input v-model="activeSelectedShot.environment" :disabled="!isStoryboardDraft" class="gflow-field" :placeholder="t('environment_placeholder')" />
                </div>
              </div>
            </div>

            <!-- Section 4: Audio -->
            <div class="inspector-accordion">
              <button type="button" class="inspector-accordion-header" @click="toggleAccordion('audio')">
                <span class="flex items-center gap-1.5">
                  <span>🎵</span>
                  <span>{{ t('audio_direction_label') }}</span>
                </span>
                <div class="flex items-center gap-1.5">
                  <span v-if="!openAccordion.audio && activeSelectedShot.audio_direction" class="text-[10px] text-ink-muted max-w-[120px] truncate">{{ activeSelectedShot.audio_direction }}</span>
                  <span class="text-[9px]">{{ openAccordion.audio ? '▲' : '▼' }}</span>
                </div>
              </button>
              <div v-if="openAccordion.audio" class="inspector-accordion-body">
                <input v-model="activeSelectedShot.audio_direction" :disabled="!isStoryboardDraft" class="gflow-field" :placeholder="t('audio_placeholder')" />
              </div>
            </div>

            <!-- Section 5: Advanced AI Prompt (Collapsible) -->
            <div v-if="activeSelectedShot.generation_prompt" class="inspector-accordion">
              <button type="button" class="inspector-accordion-header" @click="showAdvancedPrompt = !showAdvancedPrompt">
                <span class="flex items-center gap-1.5">
                  <span>⚙</span>
                  <span>{{ t('ai_prompt_label') }}</span>
                </span>
                <span class="text-[9px]">{{ showAdvancedPrompt ? '▲' : '▼' }}</span>
              </button>
              <div v-if="showAdvancedPrompt" class="inspector-accordion-body space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[10px] text-ink-muted">Raw Generator Prompt</span>
                  <button type="button" class="text-[10px] font-semibold text-indigo-400 hover:text-indigo-300" @click="copyPrompt(activeSelectedShot.generation_prompt)">
                    {{ t('btn_copy_prompt') }}
                  </button>
                </div>
                <p class="text-[10px] text-ink-secondary p-2 rounded-lg bg-surface-muted border border-outline-border font-mono leading-relaxed select-text">
                  {{ activeSelectedShot.generation_prompt }}
                </p>
              </div>
            </div>
          </div>

          <!-- Save Button if Draft -->
          <div v-if="isStoryboardDraft && activeSelectedShot.name" class="pt-1">
            <button type="button" class="w-full jm-btn-primary shadow-xs" :disabled="savingShot" @click="saveActiveShot">
              <span v-if="savingShot" class="lucide-refresh-cw size-3.5 animate-spin" />
              <span>{{ savingShot ? t('btn_saving_shot') : t('btn_save_shot') }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Tab 2 Body: Conversational AI Director -->
      <div v-else class="gflow-director-content">
        <!-- Assistant Message Bubble -->
        <div class="gflow-ai-bubble space-y-3">
          <p class="font-medium">
            {{ t('director_msg_duration', { duration: settingsForm.duration }) }}
          </p>

          <ol class="space-y-2 list-decimal list-inside text-xs text-ink-secondary">
            <li>
              <strong class="text-ink-primary">{{ t('director_step_1') }}</strong>
            </li>
            <li>
              <strong class="text-ink-primary">{{ t('director_step_2') }}</strong>
            </li>
            <li>
              <strong class="text-ink-primary">{{ t('director_step_3') }}</strong>
            </li>
          </ol>

          <p class="text-ink-muted text-xs pt-1">
            {{ t('director_msg_cta', { product: workspace?.campaign?.product_name || t('product_default') }) }}
          </p>

          <!-- Feedback & Shot count pill -->
          <div class="flex items-center justify-between pt-2 border-t border-outline-border text-xs text-ink-muted">
            <div class="flex items-center gap-3">
              <button type="button" class="hover:text-ink-primary cursor-pointer" title="Thích">👍</button>
              <button type="button" class="hover:text-ink-primary cursor-pointer" title="Không thích">👎</button>
              <button type="button" class="hover:text-ink-primary cursor-pointer" title="Báo cáo">⚑</button>
            </div>
            <span class="text-xs font-mono bg-surface-card px-2 py-0.5 rounded-md border border-outline-border text-ink-secondary">
              {{ allShotsList.length || 3 }} {{ currentLang === 'vi' ? 'cảnh' : 'shots' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Bottom Input & Action Bar (Clean Scoped AI Prompt Bar) -->
      <div class="gflow-bottom-input-bar">
        <div class="gflow-input-pill">
          <!-- Text Prompt Input with Scoped Placeholder -->
          <input
            v-model="promptInput"
            type="text"
            class="flex-1 bg-transparent border-none text-xs text-ink-primary focus:outline-none placeholder:text-ink-muted"
            :placeholder="selectedTarget === 'scene' && activeSelectedShot ? (currentLang === 'vi' ? `Hỏi AI chỉnh sửa Cảnh ${activeSelectedShot.shot_number}...` : `Edit Scene ${activeSelectedShot.shot_number} with AI...`) : (currentLang === 'vi' ? 'Hỏi AI chỉnh sửa toàn bộ video...' : 'Edit entire video with AI...')"
            :disabled="isAutoGenerating || generatingVideo"
            @keydown.enter="handleMagicGenerateClick"
          />

          <!-- Action Button -->
          <button
            type="button"
            class="gflow-action-btn"
            :class="{ 'is-active': isAutoGenerating || isProductionActive }"
            :disabled="!hasInputAsset || isAutoGenerating || (production?.status === 'Running' && !isProductionActive)"
            :title="hasInputAsset ? (currentLang === 'vi' ? 'Tạo video tự động bằng AI' : 'Generate video with AI') : (currentLang === 'vi' ? 'Thêm ít nhất một ảnh sản phẩm' : 'Add at least one product image')"
            @click="handleMagicGenerateClick"
          >
            <span v-if="isAutoGenerating" class="lucide-refresh-cw size-3.5 animate-spin" />
            <span v-else-if="isProductionActive" class="size-2.5 rounded-xs bg-white" />
            <span v-else class="lucide-sparkles size-3.5" />
          </button>
        </div>
      </div>
    </aside>

    <!-- Organization media picker for this project -->
    <div v-if="showMediaPicker" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs" @click.self="showMediaPicker = false">
      <div class="w-full max-w-3xl max-h-[80vh] overflow-hidden bg-surface-card border border-outline-border rounded-2xl shadow-2xl flex flex-col">
        <div class="flex items-center justify-between p-4 border-b border-outline-border">
          <div>
            <h3 class="text-sm font-bold text-ink-primary">{{ currentLang === 'vi' ? 'Thêm tư liệu' : 'Add Media' }}</h3>
            <p class="text-xs text-ink-muted mt-1">{{ currentLang === 'vi' ? 'Chọn tư liệu từ thư viện của tổ chức.' : 'Choose media from your organization library.' }}</p>
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
              :disabled="asset.selected || selectingMedia"
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
  </div>
</template>

<script setup>
import { Button, FormControl, call, createResource, toast, upload as uploadFile } from "frappe-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "../stores/i18n";

const { t, currentLang } = useI18n();

const route = useRoute();
const projectName = computed(() => route.params.name);

// Backend Resources
const campaign = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_project_workspace",
  params: { name: projectName.value },
  auto: true,
});
const productionResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_production",
  params: { name: projectName.value },
  auto: true,
});
const reviewResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_reviews",
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
const activeCanvasPreview = ref(null);
const previewSelection = ref("full");
const promptInput = ref("");
const showAdvancedPrompt = ref(false);

// Contextual Selection-Based Editor State
const selectedTarget = ref("scene"); // 'scene' | 'asset' | 'keyframe-start' | 'keyframe-end' | 'full'
const selectedAsset = ref(null);
const assetsExpanded = ref(false);
const isPlaying = ref(false);
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
  const total = Number(settingsForm.duration) || 15;
  const count = list.length || 1;
  const shotDur = total / count;
  const startSec = Math.round(idx * shotDur);
  const endSec = Math.round((idx + 1) * shotDur);
  return `${formatSecondsLabel(startSec)}–${formatSecondsLabel(endSec)}`;
}

function togglePlayPause() {
  isPlaying.value = !isPlaying.value;
  const videoEl = document.querySelector(".gflow-canvas-viewport video");
  if (videoEl) {
    if (isPlaying.value) {
      videoEl.play().catch(() => {});
    } else {
      videoEl.pause();
    }
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
  previewKeyframe(shot, type);
}

// 1-Click Auto Generation State
const isAutoGenerating = ref(false);
const autoGenerateStep = ref("");

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
const production = computed(() => productionResource.data || workspace.value?.production);
const reviews = computed(() => reviewResource.data || workspace.value?.reviews || []);
const finalVideo = computed(() => production.value?.final_video || workspace.value?.final_video);
const projectAssets = computed(() => workspace.value?.assets || []);
const hasInputAsset = computed(() => projectAssets.value.some((asset) => asset.file && asset.media_type === "Image"));

const displayProjectTitle = computed(() => {
  const pName = workspace.value?.campaign?.project_name;
  if (pName && pName.trim() && pName.trim().toLowerCase() !== "untitled") {
    return pName.trim();
  }
  const prodName = workspace.value?.campaign?.product_name;
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
  if (status === "Finalizing" || status === "Ready for Composition") {
    return currentLang.value === "vi" ? "Đang hoàn thiện..." : "Finalizing...";
  }
  if (status === "Completed") {
    return currentLang.value === "vi" ? "✓ Hoàn tất" : "✓ Completed";
  }
  if (status === "Failed" || status === "Partially Completed") {
    return currentLang.value === "vi" ? "Thử lại" : "Retry";
  }
  if (hasStoryboard.value) {
    return currentLang.value === "vi" ? "Tạo video" : "Generate video";
  }
  return currentLang.value === "vi" ? "Tạo tự động 1 chạm" : "1-Click Magic Generate";
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
  const count = allShotsList.value.length || 1;
  const shotDur = total / count;
  const activeIdx = Math.max(0, Math.min(count - 1, selectedShotIndex.value));
  let currentSeconds = (activeIdx + 0.5) * shotDur;
  if (selectedTarget.value === "keyframe-start") {
    currentSeconds = activeIdx * shotDur;
  } else if (selectedTarget.value === "keyframe-end") {
    currentSeconds = (activeIdx + 1) * shotDur;
  }
  return Math.min(100, Math.max(0, (currentSeconds / total) * 100));
});

const currentTimelinePositionLabel = computed(() => {
  const total = totalDurationSeconds.value;
  const count = allShotsList.value.length || 1;
  const shotDur = total / count;
  const activeIdx = Math.max(0, Math.min(count - 1, selectedShotIndex.value));
  let s = Math.round((activeIdx + 0.5) * shotDur);
  if (selectedTarget.value === "keyframe-start") {
    s = Math.round(activeIdx * shotDur);
  } else if (selectedTarget.value === "keyframe-end") {
    s = Math.round((activeIdx + 1) * shotDur);
  }
  return formatSecondsLabel(s);
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
  const total = totalDurationSeconds.value;
  const count = allShotsList.value.length || 1;
  const shotDur = total / count;
  const s = position === 0 ? Math.round(index * shotDur) : Math.round((index + 1) * shotDur);
  return formatSecondsLabel(s);
}

function seekTimelineToPercent(event) {
  const ruler = event.currentTarget;
  if (!ruler) return;
  const rect = ruler.getBoundingClientRect();
  const clickX = event.clientX - rect.left;
  const pct = Math.max(0, Math.min(100, (clickX / rect.width) * 100));

  const count = allShotsList.value.length || 1;
  const clickedShotIndex = Math.min(count - 1, Math.floor((pct / 100) * count));
  const clickedShot = allShotsList.value[clickedShotIndex];
  if (clickedShot) {
    selectShotTarget(clickedShot, clickedShotIndex);
  }
}

const productionError = computed(() => {
  if (!production.value) return "";
  if (production.value.error_summary) return production.value.error_summary;
  const failedJob = (production.value.jobs || []).find(
    (job) => (job.status === "Failed" || job.status === "Partially Completed") && job.error_summary
  );
  if (failedJob?.error_summary) return failedJob.error_summary;
  if (production.value.status === "Failed" || production.value.status === "Partially Completed" || production.value.failed_jobs > 0) {
    return currentLang.value === "vi"
      ? "Một hoặc nhiều cảnh không thể tạo. Vui lòng thử lại."
      : "One or more shots could not be generated. Please retry.";
  }
  return "";
});
const expectedShotCount = computed(() => Number(production.value?.total_jobs || workspace.value?.storyboard?.length || 3));

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
    const rev = getShotReview(activeSelectedShot.value);
    if (rev?.preview_url) {
      return { title: `Cảnh ${activeSelectedShot.value.shot_number}`, url: rev.preview_url, isVideo: true };
    }
    const frame = selectedShotFrame.value;
    if (frame?.file) {
      return { title: `Cảnh ${activeSelectedShot.value.shot_number}`, url: frame.file, isVideo: false };
    }
  }
  return null;
});

const activeRightTab = ref("director");
const savingShot = ref(false);
const processingReview = ref(false);

const isStoryboardDraft = computed(() => {
  return settings.value?.status === "Draft" || !production.value;
});

const activeShotReview = computed(() => {
  if (!activeSelectedShot.value) return null;
  return getShotReview(activeSelectedShot.value);
});

function isShotSelected(shot, index) {
  return selectedShotIndex.value === index;
}

function startProjectNameEdit() {
  projectNameDraft.value = workspace.value?.campaign?.project_name || "";
  editingProjectName.value = true;
}

function cancelProjectNameEdit() {
  editingProjectName.value = false;
  projectNameDraft.value = "";
}

async function saveProjectName() {
  if (!editingProjectName.value) return;
  const nextName = projectNameDraft.value.trim();
  if (!nextName || nextName === workspace.value?.campaign?.project_name) {
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
  const review = getShotReview(shot);
  if (review?.status === "Approved") return "Ready";
  if (review?.status === "Rejected") return "Failed";
  if (review?.status === "Pending") return "Ready";
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
    await call("joymedia.joymedia.doctype.media_project.media_project.update_campaign_shot", {
      campaign_name: projectName.value,
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

async function approveCurrentShotReview() {
  const rev = activeShotReview.value;
  if (!rev) return;
  processingReview.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.approve_campaign_review", {
      campaign_name: projectName.value,
      review_name: rev.name,
    });
    toast({ title: "Đã duyệt cảnh", text: `Cảnh ${activeSelectedShot.value?.shot_number} đã được phê duyệt.`, type: "success" });
    await reviewResource.reload();
  } catch (error) {
    toast({ title: "Lỗi duyệt cảnh", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    processingReview.value = false;
  }
}

async function rejectCurrentShotReview() {
  const rev = activeShotReview.value;
  if (!rev) return;
  processingReview.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.reject_campaign_review", {
      campaign_name: projectName.value,
      review_name: rev.name,
      notes: "Cần cải thiện chất lượng",
    });
    toast({ title: "Đã từ chối cảnh", text: "Bạn có thể bấm Tạo lại cảnh này.", type: "warning" });
    await reviewResource.reload();
  } catch (error) {
    toast({ title: "Lỗi từ chối", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    processingReview.value = false;
  }
}

async function regenerateCurrentShot() {
  const shot = activeSelectedShot.value;
  if (!shot || !shot.name) return;
  processingReview.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.regenerate_campaign_shot", {
      campaign_name: projectName.value,
      shot_name: shot.name,
    });
    toast({ title: "Đang tạo lại cảnh", text: `AI đang kết xuất lại cảnh ${shot.shot_number}.`, type: "success" });
    await refresh();
  } catch (error) {
    toast({ title: "Lỗi tạo lại", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    processingReview.value = false;
  }
}

async function retryFailedScenes() {
  retryingFailedScenes.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.retry_campaign_failed_jobs", {
      campaign_name: projectName.value,
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
  const count = allShotsList.value.length || 3;
  const total = Number(settingsForm.duration) || 15;
  return (total / count).toFixed(1);
}

function quickTrimShot(shot, delta) {
  const cur = Number(settingsForm.duration) || 15;
  const next = Math.max(3, Math.min(60, Math.round(cur + delta)));
  settingsForm.duration = next;
  saveSettings();
  toast({ title: "Đã cắt thời lượng", text: `Tổng thời lượng video là ${next}s.`, type: "success" });
}

function quickSelectAspect(format) {
  settingsForm.format = format;
  saveSettings();
}

function getShotReview(shot) {
  const num = shot.shot_number;
  const revs = reviews.value || [];
  return revs.find((r) => r.shot_number === num || r.shot_name === shot.name);
}

function getShotFirstFrame(shot, isPlan = false) {
  if (isPlan) {
    const index = Number(shot.first_frame_reference_image_index ?? shot.reference_image_index);
    const asset = index > 0 ? workspace.value?.assets?.[index - 1] : null;
    return { file: asset?.file || null, name: asset?.asset_name || null };
  }
  return { file: shot.reference_image || null, name: shot.reference_asset_name || null };
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
const ACTIVE_STATUSES = new Set(["Queued", "Running", "Awaiting Review", "Finalizing", "Ready for Composition"]);
let pollTimer = null;
const isProductionActive = computed(() => ACTIVE_STATUSES.has(production.value?.status));
const nowTick = ref(Date.now());

const productionElapsedSeconds = computed(() => {
  if (!production.value) return 0;
  const startedAt = production.value.started_at || production.value.queued_at;
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

watch(() => production.value?.status, (status) => {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (ACTIVE_STATUSES.has(status)) {
    pollTimer = setInterval(() => {
      productionResource.reload();
      reviewResource.reload();
      nowTick.value = Date.now();
    }, 4000);
  }
}, { immediate: true });

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
});

async function refresh() {
  plan.value = null;
  await campaign.reload();
  await productionResource.reload();
  await reviewResource.reload();
}

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
  if (!asset?.name || asset.selected || selectingMedia.value) return;
  selectingMedia.value = true;
  try {
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
      const created = await call("joymedia.joymedia.doctype.media_project.media_project.create_organization_asset", {
        asset_name: file.name.replace(/\.[^/.]+$/, ""),
        asset_category: uploadCategory.value,
        file_url: uploadedFile.file_url,
      });
      await call("joymedia.joymedia.doctype.media_project.media_project.select_project_reference", {
        media_project: projectName.value,
        asset_name: created.asset?.name || created.asset,
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

async function saveSettings() {
  savingSettings.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", {
      campaign_name: projectName.value,
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

// 1-Click Magic Generate Pipeline for Sellers
async function handleMagicGenerateClick() {
  if (!hasInputAsset.value) {
    toast({
      title: currentLang.value === "vi" ? "Chưa có tư liệu sản phẩm" : "No product media",
      text: currentLang.value === "vi" ? "Tải ảnh lên hoặc chọn ảnh từ Thư viện Media trước khi tạo video." : "Upload an image or choose one from the Media Library before creating a video.",
      type: "error",
    });
    return;
  }
  isAutoGenerating.value = true;
  autoGenerateStep.value = currentLang.value === "vi" ? "Đang chuẩn bị video..." : "Preparing your video...";
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.generate_project_video", {
      project_name: projectName.value,
    });
    autoGenerateStep.value = currentLang.value === "vi" ? "Đang tạo video..." : "Generating video...";
    await refresh();
    promptInput.value = "";
    toast({
      title: currentLang.value === "vi" ? "Đã bắt đầu tạo video!" : "Video Generation Started!",
      text: currentLang.value === "vi" ? "JoyMedia đang tạo các cảnh video cho bạn." : "JoyMedia is rendering video scenes for you.",
      type: "success"
    });
  } catch (error) {
    const message = error?.messages?.join(" ") || error?.message || (currentLang.value === "vi" ? "Không thể tạo video." : "Video generation failed.");
    toast({ title: currentLang.value === "vi" ? "Không thể tạo video" : "Video generation failed", text: message, type: "error" });
  } finally {
    isAutoGenerating.value = false;
    autoGenerateStep.value = "";
  }
}

async function createAnotherVersion() {
  revisingStoryboard.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.revise_campaign_storyboard", {
      campaign_name: projectName.value,
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
