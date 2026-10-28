<template>
  <aside
    class="studio-inspector overflow-hidden border-l border-outline-border flex flex-col bg-surface-card select-none z-30"
  >
    <!-- Contextual Inspector Top Header (Derived from Selection) -->
    <div class="p-3 border-b border-outline-border flex items-center justify-between gap-2 bg-surface-muted/60">
      <div class="flex items-center gap-2 min-w-0">
        <span class="text-sm">{{ inspectorHeaderIcon }}</span>
        <h3 class="text-xs font-bold text-ink-primary truncate">{{ inspectorHeaderTitle }}</h3>
      </div>

      <div class="flex items-center gap-1">
        <button
          type="button"
          class="p-1 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Đóng' : 'Close'"
          @click="$emit('update:open', false)"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Inspector Body (Driven purely by selection) -->
    <div class="p-3 overflow-y-auto flex-1 space-y-3">
      <!-- 1. EDIT MODE: Clip Inspector -->
      <template v-if="studioMode === 'edit' && selectedClip">
        <!-- Audio Clip Inspector -->
        <div v-if="selectedClip.track_type === 'Audio'" class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span>🎵</span>
              <span class="truncate max-w-[140px]">{{ selectedClip.source_asset_name || 'Music / Audio' }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-rio-400 font-bold">
              {{ selectedClip.duration_seconds?.toFixed(1) }}s
            </span>
          </div>

          <!-- Start / End / Duration Timing -->
          <div class="grid grid-cols-3 gap-1.5 text-xs">
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'BẮT ĐẦU' : 'START' }}</span>
              <span class="font-mono font-bold text-ink-primary text-xs">{{ formatClipTime(selectedClip.timeline_start_frame, fps) }}</span>
              <span class="block text-[9px] text-ink-muted font-mono">{{ selectedClip.timeline_start_frame }}f</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'KẾT THÚC' : 'END' }}</span>
              <span class="font-mono font-bold text-ink-primary text-xs">{{ formatClipTime(selectedClip.timeline_end_frame, fps) }}</span>
              <span class="block text-[9px] text-ink-muted font-mono">{{ selectedClip.timeline_end_frame }}f</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'THỜI LƯỢNG' : 'DURATION' }}</span>
              <span class="font-mono font-bold text-rio-400 text-xs">{{ ((selectedClip.timeline_end_frame - selectedClip.timeline_start_frame) / (fps || 24)).toFixed(1) }}s</span>
              <span class="block text-[9px] text-ink-muted font-mono">{{ selectedClip.timeline_end_frame - selectedClip.timeline_start_frame }}f</span>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-1.5 text-xs">
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'VIDEO GỐC' : 'SOURCE' }}</span>
              <span class="font-mono font-bold text-ink-primary text-xs">{{ Number(selectedClip.source_duration_seconds || 0).toFixed(1) }}s</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'ĐANG DÙNG' : 'USED' }}</span>
              <span class="font-mono font-bold text-rio-400 text-xs">{{ ((selectedClip.source_out_frame - selectedClip.source_in_frame) / (fps || 24)).toFixed(1) }}s</span>
            </div>
          </div>

          <button
            v-if="selectedClip.audio_role !== 'Source'"
            type="button"
            class="w-full py-1.5 px-2 rounded-xl bg-rio-500/10 hover:bg-rio-500/20 text-rio-400 border border-rio-500/20 text-xs font-semibold cursor-pointer"
            :disabled="timelineBusy"
            @click="$emit(selectedClip.audio_role === 'BGM' ? 'fitAudioClipToFullVideo' : 'fitAudioClipToVideo', selectedClip)"
          >
            {{ currentLang === 'vi' ? (selectedClip.audio_role === 'BGM' ? 'Khớp nhạc với toàn bộ video' : 'Khớp audio với video') : (selectedClip.audio_role === 'BGM' ? 'Fit BGM to Full Video' : 'Fit Audio to Remaining Video') }}
          </button>

          <button
            v-if="selectedClip.audio_role !== 'Source'"
            type="button"
            class="w-full py-1.5 px-2 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-secondary border border-outline-border text-xs font-semibold cursor-pointer"
            :disabled="timelineBusy"
            @click="$emit('useFullAudioSource', selectedClip)"
          >
            {{ currentLang === 'vi' ? 'Dùng toàn bộ audio nguồn' : 'Use Full Source' }}
          </button>

          <!-- Audio Role -->
          <div class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Vai trò âm thanh:' : 'Audio Role:' }}
            </label>
            <select
              :value="selectedClip.audio_role || 'BGM'"
              class="w-full px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer"
              :disabled="timelineBusy || selectedClip.audio_role === 'Source'"
              @change="$emit('updateAudioClip', selectedClip, { audio_role: $event.target.value })"
            >
              <option value="Source">{{ currentLang === 'vi' ? 'Âm thanh gốc' : 'Source audio' }}</option>
              <option value="BGM">{{ currentLang === 'vi' ? 'Nhạc nền' : 'Music' }}</option>
              <option value="Voiceover">{{ currentLang === 'vi' ? 'Lời thoại' : 'Voiceover' }}</option>
              <option value="SFX">{{ currentLang === 'vi' ? 'Hiệu ứng âm thanh' : 'Sound effects' }}</option>
            </select>
          </div>

          <!-- Volume Gain Slider -->
          <div class="space-y-1.5 pt-1">
            <div class="flex items-center justify-between text-[11px] font-semibold text-ink-secondary">
              <span>{{ currentLang === 'vi' ? 'Âm lượng (Gain):' : 'Volume Gain:' }}</span>
              <span class="font-mono font-bold text-rio-400">
                {{ selectedClip.gain_db > 0 ? '+' : '' }}{{ selectedClip.gain_db || 0 }} dB
              </span>
            </div>
            <input
              type="range"
              min="-24"
              max="12"
              step="0.5"
              :value="selectedClip.gain_db || 0"
              class="w-full accent-rio-600 cursor-pointer"
              :disabled="timelineBusy"
              @change="$emit('updateAudioClip', selectedClip, { gain_db: Number($event.target.value) })"
            />
          </div>

          <!-- Duck Others Toggle -->
          <label class="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer pt-1">
            <input
              type="checkbox"
              :checked="Boolean(selectedClip.duck_others)"
              class="rounded text-rio-600 focus:ring-rio-500"
              :disabled="timelineBusy"
              @change="$emit('updateAudioClip', selectedClip, { duck_others: $event.target.checked })"
            />
            <span>{{ currentLang === 'vi' ? 'Giảm âm lượng track khác khi có lời thoại (Ducking)' : 'Lower other audio / Ducking during speech' }}</span>
          </label>

          <!-- Source audio is disabled in place so refresh cannot recreate it. -->
          <div v-if="selectedClip.audio_role === 'Source'" class="pt-2 border-t border-outline-border">
            <button
              type="button"
              class="w-full py-1.5 px-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 text-xs font-semibold cursor-pointer"
              :disabled="timelineBusy"
              @click="$emit('setSourceAudioEnabled', selectedClip, !selectedClip.enabled)"
            >
              {{ selectedClip.enabled ? (currentLang === 'vi' ? 'Xóa audio nguồn' : 'Remove Source Audio') : (currentLang === 'vi' ? 'Khôi phục audio nguồn' : 'Restore Source Audio') }}
            </button>
          </div>

          <!-- Delete Audio Clip -->
          <div class="pt-2 border-t border-outline-border">
            <template v-if="selectedClip.audio_role !== 'Source'">
            <button
              type="button"
              class="w-full mb-1.5 py-1.5 px-2 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-secondary border border-outline-border text-xs font-semibold cursor-pointer"
              :disabled="timelineBusy"
              @click="$emit('setAudioClipEnabled', selectedClip, !selectedClip.enabled)"
            >
              {{ selectedClip.enabled ? (currentLang === 'vi' ? 'Tắt audio clip' : 'Disable Audio Clip') : (currentLang === 'vi' ? 'Bật audio clip' : 'Enable Audio Clip') }}
            </button>
            <button
              type="button"
              class="w-full py-1.5 px-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              @click="$emit('deleteClip', selectedClip)"
            >
              <span>⌫</span>
              <span>{{ currentLang === 'vi' ? 'Xóa audio khỏi timeline' : 'Remove Audio Clip' }}</span>
            </button>
            </template>
          </div>
        </div>

        <!-- Video Clip Inspector -->
        <div v-else class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span>✂️</span>
              <span>{{ `Clip ${selectedClip.clip_order || 1}` }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-rio-400 font-bold">
              {{ selectedClip.duration_seconds?.toFixed(2) }}s
            </span>
          </div>

          <!-- Start / End / Duration Timing -->
          <div class="grid grid-cols-3 gap-1.5 text-xs">
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'BẮT ĐẦU' : 'START' }}</span>
              <span class="font-mono font-bold text-ink-primary text-xs">{{ formatClipTime(selectedClip.source_in_frame, fps) }}</span>
              <span class="block text-[9px] text-ink-muted font-mono">{{ selectedClip.source_in_frame }}f</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'KẾT THÚC' : 'END' }}</span>
              <span class="font-mono font-bold text-ink-primary text-xs">{{ formatClipTime(selectedClip.source_out_frame, fps) }}</span>
              <span class="block text-[9px] text-ink-muted font-mono">{{ selectedClip.source_out_frame }}f</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">{{ currentLang === 'vi' ? 'THỜI LƯỢNG' : 'DURATION' }}</span>
              <span class="font-mono font-bold text-rio-400 text-xs">{{ ((selectedClip.source_out_frame - selectedClip.source_in_frame) / (fps || 24)).toFixed(1) }}s</span>
              <span class="block text-[9px] text-ink-muted font-mono">{{ selectedClip.source_out_frame - selectedClip.source_in_frame }}f</span>
            </div>
          </div>

          <!-- Transition to Next -->
          <div class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Chuyển cảnh (Transition):' : 'Transition to next:' }}
            </label>
            <div class="flex items-center gap-2">
              <select
                :value="selectedClip.transition_to_next || 'Cut'"
                class="flex-1 px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer"
                :disabled="timelineBusy"
                @change="$emit('changeTransition', $event.target.value)"
              >
                <option value="Cut">{{ currentLang === 'vi' ? 'Cắt thẳng' : 'Cut' }}</option>
                <option value="Dissolve">{{ currentLang === 'vi' ? 'Hoà tan' : 'Dissolve' }}</option>
                <option value="Fade">{{ currentLang === 'vi' ? 'Mờ dần' : 'Fade' }}</option>
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

        </div>

        <!-- Source Shot Info & Outdated Sync -->
        <div v-if="selectedClipSourceShot" class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-2.5 text-xs">
          <div class="flex items-center justify-between">
            <span class="font-bold text-ink-primary">🎯 {{ currentLang === 'vi' ? 'Cảnh gốc' : 'Source Shot' }}</span>
            <span class="text-[10px] font-bold text-rio-400 bg-surface-card px-2 py-0.5 rounded border border-outline-border">
              Cảnh {{ selectedClipSourceShot.shot_number }}
            </span>
          </div>

          <div v-if="selectedClipSourceShot.generation_prompt" class="p-2 rounded-xl bg-surface-card border border-outline-border">
            <span class="block text-[10px] font-semibold text-ink-muted mb-0.5">{{ currentLang === 'vi' ? 'MÔ TẢ CHO AI' : 'AI DESCRIPTION' }}</span>
            <p class="text-[11px] text-ink-secondary line-clamp-3 font-mono">{{ selectedClipSourceShot.generation_prompt }}</p>
          </div>

          <!-- Stale source update button -->
          <button
            v-if="selectedClip?.is_outdated"
            type="button"
            class="w-full py-2 px-3 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-colors cursor-pointer"
            :disabled="timelineBusy"
            @click="$emit('updateSourceForSelectedClip')"
          >
            ↻ {{ currentLang === 'vi' ? 'Cập nhật clip từ cảnh mới' : 'Update clip from new shot output' }}
          </button>
          <button
            type="button"
            class="w-full py-2 px-3 rounded-xl bg-rio-600 hover:bg-rio-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-colors cursor-pointer"
            :disabled="timelineBusy || regeneratingSource"
            @click="$emit('regenerateSourceForSelectedClip')"
          >
            <span v-if="regeneratingSource" class="lucide-refresh-cw size-3 animate-spin" />
            <span v-else>↻</span>
            <span>{{ currentLang === 'vi' ? 'Tạo lại cảnh gốc' : 'Regenerate source' }}</span>
          </button>
        </div>
      </template>

      <!-- 2. ASSET SELECTED: Multimodal Asset Inspector -->
      <template v-else-if="selectedTarget === 'asset' && selectedAsset">
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary">📦 {{ currentLang === 'vi' ? 'Chi tiết tư liệu' : 'Asset Details' }}</span>
            <span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-surface-card text-rio-400 border border-outline-border">
              {{ selectedAsset.media_type }}
            </span>
          </div>

          <!-- Multimodal MediaThumbnail Component -->
          <div class="w-full rounded-xl overflow-hidden border border-outline-border">
            <MediaThumbnail
              :src="selectedAsset.file"
              :media-type="selectedAsset.media_type"
              :alt="selectedAsset.asset_name"
              :duration="selectedAsset.duration_seconds"
              aspect="aspect-video"
            />
          </div>

          <div>
            <span class="block text-xs font-bold text-ink-primary">{{ selectedAsset.asset_name }}</span>
            <span class="block text-[11px] text-ink-muted mt-0.5">
              {{ selectedAsset.media_type }} · {{ selectedAsset.asset_category || 'Reference' }}
            </span>
          </div>

          <!-- Explicit Reference Role Selection -->
          <div class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Vai trò trong dự án (Reference Role):' : 'Project Reference Role:' }}
            </label>
            <select
              :value="selectedAsset.reference_role || 'Product'"
              class="w-full px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer focus:outline-none focus:border-rio-500"
              @change="$emit('updateAssetRole', selectedAsset, $event.target.value)"
            >
              <option value="Product">{{ currentLang === 'vi' ? 'Sản phẩm' : 'Product' }}</option>
              <option value="Character">{{ currentLang === 'vi' ? 'Nhân vật (mascot)' : 'Character (mascot)' }}</option>
              <option value="Person">{{ currentLang === 'vi' ? 'Người thật' : 'Person (real face)' }}</option>
              <option value="Logo">Logo</option>
              <option value="Environment">{{ currentLang === 'vi' ? 'Bối cảnh' : 'Place' }}</option>
              <option value="Style">{{ currentLang === 'vi' ? 'Phong cách' : 'Style' }}</option>
              <option value="Motion">{{ currentLang === 'vi' ? 'Chuyển động' : 'Motion' }}</option>
              <option value="Audio">{{ currentLang === 'vi' ? 'Âm thanh' : 'Audio' }}</option>
              <option value="General">{{ currentLang === 'vi' ? 'Chung' : 'General' }}</option>
            </select>
          </div>

          <div v-if="selectedAsset.media_type === 'Video' && selectedAsset.reference_role === 'Motion'" class="space-y-1.5">
            <label class="block text-[11px] font-semibold">{{ currentLang === 'vi' ? 'Video này điều khiển' : 'This video controls' }}</label>
            <select class="w-full rounded-xl border border-outline-border bg-surface-card px-2 py-1 text-xs" :value="selectedAsset.motion_reference_use || 'Camera and actions'" :disabled="isProductionActive" @change="$emit('updateMotionReferenceUse', selectedAsset, $event.target.value)">
              <option value="Camera and actions">{{ currentLang === 'vi' ? 'Máy quay và hành động' : 'Camera and actions' }}</option>
              <option value="Camera only">{{ currentLang === 'vi' ? 'Chỉ máy quay' : 'Camera only' }}</option>
              <option value="Actions only">{{ currentLang === 'vi' ? 'Chỉ hành động' : 'Actions only' }}</option>
            </select>
            <p class="text-[11px] text-ink-muted">{{ currentLang === 'vi' ? 'Tham chiếu nhịp máy quay và bố cục cho quá trình lập kế hoạch.' : 'Reference for camera rhythm and coverage during planning.' }}</p>
            <button v-if="selectedAsset.motion_reference_use !== 'Actions only'" type="button" class="jm-btn-secondary text-xs" :disabled="isProductionActive" @click="$emit('analyzeCameraReference')">
              {{ currentLang === 'vi' ? 'Phân tích máy quay tham chiếu' : 'Analyze reference camera' }}
            </button>
            <p v-if="selectedAsset.analysis_error" class="text-[11px] text-red-600">{{ selectedAsset.analysis_error }}</p>
          </div>

          <div v-if="['Character', 'Person'].includes(selectedAsset.reference_role)" class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Mã nhận diện (gộp các góc nhìn của cùng một nhân vật):' : 'Identity key (group approved views of this character):' }}
            </label>
            <input
              :value="selectedAsset.identity_key || selectedAsset.reference_key || ''"
              pattern="[a-z0-9][a-z0-9_]*"
              class="w-full px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary focus:outline-none focus:border-rio-500"
              @change="$emit('updateAssetIdentity', selectedAsset, $event.target.value)"
            />
          </div>

          <!-- How large a character or product appears next to the others -->
          <div v-if="['Character', 'Person', 'Product'].includes(selectedAsset.reference_role)" class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Kích thước tương đối (1 = bình thường, 0.4 = bé con):' : 'Relative size (1 = normal, 0.4 = a child beside a parent):' }}
            </label>
            <input
              type="number" min="0.1" max="2" step="0.05"
              :value="selectedAsset.relative_size ?? 1"
              data-test="relative-size"
              class="w-24 px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary focus:outline-none focus:border-rio-500"
              @change="$emit('updateAssetSize', selectedAsset, Number($event.target.value))"
            />
          </div>

          <!-- Actions -->
          <div class="pt-2 border-t border-outline-border flex flex-col gap-2">
            <button
              v-if="activeSelectedShot && selectedAsset.media_type === 'Image'"
              type="button"
              class="w-full jm-btn-primary text-xs !py-1.5"
              @click="$emit('applyAssetToShot', selectedAsset, activeSelectedShot)"
            >
              {{ currentLang === 'vi' ? `Gán vào Cảnh ${activeSelectedShot.shot_number}` : `Apply to Shot ${activeSelectedShot.shot_number}` }}
            </button>
            <button
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 text-xs font-semibold transition-colors cursor-pointer"
              @click="$emit('removeAsset', selectedAsset)"
            >
              {{ currentLang === 'vi' ? 'Bỏ tư liệu khỏi dự án' : 'Remove from Project' }}
            </button>
          </div>
        </div>
      </template>

      <!-- 3. KEYFRAME SELECTED: Keyframe Reference Inspector -->
      <template v-else-if="(selectedTarget === 'keyframe-start' || selectedTarget === 'keyframe-end') && activeSelectedShot">
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span class="text-rio-400">◆</span>
              <span>{{ selectedTarget === 'keyframe-start' ? (currentLang === 'vi' ? 'Ảnh bắt đầu' : 'Start Image') : (generationMode === 'Continuous' ? (currentLang === 'vi' ? 'Khung nối tiếp' : 'Continuity Frame') : (currentLang === 'vi' ? 'Ảnh kết thúc' : 'End Image')) }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-rio-400 font-bold">
              {{ selectedTarget === 'keyframe-start' ? formatShotKeyframeTime(selectedShotIndex, 0) : formatShotKeyframeTime(selectedShotIndex, 1) }}
            </span>
          </div>

          <!-- Keyframe Preview Frame -->
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
            <span v-else class="text-xs text-ink-muted font-mono">{{ currentLang === 'vi' ? 'Chưa có ảnh tham chiếu' : 'No reference image' }}</span>
          </div>

          <!-- Actions -->
          <div class="space-y-1.5 pt-1">
            <button
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl border border-outline-border bg-surface-card hover:bg-surface-hover text-ink-primary text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              @click="$emit('openMediaPicker')"
            >
              <span>🖼️</span>
              <span>{{ currentLang === 'vi' ? 'Chọn ảnh từ Thư viện' : 'Choose from Library' }}</span>
            </button>

            <button
              v-if="selectedTarget === 'keyframe-end'"
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              :class="generationMode === 'Continuous' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-outline-border bg-surface-card hover:border-rio-400 text-ink-secondary'"
              @click="$emit('toggleGenerationMode')"
            >
              <span>🔗</span>
              <span>{{ generationMode === 'Continuous' ? (currentLang === 'vi' ? '✓ Đang nối liền cảnh sau' : '✓ Keep continuity between scenes') : (currentLang === 'vi' ? 'Nối khung với Cảnh sau' : 'Independent scenes') }}</span>
            </button>

            <button
              type="button"
              class="w-full jm-btn-secondary text-xs !py-1.5"
              @click="$emit('update:selectedTarget', 'scene')"
            >
              {{ currentLang === 'vi' ? '← Xem thuộc tính Cảnh' : '← Back to Shot' }}
            </button>
          </div>
        </div>
      </template>

      <!-- 4. SHOT SELECTED: Scene details -->
      <template v-else-if="activeSelectedShot">
        <!-- Preview + status -->
        <div class="space-y-2">
          <div class="relative w-full aspect-video rounded-xl overflow-hidden bg-black">
            <MediaThumbnail
              v-if="activeSelectedShot.output_video || shotReferences[0]?.file"
              :src="activeSelectedShot.output_video || shotReferences[shotReferences.length - 1]?.file"
              :media-type="activeSelectedShot.output_video ? 'Video' : 'Image'"
              :alt="sceneLabel"
              :show-play-overlay="false"
              aspect="aspect-video"
            />
            <span
              class="absolute top-2 left-2 px-2 py-0.5 rounded-full text-[10px] font-semibold backdrop-blur"
              :class="shotStatus.class"
            >
              {{ shotStatus.label }}
            </span>
          </div>
          <div class="flex items-center justify-between gap-2">
            <p class="text-[13px] font-semibold text-ink-primary truncate" :title="activeSelectedShot.shot_name">
              {{ activeSelectedShot.shot_name || sceneLabel }}
            </p>
            <div class="flex items-center gap-1 shrink-0" :title="currentLang === 'vi' ? 'Thời lượng cảnh' : 'Scene length'">
              <button
                type="button"
                class="capcut-trim-button"
                :disabled="isProductionActive"
                :title="currentLang === 'vi' ? 'Giảm 0,5 giây' : 'Shorten by 0.5s'"
                @click="$emit('changeShotDuration', activeSelectedShot, -0.5)"
              >
                −
              </button>
              <span class="text-ink-primary font-mono text-xs font-bold min-w-[38px] text-center">
                {{ Number(estimateShotDuration(activeSelectedShot)).toFixed(1) }}s
              </span>
              <button
                type="button"
                class="capcut-trim-button"
                :disabled="isProductionActive"
                :title="currentLang === 'vi' ? 'Tăng 0,5 giây' : 'Lengthen by 0.5s'"
                @click="$emit('changeShotDuration', activeSelectedShot, 0.5)"
              >
                +
              </button>
            </div>
          </div>
        </div>

        <!-- Images this scene is generated from -->
        <div v-if="!usesKeyframes && shotReferences.length" class="space-y-1.5">
          <span class="block text-[11px] font-semibold text-ink-secondary">
            {{ currentLang === 'vi' ? 'Hình ảnh sử dụng' : 'Uses' }}
          </span>
          <div class="grid grid-cols-2 gap-2">
            <div
              v-for="(reference, index) in shotReferences"
              :key="`${reference.asset_version}-${index}`"
              class="rounded-xl border border-outline-border bg-surface-muted overflow-hidden"
            >
              <img :src="reference.file" :alt="reference.label" class="w-full aspect-video object-contain bg-black" />
              <div class="px-2 py-1.5">
                <span class="block text-[11px] font-semibold text-ink-primary truncate">{{ reference.label || `#${index + 1}` }}</span>
                <span class="block text-[10px] text-ink-muted truncate">{{ referenceRoleLabel(reference) }} · &lt;Picture {{ index + 1 }}&gt;</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Start / end images (single-image scenes only) -->
        <div v-else class="space-y-1.5">
          <span class="block text-[11px] font-semibold text-ink-secondary">
            {{ currentLang === 'vi' ? 'Khung hình' : 'Frames' }}
          </span>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <button
              type="button"
              class="p-2 rounded-xl border border-outline-border bg-surface-muted hover:border-rio-400 text-ink-secondary text-center cursor-pointer"
              @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'start')"
            >
              <span class="block text-[11px] font-semibold">{{ currentLang === 'vi' ? 'Ảnh đầu' : 'Start image' }}</span>
              <span class="block text-[10px] text-ink-muted">0.0s</span>
            </button>
            <button
              type="button"
              class="p-2 rounded-xl border border-outline-border bg-surface-muted hover:border-emerald-400 text-ink-secondary text-center cursor-pointer"
              @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'end')"
            >
              <span class="block text-[11px] font-semibold">{{ generationMode === 'Continuous' ? (currentLang === 'vi' ? 'Nối tiếp' : 'Continuity') : (currentLang === 'vi' ? 'Ảnh cuối' : 'End image') }}</span>
              <span class="block text-[10px] text-ink-muted">{{ Number(estimateShotDuration(activeSelectedShot)).toFixed(1) }}s</span>
            </button>
          </div>
        </div>

        <!-- Scene description -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Mô tả cảnh' : 'Scene description' }}
            </label>
            <span class="text-[10px] text-ink-muted">
              {{ currentLang === 'vi' ? 'Dùng cho ảnh Flux và video' : 'Used for Flux images and video' }}
            </span>
          </div>
          <textarea
            v-model="sceneDescriptionDraft"
            :disabled="isProductionActive || savingSceneDescription"
            :placeholder="currentLang === 'vi' ? 'Nhập mô tả cảnh…' : 'Describe this scene…'"
            rows="6"
            class="w-full min-h-32 px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary leading-relaxed focus:outline-none focus:border-rio-500 disabled:opacity-60 resize-y"
            @keydown.ctrl.enter.prevent="saveSceneDescription"
            @keydown.meta.enter.prevent="saveSceneDescription"
          />
          <div class="flex items-center justify-between gap-2">
            <span class="text-[10px] text-ink-muted">
              {{ currentLang === 'vi' ? 'Sửa mô tả rồi lưu trước khi tạo lại. Ctrl/⌘ + Enter để lưu.' : 'Edit the description, then save before regenerating. Ctrl/⌘ + Enter saves.' }}
            </span>
            <button
              type="button"
              class="shrink-0 px-2.5 py-1 rounded-lg bg-surface-card border border-outline-border text-[10px] font-semibold text-ink-secondary hover:text-ink-primary hover:border-rio-400 cursor-pointer disabled:opacity-50"
              :disabled="isProductionActive || savingSceneDescription || !sceneDescriptionChanged"
              @click="saveSceneDescription"
            >
              <span v-if="savingSceneDescription" class="lucide-refresh-cw size-3 animate-spin inline-block" />
              <span v-else>{{ currentLang === 'vi' ? 'Lưu mô tả' : 'Save description' }}</span>
            </button>
          </div>
          <div v-if="!usesKeyframes && shotReferences.length" class="text-[10px] text-ink-muted leading-relaxed">
            <span v-for="(reference, index) in shotReferences" :key="`legend-${index}`" class="mr-2 inline-block">
              &lt;Picture {{ index + 1 }}&gt; = {{ reference.label || referenceRoleLabel(reference) }}
            </span>
          </div>
        </div>

        <!-- Ask AI -->
        <div class="space-y-1.5">
          <button
            type="button"
            class="w-full jm-btn-primary !py-2 text-xs flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
            :disabled="isProductionActive || aiRevisionLoading"
            @click="submitAiRewrite"
          >
            <span v-if="aiRevisionLoading" class="lucide-refresh-cw size-3 animate-spin inline-block" />
            <span v-else>✨ {{ currentLang === 'vi' ? 'AI tinh chỉnh mô tả' : 'AI refine description' }}</span>
          </button>
          <p v-if="!revisionForThisShot" class="text-[10px] text-ink-muted text-center">
            {{ currentLang === 'vi' ? 'Qwen đồng bộ mô tả với ý tưởng video. Bạn xem thay đổi trước khi áp dụng.' : 'Qwen aligns the description with the video idea. You review the change before it is applied.' }}
          </p>

          <!-- The AI's proposed description, with the words it added highlighted. -->
          <div v-if="revisionForThisShot" class="rounded-lg border border-rio-500/40 bg-rio-500/5 p-2.5 space-y-2">
            <p class="text-[10px] font-bold text-rio-400">{{ currentLang === 'vi' ? 'AI đề xuất' : 'AI proposes' }}</p>
            <p v-if="revisionForThisShot.summary" class="text-[10px] text-ink-muted">{{ revisionForThisShot.summary }}</p>
            <p class="text-[11px] leading-relaxed text-ink-primary">
              <template v-for="(seg, i) in revisionSegments" :key="i"><span :class="seg.added ? 'rounded bg-emerald-500/25 text-emerald-300 px-0.5' : ''">{{ seg.text }}</span>{{ i < revisionSegments.length - 1 ? ' ' : '' }}</template>
            </p>
            <div class="flex gap-2 pt-1">
              <button type="button" class="flex-1 jm-btn-primary !py-1.5 text-[11px]" :disabled="aiRevisionLoading" @click="$emit('accept-revision')">✓ {{ currentLang === 'vi' ? 'Áp dụng' : 'Apply' }}</button>
              <button type="button" class="flex-1 rounded-md border border-outline-border py-1.5 text-[11px] text-ink-muted hover:text-ink-primary" :disabled="aiRevisionLoading" @click="$emit('discard-revision')">{{ currentLang === 'vi' ? 'Bỏ qua' : 'Discard' }}</button>
            </div>
          </div>
        </div>

        <!-- Regenerate -->
        <div class="pt-2 border-t border-outline-border space-y-1">
          <button
            type="button"
            class="w-full jm-btn-secondary !py-2 text-xs flex items-center justify-center gap-1.5 cursor-pointer"
            :disabled="isProductionActive"
            @click="$emit('regenerateCurrentShot')"
          >
            <span>↻</span>
            <span>{{ currentLang === 'vi' ? 'Tạo lại cảnh này' : 'Regenerate this scene' }}</span>
          </button>
          <p class="text-[10px] text-ink-muted text-center">
            {{ isProductionActive
              ? (currentLang === 'vi' ? 'Đang tạo video — chờ hoàn tất để chỉnh sửa.' : 'Generation is running — wait for it to finish to edit.')
              : (currentLang === 'vi' ? 'Chỉ tạo lại cảnh này với mô tả hiện tại.' : 'Re-renders only this scene with the current description.') }}
          </p>
        </div>

        <!-- Review: comments on a frame or range of frames, applied to a new take -->
        <SceneReview
          v-if="activeSelectedShot?.output_video"
          :project-name="projectName" :shot="activeSelectedShot" :fps="fps" :busy="busyShots.includes(activeSelectedShot.name)"
          @applied="$emit('reviewChanged', $event)"
        />
      </template>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { diffPromptAdditions } from "../../utils/qwenDiff";
