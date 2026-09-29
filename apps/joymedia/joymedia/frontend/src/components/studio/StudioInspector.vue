<template>
  <aside class="w-full xl:w-[380px] shrink-0 border-t xl:border-t-0 xl:border-l border-outline-border flex flex-col bg-surface-ground">
    <!-- Inspector Top Navigation Bar (Matching Left Tab System) -->
    <div class="p-3 border-b border-outline-border flex items-center justify-between gap-2 bg-surface-card">
      <div class="flex items-center gap-1 bg-surface-muted p-1 rounded-xl text-xs border border-outline-border">
        <!-- Tab 1: Context Inspector (Chi tiết) -->
        <button
          type="button"
          class="px-3 py-1 rounded-lg font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
          :class="activeRightTab === 'shot' ? 'bg-surface-card text-ink-primary font-bold shadow-xs' : 'text-ink-muted hover:text-ink-primary'"
          @click="activeRightTab = 'shot'"
        >
          <span>🎯</span>
          <span>{{ t('tab_shot_details') }}</span>
          <span
            v-if="studioMode === 'edit' && selectedClip"
            class="text-[10.5px] text-indigo-400 font-normal"
          >
            · Clip {{ selectedClip.clip_order || 1 }}
          </span>
          <span
            v-else-if="activeSelectedShot && selectedTarget !== 'asset'"
            class="text-[10.5px] text-indigo-400 font-normal"
          >
            · C{{ activeSelectedShot.shot_number }}
          </span>
          <span
            v-else-if="selectedTarget === 'asset' && selectedAsset"
            class="text-[10.5px] text-indigo-400 font-normal"
          >
            · {{ currentLang === 'vi' ? 'Tư liệu' : 'Asset' }}
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
        <button
          type="button"
          class="p-1 rounded-lg hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Quay lại' : 'Go back'"
          @click="$emit('goBack')"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Tab 1 Body: Contextual Inspector (Selection-based Editor Model) -->
    <div v-if="activeRightTab === 'shot'" class="p-3 overflow-y-auto flex-1">
      <!-- CASE EDIT MODE: Clip Inspector -->
      <div v-if="studioMode === 'edit' && selectedClip" class="gflow-director-content space-y-3">
        <!-- Clip Details Card -->
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span>✂️</span>
              <span>{{ `Clip ${selectedClip.clip_order || 1}` }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-indigo-400 font-bold">
              {{ selectedClip.duration_seconds?.toFixed(2) }}s · {{ selectedClip.duration_frames }}f
            </span>
          </div>

          <!-- IN / OUT / Duration -->
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">IN FRAME</span>
              <span class="font-mono font-bold text-ink-primary text-sm">{{ selectedClip.source_in_frame }}</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">OUT FRAME</span>
              <span class="font-mono font-bold text-ink-primary text-sm">{{ selectedClip.source_out_frame }}</span>
            </div>
          </div>

          <!-- Transition to Next -->
          <div class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Chuyển cảnh kế tiếp (Transition)' : 'Transition to next' }}
            </label>
            <div class="flex items-center gap-2">
              <select
                :value="selectedClip.transition_to_next || 'Cut'"
                class="flex-1 px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer"
                :disabled="timelineBusy"
                @change="$emit('changeTransition', $event.target.value)"
              >
                <option value="Cut">Cut (Cắt thẳng)</option>
                <option value="Dissolve">Dissolve (Hòa tan)</option>
                <option value="Fade">Fade (Mờ dần)</option>
              </select>
              <input
                v-if="selectedClip.transition_to_next && selectedClip.transition_to_next !== 'Cut'"
                type="number"
                min="4"
                max="48"
                :value="selectedClip.transition_frames || 12"
                class="w-16 px-2 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary font-mono text-center"
                :title="currentLang === 'vi' ? 'Số khung hình chuyển tiếp' : 'Transition frames'"
                :disabled="timelineBusy"
                @change="$emit('changeTransitionFrames', Number($event.target.value))"
              />
            </div>
          </div>

          <!-- Clip Editorial Actions: Split, Duplicate, Delete -->
          <div class="grid grid-cols-3 gap-1.5 pt-2 border-t border-outline-border">
            <button
              type="button"
              class="py-1.5 px-2 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              :title="currentLang === 'vi' ? 'Tách clip tại playhead' : 'Split clip at playhead'"
              @click="$emit('splitClip')"
            >
              <span>✂</span>
              <span>{{ currentLang === 'vi' ? 'Tách' : 'Split' }}</span>
            </button>
            <button
              type="button"
              class="py-1.5 px-2 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              :title="currentLang === 'vi' ? 'Nhân đôi clip này' : 'Duplicate clip'"
              @click="$emit('duplicateClip', selectedClip)"
            >
              <span>⧉</span>
              <span>{{ currentLang === 'vi' ? 'Nhân đôi' : 'Duplicate' }}</span>
            </button>
            <button
              type="button"
              class="py-1.5 px-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              :title="currentLang === 'vi' ? 'Xóa clip khỏi timeline' : 'Delete clip'"
              @click="$emit('deleteClip', selectedClip)"
            >
              <span>⌫</span>
              <span>{{ currentLang === 'vi' ? 'Xóa' : 'Delete' }}</span>
            </button>
          </div>
        </div>

        <!-- Source Shot Reference & Regeneration Section -->
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-2.5 text-xs">
          <div class="flex items-center justify-between">
            <span class="font-bold text-ink-primary flex items-center gap-1.5">
              <span>🎯</span>
              <span>{{ currentLang === 'vi' ? 'Cảnh gốc (Source Shot)' : 'Source Shot' }}</span>
            </span>
            <span v-if="selectedClipSourceShot" class="text-[10px] font-bold text-indigo-400 bg-surface-card px-2 py-0.5 rounded border border-outline-border">
              {{ t('shot_n', { n: selectedClipSourceShot.shot_number }) }}
            </span>
          </div>

          <div v-if="selectedClipSourceShot" class="space-y-2">
            <div v-if="selectedClipSourceShot.subject_identity || selectedClipSourceShot.action_plot" class="p-2 rounded-xl bg-surface-card border border-outline-border space-y-1">
              <p v-if="selectedClipSourceShot.subject_identity" class="text-[11px] text-ink-secondary">
                <span class="font-semibold text-ink-muted">{{ currentLang === 'vi' ? 'Chủ thể:' : 'Subject:' }}</span> {{ selectedClipSourceShot.subject_identity }}
              </p>
              <p v-if="selectedClipSourceShot.action_plot" class="text-[11px] text-ink-secondary">
                <span class="font-semibold text-ink-muted">{{ currentLang === 'vi' ? 'Hành động:' : 'Action:' }}</span> {{ selectedClipSourceShot.action_plot }}
              </p>
            </div>

            <!-- Generation Prompt Excerpt -->
            <div v-if="selectedClipSourceShot.generation_prompt" class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] font-semibold text-ink-muted mb-0.5">PROMPT</span>
              <p class="text-[11px] text-ink-secondary line-clamp-3 font-mono">{{ selectedClipSourceShot.generation_prompt }}</p>
            </div>

            <!-- Regenerate Source Button -->
            <button
              type="button"
              class="w-full py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-colors cursor-pointer"
              :disabled="timelineBusy || processingReview"
              @click="$emit('regenerateSourceForSelectedClip')"
            >
              <span v-if="processingReview" class="lucide-refresh-cw size-3 animate-spin" />
              <span v-else>↻</span>
              <span>{{ currentLang === 'vi' ? 'Tạo lại cảnh gốc (Regenerate source)' : 'Regenerate source' }}</span>
            </button>
            <p class="text-[10px] text-ink-muted text-center">
              {{ currentLang === 'vi' ? 'Tạo lại cảnh sẽ tự động đồng bộ video mới vào timeline clip.' : 'Regenerating will sync newly rendered video into this timeline clip.' }}
            </p>
          </div>
          <div v-else class="text-ink-muted text-center py-2 text-xs">
            {{ currentLang === 'vi' ? 'Không tìm thấy thông tin cảnh gốc.' : 'Source shot information not found.' }}
          </div>
        </div>
      </div>

      <!-- CASE 1: Clicked an Asset -> Show Asset Inspector (Scene Mode) -->
      <div v-else-if="selectedTarget === 'asset' && selectedAsset" class="gflow-director-content space-y-3">
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
              @click="$emit('applyAssetToShot', selectedAsset, activeSelectedShot)"
            >
              {{ currentLang === 'vi' ? `Gán vào Cảnh ${activeSelectedShot.shot_number}` : `Apply to Shot ${activeSelectedShot.shot_number}` }}
            </button>
            <button
              type="button"
              class="jm-btn-secondary text-xs"
              @click="$emit('update:selectedTarget', 'scene')"
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
            @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'start')"
          >
            <span class="block text-[10.5px]">◆ {{ currentLang === 'vi' ? 'Frame đầu (In)' : 'Start Frame' }}</span>
            <span class="block text-[9.5px] text-ink-muted">0.0s</span>
          </button>
          <span class="text-ink-muted">──→</span>
          <button
            type="button"
            class="flex-1 p-2 rounded-lg border text-center transition-all cursor-pointer"
            :class="selectedTarget === 'keyframe-end' ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400 font-bold shadow-xs' : 'border-outline-border bg-surface-card hover:border-emerald-400 text-ink-secondary'"
            @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'end')"
          >
            <span class="block text-[10.5px]">◆ {{ currentLang === 'vi' ? 'Frame cuối (Out)' : 'End Frame' }}</span>
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
                @click="$emit('openMediaPicker')"
              >
                {{ currentLang === 'vi' ? 'Đổi ảnh tham chiếu' : 'Change Image' }}
              </button>
            </div>
          </div>

          <!-- Keyframe Operational Actions -->
          <div class="space-y-1.5 pt-1">
            <button
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl border border-outline-border bg-surface-card hover:bg-surface-hover text-ink-primary text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              @click="$emit('openMediaPicker')"
            >
              <span>🖼️</span>
              <span>{{ currentLang === 'vi' ? 'Chọn ảnh Keyframe từ Thư viện' : 'Choose Keyframe from Library' }}</span>
            </button>

            <button
              v-if="selectedTarget === 'keyframe-end'"
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              :class="continuityMode === 'Continuous' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-outline-border bg-surface-card hover:border-indigo-400 text-ink-secondary'"
              @click="$emit('toggleContinuityMode')"
            >
              <span>🔗</span>
              <span>{{ continuityMode === 'Continuous' ? (currentLang === 'vi' ? '✓ Đang nối liền với Cảnh sau' : '✓ Chained to Next Shot') : (currentLang === 'vi' ? 'Nối khung này làm Frame đầu Cảnh sau' : 'Bridge to Next Shot In-Frame') }}</span>
            </button>

            <button
              type="button"
              class="w-full jm-btn-secondary text-xs !py-1.5"
              @click="$emit('update:selectedTarget', 'scene')"
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
            @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'start')"
          >
            <span class="block text-[10px] font-bold text-indigo-400">◆ Frame đầu (In)</span>
            <span class="block text-[9px] text-ink-muted truncate">0.0s · {{ activeSelectedShot.reference_asset_name || (currentLang === 'vi' ? 'Tham chiếu' : 'Reference') }}</span>
          </button>
          <span class="text-ink-muted text-xs">──→</span>
          <button
            type="button"
            class="flex-1 p-1.5 rounded-lg border text-center transition-all cursor-pointer bg-surface-card hover:border-emerald-400 text-ink-secondary"
            :title="currentLang === 'vi' ? 'Bấm để xem Frame cuối' : 'Preview End Keyframe'"
            @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'end')"
          >
            <span class="block text-[10px] font-bold text-emerald-400">◆ Frame cuối (Out)</span>
            <span class="block text-[9px] text-ink-muted truncate">{{ estimateShotDuration(activeSelectedShot) }}s · {{ continuityMode === 'Continuous' ? (currentLang === 'vi' ? 'Nối tiếp' : 'Continuous') : (currentLang === 'vi' ? 'Kết cảnh' : 'Cut') }}</span>
          </button>
        </div>

        <!-- Persistent NLE-style shot trim control -->
        <div class="p-2.5 rounded-xl bg-surface-muted border border-outline-border">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-[11px] font-semibold text-ink-secondary">{{ currentLang === 'vi' ? 'Thời lượng cảnh' : 'Shot duration' }}</span>
            <span class="font-mono text-[11px] text-indigo-400 font-bold">{{ estimateShotDuration(activeSelectedShot) }}s</span>
          </div>
          <input
            type="range"
            min="1"
            max="60"
            step="0.5"
            :value="Number(estimateShotDuration(activeSelectedShot))"
            class="w-full accent-indigo-500 cursor-pointer"
            :title="currentLang === 'vi' ? 'Kéo để cắt hoặc kéo dài cảnh' : 'Drag to trim or extend this shot'"
            @change="$emit('changeShotDuration', activeSelectedShot, Number($event.target.value) - Number(estimateShotDuration(activeSelectedShot)))"
          />
          <div class="flex justify-between text-[9px] text-ink-muted font-mono"><span>01s</span><span>60s</span></div>
        </div>

        <div class="p-2.5 rounded-xl bg-surface-muted border border-outline-border space-y-1.5 text-xs">
          <div class="flex items-center justify-between">
            <span class="font-bold text-ink-primary">{{ t('shot_n', { n: activeSelectedShot.shot_number }) }}</span>
            <span
              class="text-[10px] font-bold px-2 py-0.5 rounded uppercase"
              :class="getShotVideoFile(activeSelectedShot) ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-surface-card text-ink-muted border border-outline-border'"
            >
              {{ getShotVideoFile(activeSelectedShot) ? (currentLang === 'vi' ? 'Đã tạo video' : 'Generated') : (currentLang === 'vi' ? 'Bản nháp' : 'Draft') }}
            </span>
          </div>
          <div class="flex items-center gap-1.5 pt-1">
            <button
              type="button"
              class="flex-1 py-1 px-2.5 rounded-lg bg-surface-card hover:bg-surface-hover text-ink-primary text-[11px] font-semibold border border-outline-border flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="processingReview || isProductionActive"
              @click="$emit('regenerateCurrentShot')"
            >
              <span v-if="processingReview" class="lucide-refresh-cw size-3 animate-spin" />
              <span v-else>↻</span>
              <span>{{ t('btn_regenerate') }}</span>
            </button>
          </div>
        </div>

        <!-- Accordions for Scene Attributes -->
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

          <!-- Section 5: Advanced AI Prompt -->
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
                <button type="button" class="text-[10px] font-semibold text-indigo-400 hover:text-indigo-300" @click="$emit('copyPrompt', activeSelectedShot.generation_prompt)">
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
          <button type="button" class="w-full jm-btn-primary shadow-xs" :disabled="savingShot" @click="$emit('saveActiveShot')">
            <span v-if="savingShot" class="lucide-refresh-cw size-3.5 animate-spin" />
            <span>{{ savingShot ? t('btn_saving_shot') : t('btn_save_shot') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Tab 2 Body: Conversational AI Director -->
    <div v-else class="p-3 overflow-y-auto flex-1">
      <div class="gflow-director-content">
        <div class="gflow-ai-bubble space-y-3">
          <p class="font-medium">
            {{ t('director_msg_duration', { duration: durationSeconds }) }}
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
            {{ t('director_msg_cta', { product: productName || t('product_default') }) }}
          </p>

          <!-- Feedback & Shot count pill -->
          <div class="flex items-center justify-between pt-2 border-t border-outline-border text-xs text-ink-muted">
            <div class="flex items-center gap-3">
              <button type="button" class="hover:text-ink-primary cursor-pointer" title="Thích">👍</button>
              <button type="button" class="hover:text-ink-primary cursor-pointer" title="Không thích">👎</button>
              <button type="button" class="hover:text-ink-primary cursor-pointer" title="Báo cáo">⚑</button>
            </div>
            <span class="text-xs font-mono bg-surface-card px-2 py-0.5 rounded-md border border-outline-border text-ink-secondary">
              {{ hasStoryboard ? expectedShotCount : (currentLang === 'vi' ? `Dự kiến: ${expectedShotCount}` : `Planned: ${expectedShotCount}`) }}
              {{ hasStoryboard ? (currentLang === 'vi' ? 'cảnh đã tạo' : 'shots created') : (currentLang === 'vi' ? 'cảnh' : 'shots') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Input & Action Bar (Clean Scoped AI Prompt Bar) -->
    <div class="gflow-bottom-input-bar p-3 border-t border-outline-border bg-surface-card">
      <div class="gflow-input-pill flex items-center gap-2 p-1.5 rounded-xl bg-surface-muted border border-outline-border">
        <input
          :value="promptInput"
          type="text"
          class="flex-1 bg-transparent border-none text-xs text-ink-primary focus:outline-none placeholder:text-ink-muted px-2"
          :placeholder="selectedTarget === 'scene' && activeSelectedShot ? (currentLang === 'vi' ? `Hỏi AI chỉnh sửa Cảnh ${activeSelectedShot.shot_number}...` : `Edit Scene ${activeSelectedShot.shot_number} with AI...`) : (currentLang === 'vi' ? 'Hỏi AI chỉnh sửa toàn bộ video...' : 'Edit entire video with AI...')"
          :disabled="isAutoGenerating || isProductionActive"
          @input="$emit('update:promptInput', $event.target.value)"
          @keydown.enter="$emit('magicGenerate')"
        />

        <button
          type="button"
          class="gflow-action-btn size-7 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center cursor-pointer transition-colors shadow-xs"
          :class="{ 'is-active': isAutoGenerating || isProductionActive }"
          :disabled="!hasInputAsset || isAutoGenerating || isProductionActive"
          :title="hasInputAsset ? (currentLang === 'vi' ? 'Tạo video tự động bằng AI' : 'Generate video with AI') : (currentLang === 'vi' ? 'Thêm ít nhất một ảnh sản phẩm' : 'Add at least one product image')"
          @click="$emit('magicGenerate')"
        >
          <span v-if="isAutoGenerating" class="lucide-refresh-cw size-3.5 animate-spin" />
          <span v-else-if="isProductionActive" class="size-2.5 rounded-xs bg-white" />
          <span v-else class="lucide-sparkles size-3.5" />
        </button>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { useI18n } from "../../stores/i18n";

const { t } = useI18n();

const localTab = ref("shot");
const activeRightTab = computed({
  get: () => props.activeTab || localTab.value,
  set: (val) => {
    localTab.value = val;
    emit("update:activeTab", val);
  },
});
const showAdvancedPrompt = ref(false);

const openAccordion = reactive({
  subject: false,
  motion: false,
  camera: false,
  audio: false,
});

function toggleAccordion(key) {
  openAccordion[key] = !openAccordion[key];
}

const props = defineProps({
  activeTab: { type: String, default: "shot" },
  studioMode: { type: String, default: "scene" },
  selectedClip: { type: Object, default: null },
  selectedClipSourceShot: { type: Object, default: null },
  timelineBusy: { type: Boolean, default: false },
  selectedTarget: { type: String, default: "scene" },
  selectedAsset: { type: Object, default: null },
  activeSelectedShot: { type: Object, default: null },
  selectedShotFrame: { type: Object, default: null },
  selectedShotIndex: { type: Number, default: 0 },
  continuityMode: { type: String, default: "Multi-shot" },
  currentLang: { type: String, default: "vi" },
  processingReview: { type: Boolean, default: false },
  isProductionActive: { type: Boolean, default: false },
  isStoryboardDraft: { type: Boolean, default: true },
  savingShot: { type: Boolean, default: false },
  durationSeconds: { type: Number, default: 15 },
  productName: { type: String, default: "" },
  hasStoryboard: { type: Boolean, default: false },
  expectedShotCount: { type: Number, default: 0 },
  promptInput: { type: String, default: "" },
  isAutoGenerating: { type: Boolean, default: false },
  hasInputAsset: { type: Boolean, default: false },
  estimateShotDuration: { type: Function, default: (shot) => shot?.duration_seconds || 4 },
  formatShotKeyframeTime: { type: Function, default: () => "0.0s" },
  getShotVideoFile: { type: Function, default: () => null },
});

const emit = defineEmits([
  "update:activeTab",
  "goBack",
  "changeTransition",
  "changeTransitionFrames",
  "splitClip",
  "duplicateClip",
  "deleteClip",
  "regenerateSourceForSelectedClip",
  "applyAssetToShot",
  "update:selectedTarget",
  "selectKeyframeTarget",
  "openMediaPicker",
  "toggleContinuityMode",
  "changeShotDuration",
  "regenerateCurrentShot",
  "copyPrompt",
  "saveActiveShot",
  "update:promptInput",
  "magicGenerate",
]);
</script>

<style scoped>
.inspector-accordion {
  border-radius: 12px;
  background: var(--surface-muted, #1e293b);
  border: 1px solid var(--outline-border, #334155);
  overflow: hidden;
}

.inspector-accordion-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-secondary, #cbd5e1);
  background: transparent;
  cursor: pointer;
  transition: background 0.15s ease;
}

.inspector-accordion-header:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--ink-primary, #ffffff);
}

.inspector-accordion-body {
  padding: 8px 10px;
  border-top: 1px solid var(--outline-border, #334155);
}

.gflow-field {
  width: 100%;
  padding: 6px 8px;
  border-radius: 8px;
  background: var(--surface-card, #0f172a);
  border: 1px solid var(--outline-border, #334155);
  font-size: 11px;
  color: var(--ink-primary, #ffffff);
}

.gflow-field:focus {
  outline: none;
  border-color: #6366f1;
}
</style>
