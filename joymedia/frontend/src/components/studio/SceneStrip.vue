<template>
  <div class="scene-strip-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <!-- Storyboard Header -->
    <div class="flex items-center justify-between mb-2.5 px-1 flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>🎞️</span>
          <span>{{ currentLang === 'vi' ? 'Storyboard Phân cảnh' : 'Storyboard' }}</span>
        </span>
        <span v-if="syncError" class="text-rose-400 truncate">
          {{ syncError }}
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ totalDurationSeconds }}s
        </span>
        <!-- First frames: every scene's opening picture is drawn and approved before its video is made -->
        <template v-if="frames.needed.value.length">
          <Badge
            data-test="frames-approved"
            :theme="frames.allApproved.value ? 'green' : 'orange'"
            :label="frames.allApproved.value ? tr('All first frames approved', 'Đã duyệt hết khung hình đầu')
              : tr(`${frames.approvedCount.value}/${frames.needed.value.length} first frames approved`, `Đã duyệt ${frames.approvedCount.value}/${frames.needed.value.length} khung hình đầu`)"
          />
          <Button
            size="sm" variant="subtle" :loading="frames.drawingAll.value" :disabled="!storyboardApproved" data-test="draw-all-frames"
            @click="frames.draw()"
          >
            {{ tr('Draw all first frames', 'Vẽ tất cả khung hình đầu') }}
          </Button>
          <span v-if="!storyboardApproved" class="text-[10px] text-amber-500" data-test="approve-first">
            {{ tr('Approve the storyboard first (the button above the scenes).', 'Hãy duyệt kịch bản trước (nút phía trên các cảnh).') }}
          </span>
        </template>
      </div>

      <!-- A sheet's storyboard is changed by editing the sheet; a creative one by asking the AI -->
      <p v-if="hasStoryboard && fromSheet" class="max-w-[360px] text-right text-[10px] text-ink-muted" data-test="follows-sheet">
        {{ tr('The scenes follow your sheet. To change them, edit the sheet and import it again.', 'Các cảnh theo đúng file kịch bản. Muốn sửa, hãy sửa file rồi nhập lại.') }}
      </p>
      <div v-else-if="hasStoryboard" class="flex flex-col items-end gap-1">
        <form class="flex items-center gap-1.5" @submit.prevent="submitAiRevision">
          <div class="relative flex items-center">
            <span class="absolute left-2.5 text-xs text-indigo-400">✨</span>
            <input
              v-model="aiRevisionInput"
              type="text"
              :placeholder="currentLang === 'vi' ? 'Nhờ AI sửa kịch bản... (vd: thêm một cảnh cận sản phẩm)' : 'Ask the AI to change the storyboard... (e.g. add a product close-up)'"
              :aria-label="currentLang === 'vi' ? 'Yêu cầu AI chỉnh sửa storyboard' : 'Ask AI to revise the storyboard'"
              class="bg-surface-muted border border-outline-border focus:border-indigo-500 rounded-xl pl-7 pr-3 py-1 text-xs text-ink-primary placeholder:text-ink-muted w-48 sm:w-72 focus:outline-none transition-all"
              :disabled="isRevising || isGenerating"
            />
          </div>
          <button
            type="submit"
            class="px-3 py-1 rounded-xl text-xs font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition-all cursor-pointer shadow-xs disabled:opacity-50"
            :disabled="isRevising || isGenerating || !aiRevisionInput.trim()"
          >
            <span v-if="isRevising" class="lucide-refresh-cw size-3 animate-spin inline-block" />
            <span v-else>{{ currentLang === 'vi' ? 'Cập nhật cảnh' : 'Update scenes' }}</span>
          </button>
        </form>
        <p v-if="revisionError" class="max-w-[360px] text-right text-[10px] text-rose-400">
          {{ revisionError }}
        </p>
        <p v-else class="max-w-[360px] text-right text-[10px] text-ink-muted">
          {{ isRevising
            ? (currentLang === 'vi' ? 'AI đang cập nhật storyboard…' : 'AI is updating the storyboard…')
            : (currentLang === 'vi' ? 'Chỉ cập nhật phân cảnh; bấm Tạo bản mới để render.' : 'Updates scenes only; generate a new version to render.') }}
        </p>
      </div>
    </div>

    <!-- Active Clean Generation Progress (Only when generating - Shots oriented) -->
    <div
      v-if="isGenerating"
      class="mb-3 p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-between gap-3 text-xs"
    >
      <div class="flex items-center gap-2 min-w-0">
        <span class="lucide-refresh-cw size-3.5 text-indigo-400 animate-spin shrink-0" />
        <span class="font-bold text-ink-primary">
          {{ currentLang === 'vi' ? 'Đang tạo video:' : 'Generating video:' }}
        </span>
        <span v-if="shots.length || expectedShotCount" class="text-indigo-400 font-mono font-semibold">
          {{ completedShotsCount }} / {{ shots.length || expectedShotCount }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes ready' }}
        </span>
        <span v-else class="text-indigo-400 font-mono font-semibold">
          {{ currentLang === 'vi' ? 'Đang lập storyboard…' : 'Planning storyboard…' }}
        </span>
      </div>

      <!-- Shot Progress Indicators -->
      <div v-if="shots.length || expectedShotCount" class="flex items-center gap-1.5 overflow-x-auto">
        <span
          v-for="(shot, idx) in (shots.length ? shots : expectedShotCount)"
          :key="idx"
          class="text-[10px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0"
          :class="getShotBadgeClass(shot, idx)"
        >
          <span>{{ getShotStatusGlyph(shot, idx) }}</span>
          <span>S{{ idx + 1 }}</span>
        </span>
      </div>
    </div>

    <!-- Storyboard panels, as on a drawn storyboard: each scene's first frame, then what happens in plain words -->
    <div v-if="shots.length" class="grid gap-3 pb-2" :style="{ gridTemplateColumns: `repeat(auto-fill, minmax(${portrait ? 170 : 240}px, 1fr))` }" data-test="storyboard-grid">
      <template v-for="(shot, index) in shots" :key="shot.name || shot.shot_number || index">
        <div
          class="relative rounded-2xl border p-2 transition-all cursor-pointer bg-surface-muted select-none flex flex-col"
          :class="[
            selectedShotIndex === index && selectedTarget !== 'asset'
              ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/30'
              : 'border-outline-border hover:border-indigo-400'
          ]"
          draggable="true"
          data-test="storyboard-panel"
          @dragstart="onDragStart(shot, index, $event)"
          @dragover.prevent
          @drop.prevent="onDrop(shot, index)"
          @click="$emit('selectShot', shot, index)"
        >
          <!-- The first frame; clicking it plays the scene's video in place -->
          <div class="relative w-full rounded-xl overflow-hidden bg-black flex items-center justify-center mb-2" :class="portrait ? 'aspect-[9/16]' : 'aspect-video'">
            <video
              v-if="playing === shot.name && getShotVideoFile(shot)"
              :src="getShotVideoFile(shot)" :poster="panelImage(shot)" class="size-full object-contain" controls autoplay playsinline
              data-test="panel-video" @click.stop @ended="playing = ''"
            />
            <template v-else>
              <img v-if="panelImage(shot)" :src="panelImage(shot)" :alt="tr(`Scene ${shot.shot_number}`, `Cảnh ${shot.shot_number}`)" class="size-full object-cover" loading="lazy" />
              <span v-else class="text-[11px] text-zinc-400 px-2 text-center">{{ tr('No first frame yet', 'Chưa có khung hình đầu') }}</span>
              <button
                v-if="getShotVideoFile(shot)"
                type="button" data-test="panel-play"
                class="absolute inset-0 z-20 flex items-center justify-center cursor-pointer"
                :aria-label="tr(`Play scene ${shot.shot_number}`, `Phát cảnh ${shot.shot_number}`)"
                @click.stop="playing = shot.name"
              >
                <span class="size-10 rounded-full bg-white/90 flex items-center justify-center text-indigo-600 shadow-md hover:scale-110 transition-transform">
                  <svg class="size-4 fill-current ml-0.5" viewBox="0 0 24 24" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3" /></svg>
                </span>
              </button>
            </template>
            <span class="absolute left-1.5 top-1.5 z-10 rounded-md bg-black/65 px-1.5 py-0.5 text-[10px] font-bold text-white">
              {{ shot.shot_number }}
            </span>

            <!-- A new take is rendering; the current one stays visible underneath -->
            <div v-if="isRegenerating(shot)" class="absolute inset-0 z-30 bg-black/55 flex items-center justify-center text-center p-1">
              <span class="text-xs text-white font-bold animate-pulse">↻ {{ tr('Regenerating…', 'Đang tạo lại…') }}</span>
            </div>
            <div v-else-if="isGenerating && getShotState(shot) !== 'Ready'" class="absolute inset-x-0 bottom-0 z-10 bg-black/65 py-1 text-center">
              <span v-if="getShotState(shot) === 'Generating'" class="text-[10px] text-indigo-300 font-bold animate-pulse">● {{ tr('Generating', 'Đang tạo') }}</span>
              <span v-else-if="getShotState(shot) === 'Queued'" class="text-[10px] text-indigo-300 font-mono">○ {{ tr('Queued', 'Trong hàng đợi') }}</span>
              <span v-else-if="getShotState(shot) === 'Failed'" class="text-[10px] text-rose-300 font-semibold" :title="getShotMessage(shot)">! {{ tr('Needs attention', 'Cần xử lý') }}</span>
              <span v-else-if="getShotState(shot) === 'Cancelled'" class="text-[10px] text-zinc-300 font-mono">× {{ tr('Stopped', 'Đã dừng') }}</span>
              <span v-else class="text-[10px] text-zinc-300 font-mono">○ {{ tr('Waiting for first frame', 'Chờ khung hình đầu') }}</span>
            </div>
          </div>

          <!-- The first frame's review: approve it before its video is made -->
          <div v-if="frame(shot)?.needs_keyframe" class="mb-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5" data-test="scene-first-frame" @click.stop>
            <Badge
              :theme="!frame(shot).url ? 'gray' : frame(shot).stale ? 'red' : frame(shot).status === 'Approved' ? 'green' : 'orange'"
              :label="!frame(shot).url ? tr('No first frame', 'Chưa có khung hình đầu') : frame(shot).stale ? tr('Frame out of date', 'Khung hình đã cũ')
                : frame(shot).status === 'Approved' ? tr('Frame approved', 'Khung hình đã duyệt') : tr('Frame to review', 'Khung hình chờ duyệt')"
            />
            <button
              v-if="frame(shot).url && !frame(shot).stale" type="button" class="whitespace-nowrap text-[10px] font-semibold text-indigo-400 hover:underline"
              @click="frames.approve(shot.name, frame(shot).status !== 'Approved')"
            >
              {{ frame(shot).status === 'Approved' ? tr('Undo', 'Hoàn tác') : tr('Approve', 'Duyệt') }}
            </button>
            <button type="button" class="whitespace-nowrap text-[10px] text-ink-muted hover:text-ink-primary" :disabled="frames.drawingShot.value === shot.name" @click="frames.draw([shot.name])">
              {{ frame(shot).url ? tr('Redraw', 'Vẽ lại') : tr('Draw', 'Vẽ') }}
            </button>
          </div>

          <button v-if="frame(shot)?.url && !frame(shot)?.stale" type="button" class="mb-2 text-[10px] underline text-ink-muted"
            data-test="repair-opening-art" :disabled="busyShots.includes(shot.name)" @click.stop="emit('repairOpeningArt', shot)">
            {{ tr('Restore print in opening image', 'Khôi phục chữ trên ảnh mở cảnh') }}
          </button>

          <!-- The automatic consistency check of the latest frame or take (services/review/consistency.py) -->
          <div v-if="shot.consistency_status" class="mb-1 text-[10px]" data-test="consistency-check" :title="shot.consistency_notes || ''">
            <Badge
              :theme="{ Passed: 'green', 'Needs Review': 'red', Redoing: 'orange', Redrawing: 'orange', Checking: 'blue' }[shot.consistency_status] || 'gray'"
              :label="{
                Checking: tr('Checking consistency…', 'Đang kiểm tra tính nhất quán…'),
                Passed: tr('Scene action checks passed', 'Đạt kiểm tra hành động cảnh'),
                Redrawing: tr('Inconsistent: redrawing the frame automatically', 'Chưa nhất quán: đang tự vẽ lại khung hình'),
                Redoing: tr('Inconsistent: redoing the video automatically', 'Chưa nhất quán: đang tự làm lại video'),
                'Needs Review': tr('Needs your review', 'Cần bạn xem lại'),
                'Not Checked': tr('Not checked automatically', 'Chưa kiểm tra tự động'),
              }[shot.consistency_status]"
            />
            <p v-if="shot.consistency_notes && shot.consistency_status !== 'Passed'" class="mt-0.5 text-ink-muted line-clamp-3">{{ shot.consistency_notes }}</p>
          </div>

          <button v-if="shot.selected_output_asset_version" type="button" class="mb-2 text-[10px] underline text-ink-muted" data-test="check-scene"
            :disabled="shot.consistency_status === 'Checking' || busyShots.includes(shot.name)" @click.stop="emit('checkScene', shot)">
            {{ tr('Check action & physical logic', 'Kiểm tra hành động và logic vật lý') }}
          </button>

          <button v-if="shot.selected_output_asset_version" type="button" class="mb-2 ml-2 text-[10px] underline text-ink-muted" data-test="scene-findings" @click.stop="emit('reviewFindings', shot)">{{ tr('Review findings', 'Xem kết quả') }}</button>

          <button v-if="guidedEnabled && shot.selected_output_asset_version" type="button" class="mb-2 text-[10px] underline text-ink-muted" data-test="guide-motion" :disabled="busyShots.includes(shot.name)" @click.stop="emit('guideMotion', shot)">{{ tr('Guide the motion', 'Hướng dẫn chuyển động') }}</button>

          <!-- Scene title and length -->
          <div v-if="shot.brand_review?.required" data-test="brand-review" class="mb-2 text-[10px]" @click.stop>
            <button v-if="shot.selected_output_asset_version" :disabled="busyShots.includes(shot.name)" class="mb-1 block underline" data-test="restore-artwork" @click="emit('repairSourceArt', shot)">{{ tr('Restore original label / artwork', 'Khôi phục nhãn / hình gốc') }}</button>
            <Badge :theme="shot.brand_review.status === 'Approved' ? 'green' : 'orange'"
              :label="shot.brand_review.status === 'Approved' ? tr('Brand reviewed for this take', 'Đã duyệt thương hiệu cho bản này') : tr('Product, logo & mascot review required', 'Cần kiểm tra sản phẩm, logo và linh vật')" />
            <p class="mt-1 text-ink-muted">{{ tr('Compare the video with the source references: pack print, logo, colors and mascot proportions. Automatic scene checks do not certify branding.', 'So sánh video với ảnh gốc: bao bì, logo, màu sắc và tỷ lệ linh vật. Kiểm tra cảnh tự động không chứng nhận thương hiệu.') }}</p>
            <button v-if="shot.selected_output_asset_version" class="mt-1 underline disabled:opacity-40"
              :disabled="busyShots.includes(shot.name) || brandBusyShot === shot.name"
              @click="emit('reviewBrand', shot, shot.brand_review.status !== 'Approved')">
              {{ shot.brand_review.status === 'Approved' ? tr('Reopen brand review', 'Mở lại duyệt thương hiệu') : tr('Confirm product, logo & mascot match', 'Xác nhận sản phẩm, logo và linh vật đúng') }}
            </button>
          </div>
          <div class="flex items-center justify-between gap-1 text-xs font-bold text-ink-primary mb-1">
            <span class="truncate" :title="shot.storyboard_beat || ''">
              {{ shot.storyboard_beat || sceneBeat(shot) || tr(`Scene ${shot.shot_number}`, `Cảnh ${shot.shot_number}`) }}
            </span>
            <div class="flex items-center gap-1 shrink-0">
              <span
                v-if="shot.open_comments"
                class="text-[9px] px-1.5 py-0.5 rounded-full font-semibold leading-none bg-amber-500/20 text-amber-400"
                :title="tr(`${shot.open_comments} open comment(s)`, `${shot.open_comments} nhận xét chưa xử lý`)"
              >
                💬 {{ shot.open_comments }}
              </span>
              <span class="text-ink-secondary font-mono text-[11px] font-semibold bg-surface-card px-1.5 py-0.5 rounded border border-outline-border/60">
                {{ shot.source_timing || `${Number(estimateShotDuration(shot)).toFixed(1)}s` }}
              </span>
            </div>
          </div>

          <!-- The direction in plain words: what happens, and how it is filmed -->
          <dl class="mb-1.5 space-y-1 text-[11px] leading-relaxed" data-test="panel-direction" :title="shot.generation_prompt || ''">
            <div>
              <dt class="inline font-semibold text-ink-secondary">{{ tr('What happens: ', 'Diễn biến: ') }}</dt>
              <dd class="inline text-ink-primary">{{ direction(shot).action }}</dd>
            </div>
            <div v-if="direction(shot).camera">
              <dt class="inline font-semibold text-ink-secondary">{{ tr('Camera: ', 'Máy quay: ') }}</dt>
              <dd class="inline text-ink-muted whitespace-pre-line">{{ direction(shot).camera }}</dd>
            </div>
          </dl>

          <!-- What the sheet's illustration column gives for this scene: its picture, or a link -->
          <div v-if="shot.illustration" class="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px]" data-test="sheet-illustration" @click.stop>
            <span class="font-semibold text-ink-secondary">{{ tr('Sheet illustration:', 'Minh hoạ trong kịch bản:') }}</span>
            <template v-for="item in shot.illustration.split('\n').filter(Boolean)" :key="item">
              <a v-if="item.startsWith('http')" :href="item" target="_blank" rel="noopener" class="text-indigo-400 hover:underline truncate max-w-[140px]">{{ item }}</a>
              <a v-else :href="item" target="_blank" rel="noopener"><img :src="item" alt="" class="h-10 rounded border border-outline-border object-cover" loading="lazy" /></a>
            </template>
          </div>

          <!-- On-screen caption: editable in place, saved when the field is left -->
          <input
            :value="shot.caption || ''"
            type="text"
            maxlength="120"
            class="w-full mb-2 px-2 py-1 rounded-lg bg-surface-card border border-outline-border/60 text-[11px] italic text-ink-primary placeholder:text-ink-muted placeholder:not-italic focus:outline-none focus:border-indigo-500"
            :placeholder="currentLang === 'vi' ? 'Chữ trên màn hình (không bắt buộc)' : 'On-screen text (optional)'"
            :title="currentLang === 'vi' ? 'Hiện ở cuối khung hình trong cảnh này' : 'Shown at the bottom of the frame during this scene'"
            @click.stop
            @keydown.enter="$event.target.blur()"
            @change="emit('updateCaption', shot, $event.target.value)"
          />

          <div
            v-if="shot.reference_image || shot.last_frame_image"
            class="flex items-center gap-1.5 mb-2 text-[10px] text-ink-muted"
          >
            <span class="font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Ảnh tham chiếu:' : 'Reference:' }}
            </span>
            <span
              v-if="shot.reference_image_reference_key"
              class="rounded-full bg-indigo-500/10 border border-indigo-500/30 px-1.5 py-0.5 text-indigo-400 truncate"
            >
              @{{ shot.reference_image_reference_key }}
            </span>
            <span
              v-if="shot.last_frame_image_reference_key"
              class="rounded-full bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 text-amber-400 truncate"
            >
              @{{ shot.last_frame_image_reference_key }}
            </span>
          </div>

          <!-- Bottom: Role Badge & Scene action menu -->
          <div class="flex items-center justify-between pt-1.5 border-t border-outline-border/60 text-xs">
            <!-- Takes, as in Google Flow: step through every render of this scene -->
            <div v-if="Number(shot.take_count) > 1" class="flex items-center gap-0.5 text-[10.5px] text-ink-secondary">
              <button
                type="button"
                class="px-1 rounded hover:bg-surface-hover cursor-pointer disabled:opacity-30 disabled:cursor-default"
                :disabled="isRegenerating(shot) || shot.take_index <= 1"
                :title="currentLang === 'vi' ? 'Phiên bản trước' : 'Previous take'"
                @click.stop="emit('selectTake', shot, shot.take_index - 1)"
              >‹</button>
              <span class="font-mono" :title="currentLang === 'vi' ? 'Phiên bản' : 'Take'">{{ shot.take_index || '–' }}/{{ shot.take_count }}</span>
              <button
                type="button"
                class="px-1 rounded hover:bg-surface-hover cursor-pointer disabled:opacity-30 disabled:cursor-default"
                :disabled="isRegenerating(shot) || shot.take_index >= shot.take_count"
                :title="currentLang === 'vi' ? 'Phiên bản sau' : 'Next take'"
                @click.stop="emit('selectTake', shot, shot.take_index + 1)"
              >›</button>
            </div>
            <span v-else />
            <div class="relative flex items-center gap-1">
              <button
                v-if="getShotVideoFile(shot)"
                type="button"
                class="px-2 py-0.5 rounded-lg text-[11px] font-semibold text-indigo-400 hover:bg-indigo-500/10 cursor-pointer disabled:opacity-40 disabled:cursor-default"
                :disabled="isRegenerating(shot) || Boolean(production?.planning)"
                :title="currentLang === 'vi'
                  ? 'Dựng lại cảnh này với mô tả hiện tại. Bản cũ vẫn được giữ.'
                  : 'Render this scene again from its current description. The old take is kept.'"
                @click.stop="emit('regenerateShot', shot)"
              >
                ↻ {{ currentLang === 'vi' ? 'Tạo lại' : 'Redo' }}
              </button>
              <button
                v-if="shot.output_video"
                type="button" data-test="review-scene"
                class="px-2 py-0.5 rounded-lg text-[11px] font-semibold text-amber-400 hover:text-amber-300 hover:bg-surface-hover cursor-pointer transition-colors"
                :title="currentLang === 'vi' ? 'Xem và nhận xét cảnh này' : 'Watch and comment on this scene'"
                @click.stop="emit('editShot', shot, index)"
              >
                💬 {{ currentLang === 'vi' ? 'Nhận xét' : 'Review' }}{{ shot.open_comments ? ` (${shot.open_comments})` : '' }}
              </button>
              <button
                type="button"
                class="px-2 py-0.5 rounded-lg text-sm font-semibold text-indigo-400 hover:text-indigo-300 hover:bg-surface-hover cursor-pointer transition-colors"
                :title="currentLang === 'vi' ? 'Tùy chọn cảnh' : 'Scene options'"
                :aria-expanded="menuOpenIndex === index"
                @click.stop="toggleSceneMenu(index)"
              >
                ⋯
              </button>
              <div
                v-if="menuOpenIndex === index"
                class="absolute right-0 bottom-8 z-30 w-52 rounded-xl border border-outline-border bg-surface-card p-1.5 shadow-xl"
                @click.stop
              >
                <button
                  type="button"
                  class="w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-ink-primary hover:bg-surface-hover cursor-pointer"
                  @click="emit('editShot', shot, index); menuOpenIndex = null"
                >
                  {{ currentLang === 'vi' ? 'Sửa cảnh' : 'Edit Scene' }}
                </button>
				<button
				  type="button"
				  class="w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-ink-primary hover:bg-surface-hover cursor-pointer"
				  @click="emit('updateContinuity', shot, shot.continuity_mode === 'Continue' ? 'New Scene' : 'Continue'); menuOpenIndex = null"
				>
				  {{ shot.continuity_mode === 'Continue'
				    ? (currentLang === 'vi' ? 'Bắt đầu cảnh mới' : 'Start new scene')
				    : (currentLang === 'vi' ? 'Nối từ cảnh trước' : 'Continue previous scene') }}
				</button>
                <div v-if="cuesFor(shot).length" class="border-t border-outline-border mt-1 pt-1" data-test="shot-audio-cues">
                  <p class="px-2.5 py-1 text-[10px] uppercase tracking-wide text-ink-muted">
                    {{ currentLang === 'vi' ? 'Âm thanh theo kịch bản' : 'Audio cues' }}
                  </p>
                  <button
                    v-for="cue in cuesFor(shot)"
                    :key="cue.role + cue.text"
                    type="button"
                    class="flex w-full items-start gap-2 rounded-lg px-2.5 py-1 text-left text-[11px] text-ink-primary hover:bg-surface-hover cursor-pointer"
                    :title="cue.text"
                    @click="emit('placeCueAudio', shot, cue.role); menuOpenIndex = null"
                  >
                    <span :class="cue.scheduled ? 'text-emerald-400' : 'text-amber-400'">{{ cue.scheduled ? '✓' : '+' }}</span>
                    <span class="min-w-0"><b>{{ cue.role }}</b> <span class="truncate block text-ink-muted">{{ cue.text }}</span></span>
                  </button>
                </div>
                <button
                  v-if="cuesFor(shot).some(cue => cue.role === 'Voiceover' && !cue.scheduled) && getShotVideoFile(shot)"
                  type="button"
                  class="w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-indigo-400 hover:bg-surface-hover disabled:opacity-50"
                  :disabled="Boolean(narrationBusyShot)"
                  data-test="generate-voiceover"
                  @click="emit('generateVoiceover', shot); menuOpenIndex = null"
                >
                  {{ currentLang === 'vi' ? 'Tạo giọng đọc tiếng Việt' : 'Generate Vietnamese narration' }}
                </button>
                <div v-if="projectReferences.length" class="border-t border-outline-border mt-1 pt-1" data-test="shot-references">
                  <p class="px-2.5 py-1 text-[10px] uppercase tracking-wide text-ink-muted">
                    {{ currentLang === 'vi' ? 'Tham chiếu cho cảnh' : 'Scene references' }}
                  </p>
                  <label
                    v-for="reference in projectReferences"
                    :key="reference.reference_key"
                    class="flex items-center gap-2 rounded-lg px-2.5 py-1 text-[11px] text-ink-primary hover:bg-surface-hover cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      class="accent-indigo-600"
                      :checked="shotUsesReference(shot, reference)"
                      :disabled="isGenerating"
                      @change="toggleReference(shot, reference)"
                    />
                    <span class="truncate">{{ reference.label || reference.asset_name }}</span>
                  </label>
                </div>
                <button
                  type="button"
                  class="w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-rose-400 hover:bg-rose-500/10 cursor-pointer disabled:opacity-50"
                  :disabled="isGenerating"
                  @click="emit('deleteShot', shot, index); menuOpenIndex = null"
                >
                  {{ currentLang === 'vi' ? 'Xóa cảnh' : 'Delete Scene' }}
                </button>
              </div>
            </div>
          </div>
        </div>

      </template>
    </div>

    <div v-if="shots.length" class="relative flex justify-end pt-1">
      <button
        type="button"
        class="rounded-xl border border-dashed border-indigo-500/50 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-400 hover:bg-indigo-500/20 cursor-pointer"
        @click="$emit('addScene', shots[shots.length - 1])"
      >
        + {{ currentLang === 'vi' ? 'Thêm cảnh' : 'Add Scene' }}
      </button>
    </div>

    <!-- Empty Storyboard State -->
    <div v-else class="text-center py-6 text-xs text-ink-muted">
      {{ currentLang === 'vi' ? 'Nhập ý tưởng video bên trên và bấm Tạo Video để sinh phân cảnh tự động.' : 'Enter your video idea above and click Generate Video to create storyboard scenes.' }}
    </div>
  </div>