import MediaThumbnail from "../MediaThumbnail.vue";
import SceneReview from "./SceneReview.vue";

const props = defineProps({
  open: { type: Boolean, default: true },
  studioMode: { type: String, default: "scene" },
  selectedTarget: { type: String, default: "scene" },
  selectedAsset: { type: Object, default: null },
  activeSelectedShot: { type: Object, default: null },
  selectedShotIndex: { type: Number, default: 0 },
  selectedShotFrame: { type: Object, default: null },
  selectedClip: { type: Object, default: null },
  selectedClipSourceShot: { type: Object, default: null },
  timelineBusy: { type: Boolean, default: false },
  fps: { type: Number, default: 24 },
  generationMode: { type: String, default: "Multi-shot" },
  currentDuration: { type: [Number, String], default: 15 },
  currentPreset: { type: String, default: "Landscape" },
  regeneratingSource: { type: Boolean, default: false },
  isProductionActive: { type: Boolean, default: false },
  aiRevisionLoading: { type: Boolean, default: false },
  pendingRevision: { type: Object, default: null },
  projectName: { type: String, default: "" },
  busyShots: { type: Array, default: () => [] },
  currentLang: { type: String, default: "en" },
  estimateShotDuration: { type: Function, default: (s) => s?.duration_seconds || 5 },
  formatShotKeyframeTime: { type: Function, default: () => "0.0s" },
});

