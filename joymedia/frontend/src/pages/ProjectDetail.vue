<template>
  <div class="flex-1 flex overflow-hidden w-full h-full min-h-[calc(100vh-52px)] bg-surface-base">
    <!-- Center Stage: Cinema Canvas & Scene Builder -->
    <main class="gflow-center-canvas">
      <!-- Top Studio Control Strip (Inside Canvas View) -->
      <div class="flex items-center justify-between gap-3 mb-4 p-2.5 rounded-2xl bg-surface-card border border-outline-border shadow-xs">
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
          <h2 class="text-xs font-bold text-ink-primary truncate">
            {{ workspace?.campaign?.project_name || "JoyMedia Studio" }}
          </h2>
          <span
            v-if="workspace?.campaign?.status"
            class="text-[10px] px-2 py-0.5 rounded-md font-bold uppercase tracking-wider bg-surface-muted border border-outline-border text-indigo-400"
          >
            {{ workspace.campaign.status }}
          </span>
        </div>

        <!-- Middle: Aspect Ratio & Duration -->
        <div class="flex items-center gap-2">
          <div class="flex items-center bg-surface-muted border border-outline-border rounded-xl p-0.5 text-xs">
            <button
              type="button"
              class="px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer"
              :class="settingsForm.format === 'Landscape' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
              @click="quickSelectAspect('Landscape')"
            >
              16:9
            </button>
            <button
              type="button"
              class="px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer"
              :class="settingsForm.format === 'Portrait' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
              @click="quickSelectAspect('Portrait')"
            >
              9:16
            </button>
            <button
              type="button"
              class="px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer"
              :class="settingsForm.format === 'Square' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
              @click="quickSelectAspect('Square')"
            >
              1:1
            </button>
          </div>

          <span class="text-xs font-mono text-ink-secondary bg-surface-card border border-outline-border px-2.5 py-1 rounded-xl shadow-xs">
            {{ settingsForm.duration }}s
          </span>

          <button
            type="button"
            class="text-xs text-ink-muted hover:text-ink-primary p-1.5 rounded-xl hover:bg-surface-hover border border-transparent hover:border-outline-border transition-colors cursor-pointer"
            title="Cài đặt video"
            @click="showSettings = !showSettings"
          >
            ⚙
          </button>
        </div>

        <!-- Right: Primary Generate Button in Strip -->
        <button
          type="button"
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all cursor-pointer"
          :class="{ 'animate-pulse': isAutoGenerating || isProductionActive }"
          :disabled="isAutoGenerating || (production?.status === 'Running' && !isProductionActive)"
          @click="handleMagicGenerateClick"
        >
          <span v-if="isAutoGenerating" class="lucide-refresh-cw size-3.5 animate-spin" />
          <span v-else class="lucide-sparkles size-3.5" />
          <span>{{ isAutoGenerating ? autoGenerateStep : (isProductionActive ? `${production?.progress || 0}% Đang tạo...` : "🪄 Tạo Video") }}</span>
        </button>
      </div>

      <!-- Cinema Viewport Window -->
      <div class="flex-1 flex flex-col items-center justify-center min-h-[380px] w-full">
        <div
          class="gflow-canvas-viewport w-full"
          :class="{
            'ratio-landscape': settingsForm.format === 'Landscape',
            'ratio-portrait': settingsForm.format === 'Portrait',
            'ratio-square': settingsForm.format === 'Square'
          }"
        >
          <!-- 62% Zoom Badge -->
          <div class="absolute top-3 right-3 z-10 text-[11px] font-mono text-ink-secondary bg-surface-card/90 backdrop-blur-md px-2 py-0.5 rounded-md border border-outline-border shadow-xs">
            62%
          </div>

          <!-- Master Video if Ready -->
          <video
            v-if="finalVideo?.file && (!activeCanvasPreview || activeCanvasPreview.isMaster)"
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
              {{ isAutoGenerating ? autoGenerateStep : "Đang kết xuất video quảng cáo..." }}
            </h3>
            <p class="text-xs text-ink-muted mt-1">
              {{ production?.completed_jobs || 0 }} / {{ production?.total_jobs || expectedShotCount }} cảnh hoàn thành · ETA {{ estimatedFinishLabel }}
            </p>
          </div>

          <!-- Failed Jobs Alert Overlay -->
          <div v-else-if="production?.status === 'Failed' || (production?.failed_jobs > 0 && !isProductionActive)" class="flex flex-col items-center justify-center text-center p-6 space-y-2">
            <span class="size-12 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center text-xl mb-1 border border-rose-500/30">✕</span>
            <h3 class="text-sm font-bold text-ink-primary">Có cảnh quay chưa hoàn thành</h3>
            <p class="text-xs text-ink-muted max-w-sm">{{ production?.error_summary || 'Một số cảnh quay gặp sự cố khi kết xuất.' }}</p>
            <div class="flex items-center gap-2 pt-2">
              <button
                type="button"
                class="px-3.5 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-xs cursor-pointer"
                :disabled="retryingFailedScenes"
                @click="retryFailedScenes"
              >
                {{ retryingFailedScenes ? 'Đang thử lại...' : 'Thử lại cảnh lỗi' }}
              </button>
              <button
                type="button"
                class="px-3.5 py-1.5 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold shadow-xs cursor-pointer"
                @click="createAnotherVersion"
              >
                Tạo bản mới
              </button>
            </div>
          </div>

          <!-- Blank Canvas Placeholder Matching Screenshot -->
          <div v-else class="flex flex-col items-center justify-center text-center p-8 text-ink-muted">
            <span class="size-14 rounded-2xl bg-surface-card border border-outline-border flex items-center justify-center mb-3 text-ink-secondary text-xl shadow-md">
              🖼️
            </span>
            <p class="text-xs text-ink-primary font-medium">{{ currentLang === 'vi' ? 'Khung hiển thị JoyMedia' : 'JoyMedia Viewport' }}</p>
            <p class="text-[11px] text-ink-muted mt-1">{{ currentLang === 'vi' ? 'Tải ảnh sản phẩm hoặc bấm Tạo video bên phải' : 'Upload product image or click Generate video on the right' }}</p>
          </div>
        </div>
      </div>

      <!-- Scene Builder & Timeline Strip -->
      <div class="mt-4 p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs">
        <div class="flex items-center justify-between mb-3 px-1">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold uppercase tracking-wider text-ink-primary">Dòng thời gian các cảnh (Scene Builder)</span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border">
              {{ allShotsList.length }} Cảnh · {{ settingsForm.duration }}s
            </span>
          </div>

          <div class="flex items-center gap-1.5">
            <button
              v-if="!hasStoryboard"
              type="button"
              class="px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-xs transition-colors cursor-pointer"
              :disabled="generatingPlan"
              @click="generatePlan"
            >
              {{ generatingPlan ? t('btn_ai_scripting') : t('btn_ai_script') }}
            </button>
            <button
              v-else
              type="button"
              class="px-3 py-1.5 rounded-xl text-xs font-semibold text-ink-primary bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer"
              @click="createAnotherVersion"
            >
              {{ t('btn_new_version') }}
            </button>
          </div>
        </div>

        <!-- Horizontal Shots Filmstrip with Trimming -->
        <div v-if="allShotsList.length" class="flex items-stretch gap-3 overflow-x-auto py-2">
          <template v-for="(shot, index) in allShotsList" :key="shot.name || shot.shot_number">
            <!-- Shot Tile -->
            <div
              class="relative flex-shrink-0 w-36 p-2 rounded-xl bg-surface-muted border transition-all cursor-pointer select-none"
              :class="isShotSelected(shot, index) ? 'border-indigo-500 bg-surface-active shadow-md ring-1 ring-indigo-500' : 'border-outline-border hover:border-indigo-500/50'"
              @click="selectShot(shot, index)"
            >
              <div class="flex items-center justify-between text-[10px] font-bold text-ink-primary mb-1">
                <span>{{ t('shot_n', { n: shot.shot_number }) }}</span>
                <span class="text-ink-muted font-mono">{{ estimateShotDuration(shot) }}s</span>
              </div>

              <div class="relative w-full aspect-video rounded-lg overflow-hidden bg-black flex items-center justify-center">
                <!-- If this shot has a generated review video, show video preview / play overlay -->
                <template v-if="getShotReview(shot)?.preview_url">
                  <video :src="getShotReview(shot).preview_url" class="w-full h-full object-cover pointer-events-none" preload="metadata" />
                  <div class="absolute inset-0 bg-black/25 flex items-center justify-center pointer-events-none">
                    <span class="size-5 rounded-full bg-white/90 text-indigo-600 flex items-center justify-center text-[10px] shadow font-bold">▶</span>
                  </div>
                </template>
                <img
                  v-else-if="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file"
                  :src="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file"
                  class="w-full h-full object-cover"
                />
                <span v-else class="text-[10px] text-ink-muted">{{ t('shot_n', { n: shot.shot_number }) }}</span>

                <!-- Review Status Indicator -->
                <span
                  v-if="getShotReview(shot)"
                  class="absolute top-1 right-1 size-2 rounded-full ring-1 ring-black"
                  :class="{
                    'bg-emerald-400': getShotReview(shot).status === 'Approved',
                    'bg-amber-400': getShotReview(shot).status === 'Pending',
                    'bg-rose-400': getShotReview(shot).status === 'Rejected'
                  }"
                  :title="`Review: ${getShotReview(shot).status}`"
                />
              </div>

              <p class="text-[10.5px] text-ink-secondary truncate mt-1.5 font-medium" :title="shot.subject || shot.subject_identity">
                {{ shot.subject || shot.subject_identity || t('action_shot') }}
              </p>

              <!-- Trimming controls -->
              <div class="flex items-center justify-between mt-1 pt-1 border-t border-outline-border text-[10px] text-ink-muted font-mono">
                <span>{{ estimateShotDuration(shot) }}s</span>
                <div class="flex items-center gap-1">
                  <button type="button" class="hover:text-ink-primary px-1 font-bold cursor-pointer" :title="t('trim_short_title')" @click.stop="quickTrimShot(shot, -0.5)">-</button>
                  <button type="button" class="hover:text-ink-primary px-1 font-bold cursor-pointer" :title="t('trim_long_title')" @click.stop="quickTrimShot(shot, 0.5)">+</button>
                </div>
              </div>
            </div>

            <!-- Connecting transition node -->
            <div v-if="index < allShotsList.length - 1" class="flex flex-col items-center justify-center shrink-0 text-ink-muted">
              <span class="text-[9px] font-mono mb-0.5">cut</span>
              <span class="lucide-chevron-right size-3 text-ink-muted" />
            </div>
          </template>
        </div>

        <div v-else class="text-center py-6 text-xs text-ink-muted">
          {{ t('no_storyboard_text') }}
        </div>
      </div>

      <!-- Footer Disclaimer -->
      <footer class="mt-4 text-center text-[11px] text-ink-muted">
        {{ t('disclaimer') }}
      </footer>
    </main>

    <!-- Right Panel: Conversational Assistant & Director Panel (Matches Screenshot) -->
    <aside class="gflow-right-panel">
      <!-- Director Header with Segmented Tabs -->
      <div class="gflow-director-header">
        <div class="flex items-center gap-1 p-0.5 rounded-xl bg-surface-muted border border-outline-border text-xs">
          <button
            type="button"
            class="px-2.5 py-1 rounded-lg font-semibold transition-colors flex items-center gap-1 cursor-pointer"
            :class="activeRightTab === 'director' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
            @click="activeRightTab = 'director'"
          >
            <span>{{ t('tab_ai_assistant') }}</span>
          </button>
          <button
            v-if="activeSelectedShot"
            type="button"
            class="px-2.5 py-1 rounded-lg font-semibold transition-colors flex items-center gap-1 cursor-pointer"
            :class="activeRightTab === 'shot' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
            @click="activeRightTab = 'shot'"
          >
            <span>{{ t('tab_shot', { n: activeSelectedShot.shot_number }) }}</span>
            <span
              v-if="activeShotReview"
              class="size-1.5 rounded-full"
              :class="{
                'bg-emerald-400': activeShotReview.status === 'Approved',
                'bg-amber-400': activeShotReview.status === 'Pending',
                'bg-rose-400': activeShotReview.status === 'Rejected'
              }"
            />
          </button>
        </div>

        <div class="flex items-center gap-1 text-ink-muted">
          <button type="button" class="p-1 rounded-lg hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer" title="Cài đặt video" @click="showSettings = true">
            ⚙
          </button>
          <button type="button" class="p-1 rounded-lg hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer" title="Đóng panel" @click="goBack">
            ✕
          </button>
        </div>
      </div>

      <!-- Tab 1: Conversational Director Body (Matches Screenshot) -->
      <div v-if="activeRightTab === 'director'" class="gflow-director-content">
        <!-- Assistant Message Bubble -->
        <div class="gflow-ai-bubble space-y-3">
          <p>
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
              {{ allShotsList.length || 3 }}
            </span>
          </div>
        </div>

        <!-- Clip Preview Card in Conversation Feed -->
        <div class="rounded-2xl overflow-hidden bg-surface-muted border border-outline-border p-2.5">
          <div class="aspect-video rounded-xl overflow-hidden bg-black/60 flex items-center justify-center relative">
            <video
              v-if="finalVideo?.file"
              :src="finalVideo.file"
              class="w-full h-full object-cover"
              controls
            />
            <img
              v-else-if="selectedShotFrame?.file"
              :src="selectedShotFrame.file"
              class="w-full h-full object-cover"
            />
            <div v-else class="text-ink-muted text-xs">Xem trước cảnh quay</div>
          </div>
          <div class="flex items-center justify-between mt-2 px-1 text-[11px] text-ink-muted">
            <span class="font-semibold text-ink-primary truncate">{{ workspace?.campaign?.product_name || "Sản phẩm" }}</span>
            <span class="font-mono text-ink-secondary">{{ settingsForm.duration }}s</span>
          </div>
        </div>
      </div>

      <!-- Tab 2: Shot Specification Inspector (Direct Frappe Data Model) -->
      <div v-else-if="activeSelectedShot" class="gflow-director-content space-y-3">
        <!-- Shot Header & Status -->
        <div class="p-3.5 rounded-2xl bg-surface-muted border border-outline-border space-y-2.5">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-ink-primary">{{ t('shot_n', { n: activeSelectedShot.shot_number }) }}</span>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded-md bg-surface-card text-indigo-400 border border-outline-border">
                {{ estimateShotDuration(activeSelectedShot) }}s
              </span>
            </div>

            <!-- Review or Storyboard Status Badge -->
            <span
              v-if="activeShotReview"
              class="text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider"
              :class="{
                'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30': activeShotReview.status === 'Approved',
                'bg-amber-500/20 text-amber-400 border border-amber-500/30': activeShotReview.status === 'Pending',
                'bg-rose-500/20 text-rose-400 border border-rose-500/30': activeShotReview.status === 'Rejected',
              }"
            >
              {{ activeShotReview.status }}
            </span>
            <span
              v-else
              class="text-[10px] font-bold px-2 py-0.5 rounded bg-surface-card text-ink-muted border border-outline-border uppercase"
            >
              {{ isStoryboardDraft ? t('status_draft') : t('status_locked') }}
            </span>
          </div>

          <!-- Quality Review Decision Actions if review exists -->
          <div v-if="activeShotReview" class="pt-2 border-t border-outline-border space-y-2">
            <p v-if="activeShotReview.notes" class="text-[11px] text-ink-muted italic">
              "{{ activeShotReview.notes }}"
            </p>
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="flex-1 py-1 px-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-colors flex items-center justify-center gap-1"
                :disabled="processingReview"
                @click="approveCurrentShotReview"
              >
                <span>{{ t('btn_approve') }}</span>
              </button>
              <button
                type="button"
                class="flex-1 py-1 px-2 rounded-lg bg-rose-600/80 hover:bg-rose-600 text-white text-xs font-semibold transition-colors flex items-center justify-center gap-1"
                :disabled="processingReview"
                @click="rejectCurrentShotReview"
              >
                <span>{{ t('btn_reject') }}</span>
              </button>
              <button
                type="button"
                class="p-1 px-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-semibold transition-colors"
                :title="t('btn_regenerate')"
                :disabled="processingReview"
                @click="regenerateCurrentShot"
              >
                <span>{{ t('btn_regenerate') }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Shot Specification Fields -->
        <div class="space-y-2.5 text-xs">
          <!-- Reference Keyframe / First Frame Preview -->
          <div v-if="selectedShotFrame?.file || activeSelectedShot.reference_image" class="p-2.5 rounded-2xl bg-surface-muted border border-outline-border space-y-1.5">
            <div class="flex items-center justify-between text-[11px] text-ink-muted">
              <span class="font-semibold text-ink-primary">{{ t('ref_keyframe') }}</span>
              <span class="font-mono text-[10px] text-indigo-400 truncate max-w-[140px]">{{ activeSelectedShot.reference_asset_name || selectedShotFrame?.name || 'Reference' }}</span>
            </div>
            <div class="aspect-video w-full rounded-xl overflow-hidden bg-surface-card border border-outline-border flex items-center justify-center">
              <img :src="selectedShotFrame?.file || activeSelectedShot.reference_image" class="w-full h-full object-cover" />
            </div>
          </div>

          <!-- Last Frame Preview if available (Continuous chained mode) -->
          <div v-if="activeSelectedShot.last_frame_image" class="p-2.5 rounded-2xl bg-surface-muted border border-outline-border space-y-1.5">
            <div class="flex items-center justify-between text-[11px] text-ink-muted">
              <span class="font-semibold text-ink-primary">{{ t('last_frame') }}</span>
              <span class="font-mono text-[10px] text-indigo-400 truncate max-w-[140px]">{{ activeSelectedShot.last_frame_asset_name || 'Last Frame' }}</span>
            </div>
            <div class="aspect-video w-full rounded-xl overflow-hidden bg-surface-card border border-outline-border flex items-center justify-center">
              <img :src="activeSelectedShot.last_frame_image" class="w-full h-full object-cover" />
            </div>
          </div>

          <!-- Subject Identity -->
          <div>
            <label class="block text-ink-secondary text-[11px] font-medium mb-1">{{ t('subject_identity_label') }}</label>
            <input
              v-model="activeSelectedShot.subject_identity"
              :disabled="!isStoryboardDraft"
              class="gflow-field"
              :placeholder="t('subject_placeholder')"
            />
          </div>

          <!-- Action Plot -->
          <div>
            <label class="block text-ink-secondary text-[11px] font-medium mb-1">{{ t('action_plot_label') }}</label>
            <textarea
              v-model="activeSelectedShot.action_plot"
              :disabled="!isStoryboardDraft"
              rows="2"
              class="gflow-field resize-none"
              :placeholder="t('action_placeholder')"
            />
          </div>

          <!-- Camera Direction -->
          <div>
            <label class="block text-ink-secondary text-[11px] font-medium mb-1">{{ t('camera_direction_label') }}</label>
            <input
              v-model="activeSelectedShot.camera_direction"
              :disabled="!isStoryboardDraft"
              class="gflow-field"
              :placeholder="t('camera_placeholder')"
            />
          </div>

          <!-- Environment -->
          <div>
            <label class="block text-ink-secondary text-[11px] font-medium mb-1">{{ t('environment_label') }}</label>
            <input
              v-model="activeSelectedShot.environment"
              :disabled="!isStoryboardDraft"
              class="gflow-field"
              :placeholder="t('environment_placeholder')"
            />
          </div>

          <!-- Audio Direction -->
          <div>
            <label class="block text-ink-secondary text-[11px] font-medium mb-1">{{ t('audio_direction_label') }}</label>
            <input
              v-model="activeSelectedShot.audio_direction"
              :disabled="!isStoryboardDraft"
              class="gflow-field"
              :placeholder="t('audio_placeholder')"
            />
          </div>

          <!-- Compiled AI Prompt (Collapsible inspection) -->
          <div v-if="activeSelectedShot.generation_prompt" class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-[11px] font-semibold text-ink-primary">{{ t('ai_prompt_label') }}</span>
              <button
                type="button"
                class="text-[10px] font-semibold text-indigo-400 hover:text-indigo-300 transition-colors cursor-pointer"
                @click="copyPrompt(activeSelectedShot.generation_prompt)"
              >
                {{ t('btn_copy_prompt') }}
              </button>
            </div>
            <p class="text-[10.5px] text-ink-secondary bg-surface-card p-2.5 rounded-xl border border-outline-border font-mono line-clamp-3 hover:line-clamp-none transition-all leading-relaxed select-text">
              {{ activeSelectedShot.generation_prompt }}
            </p>
          </div>

          <!-- Save Button if Draft -->
          <div v-if="isStoryboardDraft && activeSelectedShot.name" class="pt-2">
            <button
              type="button"
              class="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs transition-colors flex items-center justify-center gap-1.5 shadow-sm shadow-indigo-600/20 cursor-pointer"
              :disabled="savingShot"
              @click="saveActiveShot"
            >
              <span v-if="savingShot" class="lucide-refresh-cw size-3.5 animate-spin" />
              <span>{{ savingShot ? t('btn_saving_shot') : t('btn_save_shot') }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Bottom Input & Action Bar -->
      <div class="gflow-bottom-input-bar">
        <div class="gflow-input-pill">
          <!-- + Upload button -->
          <label class="cursor-pointer text-ink-muted hover:text-ink-primary p-1 transition-colors" title="Tải ảnh sản phẩm">
            <span class="text-base font-bold">+</span>
            <input
              class="file-input-hidden"
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              multiple
              :disabled="uploadingImages"
              @change="uploadSelectedImages"
            />
          </label>

          <!-- Text Prompt Input -->
          <input
            v-model="promptInput"
            type="text"
            :placeholder="currentLang === 'vi' ? 'Bạn muốn tạo video như thế nào?' : 'What kind of video do you want to create?'"
            :disabled="isAutoGenerating || generatingVideo"
            @keydown.enter="handleMagicGenerateClick"
          />

          <!-- Options icon -->
          <button
            type="button"
            class="text-ink-muted hover:text-ink-primary p-1 transition-colors cursor-pointer"
            title="Cài đặt định dạng"
            @click="showSettings = !showSettings"
          >
            <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="4" x2="20" y1="9" y2="9"/>
              <line x1="4" x2="20" y1="15" y2="15"/>
              <circle cx="9" cy="9" r="2"/>
              <circle cx="15" cy="15" r="2"/>
            </svg>
          </button>

          <!-- Action Button (Primary purple/indigo circle with play/stop/magic) -->
          <button
            type="button"
            class="gflow-action-btn"
            :class="{ 'is-active': isAutoGenerating || isProductionActive }"
            :disabled="isAutoGenerating || (production?.status === 'Running' && !isProductionActive)"
            title="Tạo video tự động bằng AI"
            @click="handleMagicGenerateClick"
          >
            <span v-if="isAutoGenerating" class="lucide-refresh-cw size-3.5 animate-spin" />
            <span v-else-if="isProductionActive" class="size-2.5 rounded-xs bg-white" />
            <span v-else class="lucide-sparkles size-3.5" />
          </button>
        </div>
      </div>
    </aside>

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
            <FormControl v-model="settingsForm.duration" type="number" min="3" max="60" />
          </div>
          <div>
            <label class="block text-ink-secondary mb-1 font-semibold">{{ t('settings_aspect_label') }}</label>
            <FormControl v-model="settingsForm.format" type="select" :options="['Landscape', 'Portrait', 'Square']" />
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
const generatingPlan = ref(false);
const applyingPlan = ref(false);
const generatingVideo = ref(false);
const retryingFailedScenes = ref(false);
const revisingStoryboard = ref(false);
const uploadingImages = ref(false);
const selectedShotIndex = ref(0);
const activeCanvasPreview = ref(null);
const promptInput = ref("");

// 1-Click Auto Generation State
const isAutoGenerating = ref(false);
const autoGenerateStep = ref("");

const settingsForm = reactive({ duration: 15, format: "Landscape", video_style: "", continuity_mode: "Multi-shot" });
const workspace = computed(() => campaign.data);
const settings = computed(() => workspace.value?.video_settings);
const production = computed(() => productionResource.data || workspace.value?.production);
const reviews = computed(() => reviewResource.data || workspace.value?.reviews || []);
const finalVideo = computed(() => production.value?.final_video || workspace.value?.final_video);
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
  if (finalVideo.value?.file) {
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

function selectShot(shot, index) {
  selectedShotIndex.value = index;
  activeCanvasPreview.value = null;
  activeRightTab.value = "shot";
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
  settingsForm.duration = value.duration || 15;
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

async function uploadSelectedImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;

  uploadingImages.value = true;
  try {
    for (const file of files) {
      const uploadedFile = await uploadFile(file, { private: true });
      if (!uploadedFile?.file_url) throw new Error("Không thể tải lên file.");
      await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_asset", {
        media_project: projectName.value,
        asset_name: file.name.replace(/\.[^/.]+$/, ""),
        asset_category: "Product",
        file_url: uploadedFile.file_url,
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
  isAutoGenerating.value = true;
  autoGenerateStep.value = "Đang lưu cài đặt...";
  try {
    if (!settings.value) {
      await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", {
        campaign_name: projectName.value,
        total_duration_seconds: settingsForm.duration,
        delivery_preset: settingsForm.format,
        video_style: settingsForm.video_style || (videoStyles.data?.[0]?.workflow_key || ""),
        continuity_mode: settingsForm.continuity_mode,
      });
      await refresh();
    }

    if (!hasStoryboard.value) {
      autoGenerateStep.value = "AI đang soạn kịch bản các cảnh...";
      const generatedPlan = await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video_plan", {
        campaign_name: projectName.value,
      });

      autoGenerateStep.value = "Đang đưa cảnh vào dòng thời gian...";
      await call("joymedia.joymedia.doctype.media_project.media_project.apply_campaign_video_plan", {
        campaign_name: projectName.value,
        plan_json: JSON.stringify(generatedPlan),
      });
      await refresh();
    }

    autoGenerateStep.value = "Khởi chạy AI Video Studio...";
    await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video", {
      campaign_name: projectName.value,
    });
    await refresh();
    promptInput.value = "";
    toast({
      title: currentLang.value === "vi" ? "Đã bắt đầu tạo video!" : "Video Generation Started!",
      text: currentLang.value === "vi" ? "JoyMedia đang tạo các cảnh video cho bạn." : "JoyMedia is rendering video scenes for you.",
      type: "success"
    });
  } catch (error) {
    toast({ title: "Không thể tạo video", text: error.message || "Vui lòng kiểm tra lại thông tin.", type: "error" });
  } finally {
    isAutoGenerating.value = false;
    autoGenerateStep.value = "";
  }
}

async function generatePlan() {
  generatingPlan.value = true;
  try {
    const generatedPlan = await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video_plan", {
      campaign_name: projectName.value,
    });
    await call("joymedia.joymedia.doctype.media_project.media_project.apply_campaign_video_plan", {
      campaign_name: projectName.value,
      plan_json: JSON.stringify(generatedPlan),
    });
    await refresh();
    toast({ title: "Đã tạo kịch bản", text: "Kịch bản các cảnh đã sẵn sàng.", type: "success" });
  } catch (error) {
    toast({ title: "Lỗi kịch bản", text: error.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    generatingPlan.value = false;
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