</template>

<script setup>
import { Badge, Button } from "frappe-ui";
import { tr } from "../../stores/i18n";
import { computed, ref, watch } from "vue";

const props = defineProps({
  projectName: { type: String, required: true },
  guidedEnabled: { type: Boolean, default: false },
  frames: { type: Object, required: true },
  shots: { type: Array, default: () => [] },
  selectedShotIndex: { type: Number, default: 0 },
  selectedTarget: { type: String, default: "scene" },
  totalDurationSeconds: { type: [Number, String], default: 15 },
  hasStoryboard: { type: Boolean, default: false },
  isGenerating: { type: Boolean, default: false },
  isRevising: { type: Boolean, default: false },
  revisionError: { type: String, default: "" },
  expectedShotCount: { type: Number, default: 0 },
  production: { type: Object, default: null },
  generationPhase: { type: String, default: "idle" },
  syncError: { type: String, default: "" },
  currentLang: { type: String, default: "en" },
  // Scenes with a render in progress (several scenes can be regenerated at once).
  busyShots: { type: Array, default: () => [] },
  estimateShotDuration: { type: Function, default: (s) => s?.duration_seconds || 5 },
  formatShotKeyframeTime: { type: Function, default: () => "0.0s" },
  getShotVideoFile: { type: Function, default: () => "" },
  getShotFirstFrame: { type: Function, default: () => ({}) },
  // Visual project references a scene can be generated from.
  projectReferences: { type: Array, default: () => [] },
  audioPlan: { type: Array, default: () => [] },
  narrationBusyShot: { type: String, default: '' },
  brandBusyShot: { type: String, default: '' },
  // The storyboard is the advertiser's sheet, followed as written: it is changed by editing the sheet, not by the AI.
  fromSheet: { type: Boolean, default: false },
  // First frames are drawn from the approved scenes only.
  storyboardApproved: { type: Boolean, default: true },
  portrait: { type: Boolean, default: false },
});