const emit = defineEmits([
  "accept-revision",
  "discard-revision",
  "update:open",
  "update:selectedTarget",
  "changeTransition",
  "changeTransitionFrames",
  "splitClip",
  "duplicateClip",
  "deleteClip",
  "updateAudioClip",
  "fitAudioClipToVideo",
  "fitAudioClipToFullVideo",
  "useFullAudioSource",
  "setAudioClipEnabled",
  "setSourceAudioEnabled",
  "updateSourceForSelectedClip",
  "regenerateSourceForSelectedClip",
  "applyAssetToShot",
  "removeAsset",
  "updateAssetRole",
  "analyzeCameraReference",
  "updateMotionReferenceUse",
  "updateAssetIdentity",
  "updateAssetSize",
  "selectKeyframeTarget",
  "toggleGenerationMode",
  "changeShotDuration",
  "regenerateCurrentShot",
  "saveSceneDescription",
  "askAi",
  "reviewChanged",
  "openSettings",
  "openMediaPicker",
]);

const sceneDescriptionDraft = ref("");
const savingSceneDescription = ref(false);
const sceneDescriptionChanged = computed(() =>
  sceneDescriptionDraft.value.trim() !== String(props.activeSelectedShot?.generation_prompt || "").trim()
);

function saveSceneDescription() {
  const description = sceneDescriptionDraft.value.trim();
  if (!description || !sceneDescriptionChanged.value || savingSceneDescription.value) return;
  savingSceneDescription.value = true;
  emit("saveSceneDescription", props.activeSelectedShot?.name, description, () => {
    savingSceneDescription.value = false;
  });
}