const frames = props.frames;
const frame = (shot) => frames.byShot.value[shot.name];

const emit = defineEmits([
  "selectShot",
  "editShot",
  "deleteShot",
  "addScene",
  "selectKeyframe",
  "changeShotDuration",
  "reviseStoryboard",
  "reorderShots",
  "regenerateShot",
  "selectTake",
  "updateCaption",
	"updateContinuity",
  "updateReferences",
  "placeCueAudio",
  "generateVoiceover",
  "reviewBrand",
  "checkScene",
  "reviewFindings",
  "repairSourceArt",
  "repairOpeningArt",
  "guideMotion",
]);

const aiRevisionInput = ref("");
// The scene whose video plays in its panel.
const playing = ref("");

const panelImage = (shot) => frame(shot)?.url || props.getShotFirstFrame(shot)?.file || shot.reference_image || shot.last_frame_image || "";

// The direction under a panel: the sheet's own words in a Vietnamese studio, the English direction otherwise.
function direction(shot) {
  if (shot.authored_action) return {action:shot.authored_action,camera:shot.sheet_direction?.camera||shot.direction?.camera||''};
  const sheet = shot.sheet_direction;
  const english = shot.direction || {};
  if (sheet?.action && (props.currentLang === "vi" || !english.action)) return sheet;
  return english.action ? english : { action: sceneSummary(shot), camera: "" };
}
const menuOpenIndex = ref(null);

function cuesFor(shot) {
  return props.audioPlan.filter((cue) => cue.shot === shot.name);
}

function shotUsesReference(shot, reference) {
  return (shot.references || []).some((item) => item.reference_key === reference.reference_key);
}

function toggleReference(shot, reference) {
  const current = (shot.references || []).map((item) => item.reference_key).filter(Boolean);
  const next = current.includes(reference.reference_key)
    ? current.filter((key) => key !== reference.reference_key)
    : [...current, reference.reference_key];
  emit("updateReferences", shot, next);
}

function toggleSceneMenu(index) {
  menuOpenIndex.value = menuOpenIndex.value === index ? null : index;
}

function submitAiRevision() {
  emit("reviseStoryboard", aiRevisionInput.value.trim());
}

watch(
  () => props.isRevising,
  (isRevising, wasRevising) => {
    if (wasRevising && !isRevising && !props.revisionError) {
      aiRevisionInput.value = "";
    }
  },
);

const draggedIndex = ref(null);

function onDragStart(shot, index, event) {
  draggedIndex.value = index;
  event.dataTransfer.effectAllowed = "move";
}

function onDrop(shot, index) {
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    emit("reorderShots", draggedIndex.value, index);
  }
  draggedIndex.value = null;
}

const completedShotsCount = computed(() => {
  if (!props.shots?.length) return 0;
  return props.shots.filter((s) => Boolean(props.getShotVideoFile(s))).length;
});