function submitAiRewrite() {
  const instruction = props.currentLang === "vi"
    ? "Đồng bộ mô tả cảnh này với ý tưởng video chính và hình tham chiếu. Giữ đúng nhân vật, sản phẩm, hành động và bối cảnh; viết một mô tả rõ ràng dùng được cho cả tạo ảnh Flux và tạo video."
    : "Rewrite this shot so it exactly matches the main video brief and selected references. Keep the same character, product, action, and setting, and return one clear description suitable for both Flux image generation and video generation.";
  emit("askAi", instruction);
}

const shotReferences = computed(() => props.activeSelectedShot?.references || []);
// Single-image scenes are driven by start/end frames; reference scenes by <Picture N> images.
const usesKeyframes = computed(
  () => !shotReferences.value.length
    || shotReferences.value.some((reference) => ["first_frame", "last_frame"].includes(reference.input_role))
);
const sceneLabel = computed(() =>
  props.currentLang === "vi" ? `Cảnh ${props.activeSelectedShot?.shot_number}` : `Scene ${props.activeSelectedShot?.shot_number}`
);
const shotStatus = computed(() => {
  if (props.activeSelectedShot?.output_video) {
    return { label: props.currentLang === "vi" ? "Đã tạo" : "Ready", class: "bg-emerald-500/90 text-white" };
  }
  if (props.isProductionActive) {
    return { label: props.currentLang === "vi" ? "Đang tạo…" : "Generating…", class: "bg-rio-500/90 text-white" };
  }
  return { label: props.currentLang === "vi" ? "Chưa tạo" : "Not generated", class: "bg-black/60 text-white" };
});

function referenceRoleLabel(reference) {
  const role = String(reference?.reference_role || "").toLowerCase();
  if (role === "character") return props.currentLang === "vi" ? "Nhân vật" : "Character";
  if (role === "environment") return props.currentLang === "vi" ? "Bối cảnh" : "Location";
  return reference?.reference_role || (props.currentLang === "vi" ? "Tham chiếu" : "Reference");
}

watch(
  () => props.activeSelectedShot?.generation_prompt,
  (prompt) => { sceneDescriptionDraft.value = String(prompt || ""); },
  { immediate: true }
);

function formatClipTime(frames, fps = 24) {
  const safeFps = Number(fps) || 24;
  const totalSeconds = Math.max(0, Number(frames || 0)) / safeFps;
  const mins = Math.floor(totalSeconds / 60);
  const secs = (totalSeconds % 60).toFixed(1);
  return `${String(mins).padStart(2, "0")}:${secs.padStart(4, "0")}`;
}

const inspectorHeaderTitle = computed(() => {
  if (props.studioMode === "edit" && props.selectedClip) {
    if (props.selectedClip.track_type === "Audio") {
      return props.selectedClip.source_asset_name || props.selectedClip.audio_role || (props.currentLang === "vi" ? "Nhạc / Âm thanh" : "Music / Audio");
    }
    return props.selectedClip.shot_number
      ? (props.currentLang === "vi" ? `Clip Cảnh ${props.selectedClip.shot_number}` : `Shot ${props.selectedClip.shot_number} Clip`)
      : `Clip ${props.selectedClip.clip_order || 1}`;
  }
  if (props.selectedTarget === "asset" && props.selectedAsset) {
    return props.selectedAsset.asset_name || "Asset Details";
  }
  if (props.selectedTarget === "keyframe-start") {
    return props.currentLang === "vi" ? "Ảnh bắt đầu" : "Start Image";
  }
  if (props.selectedTarget === "keyframe-end") {
    return props.currentLang === "vi" ? "Ảnh kết thúc" : "End Image";
  }
  if (props.activeSelectedShot) {
    return props.currentLang === "vi" ? `Cảnh ${props.activeSelectedShot.shot_number}` : `Scene ${props.activeSelectedShot.shot_number}`;
  }
  return props.currentLang === "vi" ? "Cài đặt dự án" : "Project Settings";
});

const inspectorHeaderIcon = computed(() => {
  if (props.studioMode === "edit" && props.selectedClip) {
    return props.selectedClip.track_type === "Audio" ? "🎵" : "🎬";
  }
  if (props.selectedTarget === "asset") return "📦";
  if (props.selectedTarget === "keyframe-start" || props.selectedTarget === "keyframe-end") return "◆";
  if (props.activeSelectedShot) return "🎞️";
  return "⚙";
});
// The pending revision belongs to one scene; show it only while that scene is open.
const revisionForThisShot = computed(() =>
  props.pendingRevision && props.activeSelectedShot && props.pendingRevision.shotName === props.activeSelectedShot.name
    ? props.pendingRevision
    : null,
);
const revisionSegments = computed(() =>
  revisionForThisShot.value
    ? diffPromptAdditions(revisionForThisShot.value.original, revisionForThisShot.value.proposed)
    : [],
);

</script>