// Story roles the AI director gives each scene ("CLIMAX: Sunset on the terrace").
const SCENE_BEATS = {
  OPENING: ["Opening", "Mở đầu"],
  BUILD: ["Build-up", "Phát triển"],
  CLIMAX: ["Climax", "Cao trào"],
  RESOLUTION: ["Wind-down", "Lắng đọng"],
  CLOSING: ["Ending", "Kết thúc"],
};

function sceneBeat(shot) {
  const beat = SCENE_BEATS[String(shot.shot_name || "").split(":")[0].trim().toUpperCase()];
  return beat ? beat[props.currentLang === "vi" ? 1 : 0] : "";
}

function sceneSummary(shot) {
  const name = String(shot.shot_name || "");
  const title = name.includes(":") ? name.slice(name.indexOf(":") + 1).trim() : name.trim();
  if (title && !/^(scene|shot)\s*\d+$/i.test(title)) return title;
  const picture = props.currentLang === "vi" ? "ảnh" : "picture";
  // The full prompt is for the AI; show it without its <Picture N> markup.
  const prompt = String(shot.generation_prompt || "").replace(/<Picture\s*(\d+)>/gi, `${picture} $1`);
  return prompt || (props.currentLang === "vi" ? "Cảnh giới thiệu sản phẩm" : "Product showcase");
}

function isRegenerating(shot) {
  return Boolean(props.getShotVideoFile(shot) && props.busyShots.includes(shot.name));
}

function getShotState(shot) {
  if (props.getShotVideoFile(shot)) return "Ready";
  const status = props.production?.shots?.find((item) => item.shot === shot.name)?.status;
  if (status === "Running" || status === "Generating") return "Generating";
  if (status === "Queued") return "Queued";
  if (status === "Failed") return "Failed";
  if (status === "Cancelled") return "Cancelled";
  return "Waiting";
}

function getShotMessage(shot) {
  return props.production?.shots?.find((item) => item.shot === shot.name)?.message || "";
}

function getShotBadgeClass(shot, idx) {
  const state = typeof shot === "object" ? getShotState(shot) : "Waiting";
  if (state === "Ready") return "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
  if (state === "Failed") return "bg-rose-500/20 text-rose-400 border border-rose-500/30";
  if (state === "Generating") {
    return "bg-indigo-500/20 text-indigo-400 border border-indigo-500/40 animate-pulse";
  }
  if (state === "Queued") return "bg-indigo-500/10 text-indigo-400 border border-indigo-500/30";
  return "bg-surface-muted text-ink-muted border border-outline-border";
}

function getShotStatusGlyph(shot, idx) {
  const state = typeof shot === "object" ? getShotState(shot) : "Waiting";
  if (state === "Ready") return "✓";
  if (state === "Failed") return "!";
  if (state === "Generating") return "●";
  return "○";
}
</script>
