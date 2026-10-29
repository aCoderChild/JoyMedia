<template>
  <section v-if="focused.length" class="rounded-xl border border-outline-border p-4 space-y-4" data-test="creative-batches">
    <article v-for="{ batch, variant } in focused" :key="batch.name + variant.index" class="space-y-4 text-sm" :data-test="'variant-' + variant.index">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-semibold">{{ variant.script?.display_title || variant.title || variant.script?.title || (working(variant) ? tr('Writing a new story…', 'Đang viết câu chuyện mới…') : tr('No script yet', 'Chưa có kịch bản')) }}</h2>
        <div class="flex items-center gap-3 text-xs">
          <span class="rounded-full px-2 py-0.5" :class="pill(variant.status)">{{ label(variant.status) }}</span>
          <button v-if="active(batch) && working(variant)" class="text-ink-muted underline" @click="cancel(batch)">{{ tr('Stop', 'Dừng') }}</button>
        </div>
      </div>
      <ol v-if="!finishedVideo(variant)" class="grid grid-cols-5 gap-1 text-[11px] text-ink-muted" :aria-label="tr('Progress', 'Tiến độ')">
        <li v-for="(step, i) in steps" :key="step.key" :aria-current="i === progress(variant) ? 'step' : undefined">
          <span class="mb-1 block h-1.5 rounded-full" :class="i < progress(variant) ? 'bg-rio-500' : i === progress(variant) && working(variant) ? 'bg-rio-300 animate-pulse' : i === progress(variant) && variant.status === 'Needs Attention' ? 'bg-rose-400' : i === progress(variant) && waiting.includes(variant.status) ? 'bg-amber-400' : 'bg-surface-muted'" />
          <span :class="i === progress(variant) && 'font-semibold text-ink-primary'">{{ step.label }}</span>
        </li>
      </ol>
      <div v-if="!finishedVideo(variant)" class="rounded-lg border p-3" :class="nextStep(batch, variant).tone" role="status" data-test="next-step">
        <p class="font-medium">{{ nextStep(batch, variant).title }}</p>
        <p v-if="nextStep(batch, variant).detail" class="text-xs mt-0.5 opacity-80">{{ nextStep(batch, variant).detail }}</p>
      </div>
      <ReferenceRegistry :registry="variant.reference_registry" :scenes="variant.scene_reference_map" />
      <ReferencePreparation :plan="variant.reference_plan" :bridges="variant.reference_bridges" />
      <details v-if="variant.prepared_assets?.length" class="rounded-lg border border-outline-border p-3" data-test="prepared-assets">
        <summary class="cursor-pointer font-medium">{{ tr('Prepared product views and character poses', 'Góc sản phẩm và tư thế nhân vật đã chuẩn bị') }}</summary>
        <ul class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          <li v-for="(asset, i) in variant.prepared_assets" :key="`${asset.kind}-${asset.reference_key || i}`" class="min-w-0 rounded border border-outline-border p-2 text-xs">
            <img v-if="asset.url" :src="asset.url" :alt="asset.description || asset.kind" class="h-28 w-full rounded bg-surface-muted object-contain" loading="lazy" />
            <div v-else class="grid h-28 place-items-center rounded bg-surface-muted px-2 text-center text-ink-muted">{{ tr('View not verified', 'Góc nhìn chưa được xác minh') }}</div>
            <p class="mt-1 font-medium">{{ asset.kind === 'Character' ? tr('Character pose', 'Tư thế nhân vật') : tr('Product view', 'Góc sản phẩm') }} <span v-if="asset.scenes?.length">· {{ tr('Scenes', 'Cảnh') }} {{ asset.scenes.join(', ') }}</span></p>
            <p class="line-clamp-2 text-ink-secondary" :title="asset.description">{{ asset.description || tr('Source view', 'Góc gốc') }}</p>
            <p v-if="asset.status === 'supplied'" class="text-ink-secondary">{{ tr('Supplied reference', 'Ảnh tham chiếu đã cung cấp') }}</p>
            <p v-else-if="asset.status !== 'ready'" class="text-amber-700 dark:text-amber-300">{{ tr('Not verified', 'Chưa xác minh') }}</p>
          </li>
        </ul>
      </details>
      <p v-if="variant.product && !(variant.script?.display_title || variant.title || '').toLowerCase().includes(variant.product.toLowerCase())" class="text-xs text-ink-muted">{{ tr('Product', 'Sản phẩm') }}: {{ variant.product }}</p>
      <div class="space-y-4 text-sm">

        <div v-if="['Pictures Ready', 'Keyframes', 'Locations', 'Rewriting'].includes(variant.status) && (variant.pictures?.some(p => p.url) || variant.status === 'Pictures Ready')" class="space-y-2" data-test="picture-review">
          <p v-if="batch.delivery_mode === 'automatic'" class="text-xs text-ink-secondary">{{ tr('Storyboard first frames appear here as they finish. Video generation continues automatically.', 'Ảnh đầu của từng cảnh xuất hiện tại đây khi tạo xong. Hệ thống tự tiếp tục tạo video.') }}</p>
          <ol class="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <li v-for="picture in variant.pictures" :key="picture.shot" class="rounded-lg border border-outline-border p-1.5 text-xs" :class="picture.note && !repairing(variant) ? 'border-amber-300' : ''">
              <img v-if="picture.url" :src="picture.url" :alt="picture.shot_name" class="h-48 w-full rounded object-contain bg-surface-muted" loading="lazy" />
              <div v-else class="grid h-48 w-full place-items-center rounded bg-surface-muted text-ink-muted">{{ tr('No picture yet', 'Chưa có hình') }}</div>
              <p class="mt-1 font-medium truncate" :title="picture.shot_name">{{ picture.shot_number }}. {{ sceneName(variant, picture.shot_number, picture.shot_name) }}</p>
              <p v-if="picture.note?.startsWith('Critical ')" class="font-medium" :class="repairing(variant) ? 'text-rio-600 dark:text-rio-300' : 'text-amber-700 dark:text-amber-300'">{{ repairing(variant) ? tr('AI is adjusting this picture', 'AI đang chỉnh lại ảnh này') : tr('This picture is not right yet — please check it', 'Ảnh này chưa đạt — hãy xem lại') }}</p>
              <p v-if="picture.label_unlocked && !repairing(variant)" class="font-medium text-amber-700 dark:text-amber-300">{{ tr('Product label not locked (a paw covers it): compare the label with your product photo.', 'Nhãn sản phẩm chưa được khoá (bị tay che): hãy so nhãn với ảnh sản phẩm.') }}</p>
              <p v-if="pictureNote(picture.note || '') && (picture.note.startsWith('Critical ') || !(repairing(variant) && batch.delivery_mode === 'automatic'))" class="text-amber-700 dark:text-amber-300" :title="picture.note">{{ pictureNote(picture.note) }}</p>
              <div v-if="variant.status === 'Pictures Ready'" class="flex gap-2">
                <button class="underline text-ink-muted" :disabled="busy" @click="redraw(batch, variant, picture)">{{ tr('Draw again', 'Vẽ lại') }}</button>
                <button v-if="!(key(batch, variant, picture.shot_number) in drafts)" class="underline text-ink-muted" @click="drafts[key(batch, variant, picture.shot_number)] = ''">{{ tr('Add note', 'Thêm ghi chú') }}</button>
              </div>
              <textarea v-if="key(batch, variant, picture.shot_number) in drafts" v-model="drafts[key(batch, variant, picture.shot_number)]" rows="2" class="mt-1 w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('What should change in this scene?', 'Cảnh này cần sửa gì?')" />
            </li>
          </ol>
        </div>

        <!-- This is deliberately separate from the final export.  It keeps the
             whole film visible while later clips and all sound work are pending. -->
        <!-- While the video is being made: a growing silent draft. It goes once the finished video exists. -->
        <section v-if="variant.rough_preview?.file && !variant.video" class="space-y-2" data-test="progressive-film-preview">
          <p class="text-xs text-ink-secondary">{{ tr(`Draft so far: ${readyScenes(variant)} of ${variant.preview_scenes?.length || 0} scenes ready · music and voice are added at the end`, `Bản dựng tạm: ${readyScenes(variant)}/${variant.preview_scenes?.length || 0} cảnh đã xong · nhạc và lời thoại được thêm ở bước cuối`) }}</p>
          <video :src="variant.rough_preview.file" controls playsinline preload="metadata" class="mx-auto max-h-[48vh] max-w-full rounded-xl bg-black" data-test="progressive-film-player" />
        </section>

        <!-- Every scene as its own clip; a weak one can be made again with an optional instruction. -->
        <section v-if="variant.preview_scenes?.length && readyScenes(variant)" class="space-y-2" data-test="scene-clips">
          <h3 class="text-sm font-semibold">{{ tr('Scenes', 'Các cảnh') }} <span class="font-normal text-ink-muted">· {{ readyScenes(variant) }}/{{ variant.preview_scenes.length }}</span></h3>
          <ol class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <li v-for="scene in variant.preview_scenes" :key="scene.shot" class="flex min-w-0 flex-col overflow-hidden rounded-xl border border-outline-border bg-surface-card text-xs" data-test="preview-scene">
              <div class="relative grid aspect-[3/4] place-items-center bg-surface-muted">
                <video v-if="scene.clip" :src="scene.clip" :poster="frame(variant, scene.shot_number)" controls playsinline preload="none" class="h-full w-full object-cover" />
                <img v-else-if="frame(variant, scene.shot_number)" :src="frame(variant, scene.shot_number)" alt="" class="h-full w-full object-cover opacity-60" loading="lazy" />
                <span v-if="!scene.ready" class="absolute inset-x-0 bottom-2 mx-auto w-fit rounded-full bg-black/60 px-2 py-0.5 text-[11px] text-white">{{ tr('Making…', 'Đang tạo…') }}</span>
              </div>
              <div class="flex flex-1 flex-col gap-1 p-2">
                <p class="font-medium leading-snug">{{ scene.shot_number }}. {{ sceneName(variant, scene.shot_number, scene.shot_name) }}</p>
                <p v-for="line in findingLines(scene.unresolved)" :key="line" class="text-amber-700 dark:text-amber-300" data-test="scene-unresolved">⚠ {{ line }}</p>
                <template v-if="scene.ready && !busy">
                  <button v-if="openRetry !== sceneKey(batch, variant, scene.shot)" type="button" class="mt-auto self-start text-rio-500 hover:underline" @click="openRetry = sceneKey(batch, variant, scene.shot)">↻ {{ tr('Make again', 'Làm lại') }}</button>
                  <div v-else class="mt-1 space-y-1">
                    <textarea v-model="scenePrompts[sceneKey(batch, variant, scene.shot)]" rows="3" class="w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('What should change? (optional)', 'Cần đổi gì? (tuỳ chọn)')" />
                    <div class="flex gap-2">
                      <button type="button" class="jm-button-primary px-2 py-1 text-xs" @click="retryScene(batch, variant, scene); openRetry = ''">{{ tr('Make this scene again', 'Làm lại cảnh này') }}</button>
                      <button type="button" class="text-ink-muted hover:underline" @click="openRetry = ''">{{ tr('Cancel', 'Huỷ') }}</button>
                    </div>
                  </div>
                </template>
              </div>
            </li>
          </ol>
        </section>

        <div v-if="variant.held_clips?.length && batch.delivery_mode !== 'automatic'" class="space-y-3" data-test="clip-review">
          <ol class="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <li v-for="clip in variant.held_clips" :key="clip.shot" class="flex flex-col rounded-lg border-2 p-2 text-xs transition-colors" :class="choice(clip) === 'use' ? 'border-emerald-500' : choice(clip) === 'redo' ? 'border-outline-border opacity-80' : 'border-amber-300'" :data-clip="clip.shot">
              <div class="grid place-items-center rounded bg-surface-muted">
                <video v-if="clip.url && playable(clip)" :src="clip.url" :poster="poster(variant, clip)" controls playsinline preload="metadata" class="max-h-72 max-w-full rounded" @error="broken[clip.shot] = true" />
                <div v-else class="relative">
                  <img v-if="poster(variant, clip)" :src="poster(variant, clip)" alt="" class="max-h-72 max-w-full rounded opacity-60" loading="lazy" />
                  <span class="absolute inset-x-0 bottom-2 mx-auto w-fit rounded-full bg-black/70 px-2 py-0.5 text-white">{{ tr('Will be made again', 'Sẽ được tạo lại') }}</span>
                </div>
              </div>
              <p class="mt-1.5 font-medium">{{ clip.shot_number }}. {{ sceneName(variant, clip.shot_number, clip.shot_name) }}</p>
              <p v-for="line in findingLines(clip.findings)" :key="line" class="text-amber-700 dark:text-amber-300">{{ line }}</p>
              <p v-if="!usable(clip)" class="text-ink-muted">{{ tr('This clip cannot be used; it will be made again.', 'Clip này không dùng được nên sẽ được tạo lại.') }}</p>
              <div v-else class="mt-auto pt-2">
                <div class="grid grid-cols-2 gap-1.5" role="group" :aria-label="tr('Your choice', 'Lựa chọn của bạn')">
                  <button type="button" class="rounded-md border px-2 py-1.5 font-medium" :class="choice(clip) === 'use' ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-outline-border hover:border-emerald-500'" :aria-pressed="choice(clip) === 'use'" :disabled="busy" data-test="clip-use" @click="decide(clip, 'use')">✓ {{ tr('Use', 'Dùng') }}</button>
                  <button type="button" class="rounded-md border px-2 py-1.5 font-medium" :class="choice(clip) === 'redo' ? 'border-ink-primary bg-ink-primary text-surface-card' : 'border-outline-border hover:border-ink-primary'" :aria-pressed="choice(clip) === 'redo'" :disabled="busy" data-test="clip-redo" @click="decide(clip, 'redo')">↻ {{ tr('Make again', 'Làm lại') }}</button>
                </div>
                <button v-if="choice(clip) === 'use' && !(('clip:' + clip.shot) in drafts)" type="button" class="mt-1 text-ink-muted underline" @click="drafts['clip:' + clip.shot] = ''">{{ tr('Add note', 'Thêm ghi chú') }}</button>
                <textarea v-if="choice(clip) === 'use' && ('clip:' + clip.shot) in drafts" v-model="drafts['clip:' + clip.shot]" rows="2" class="mt-1 w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('Note (optional)', 'Ghi chú (tuỳ chọn)')" />
              </div>
            </li>
          </ol>
          <div class="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 rounded-lg border border-outline-border bg-surface-card/95 p-3 backdrop-blur" data-test="clip-decisions">
            <button class="jm-button-primary" :disabled="busy || undecided(variant).length > 0" data-test="apply-clip-choices" @click="applyChoices(batch, variant)">{{ doneLabel(variant) }}</button>
            <span v-if="undecided(variant).length" class="text-xs text-ink-secondary">{{ tr(`Choose Use or Make again for ${undecided(variant).length} more clip(s).`, `Còn ${undecided(variant).length} clip chưa chọn Dùng hoặc Làm lại.`) }}</span>
            <button v-if="undecided(variant).length > 1" class="text-xs text-ink-muted underline" :disabled="busy" data-test="use-all-clips" @click="undecided(variant).forEach(clip => decide(clip, 'use'))">{{ tr('Use all the rest', 'Dùng tất cả clip còn lại') }}</button>
          </div>
        </div>

        <details v-if="variant.script?.scenes" :open="variant.status === 'Script Ready'" class="group text-xs" data-test="storyboard">
          <summary class="flex cursor-pointer list-none items-center gap-2 font-medium text-ink-primary">
            <span class="transition-transform group-open:rotate-90">▸</span>
            {{ tr('Storyboard', 'Bảng phân cảnh') }}
            <span class="rounded-full bg-surface-muted px-2 py-0.5 font-normal text-ink-secondary">{{ variant.script.scenes.length }} {{ tr('scenes', 'cảnh') }} · {{ totalSeconds(variant) }}s</span>
          </summary>
          <!-- The film at a glance: one segment per scene, as long as the scene. -->
          <div class="mt-3 flex h-7 overflow-hidden rounded-md" role="list" :aria-label="tr('Scene timeline', 'Dòng thời gian các cảnh')">
            <button v-for="(scene, i) in variant.script.scenes" :key="'t' + i" type="button" role="listitem" class="flex min-w-0 items-center justify-center border-r border-white/40 text-[11px] font-semibold text-white last:border-r-0 hover:brightness-110" :class="hue(i).bar" :style="{ flexGrow: Number(scene.duration_seconds) || 1, flexBasis: 0 }" :title="`${i + 1}. ${sceneName(variant, i + 1, scene.beat_name)} · ${Number(scene.duration_seconds).toFixed(1)}s`" @click="jump(batch, variant, i + 1)">{{ i + 1 }}</button>
          </div>
          <ol class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3" :class="columns(variant.script.scenes.length)">
            <li v-for="(scene, i) in variant.script.scenes" :id="sceneId(batch, variant, i + 1)" :key="i" class="flex scroll-mt-24 flex-col overflow-hidden rounded-xl border border-outline-border bg-surface-card shadow-sm transition-shadow hover:shadow-md" data-test="script-scene">
              <div class="relative bg-surface-muted">
                <a v-if="frame(variant, i + 1)" :href="frame(variant, i + 1)" target="_blank" rel="noopener" :title="tr('Open the full picture', 'Mở hình lớn')">
                  <img :src="frame(variant, i + 1)" :alt="sceneName(variant, i + 1, scene.beat_name)" class="block h-auto w-full" loading="lazy" />
                </a>
                <div v-else class="grid aspect-[3/4] w-full place-items-center text-ink-muted">
                  <span :class="working(variant) && 'animate-pulse'">{{ working(variant) ? tr('Drawing…', 'Đang vẽ…') : tr('No picture yet', 'Chưa có hình') }}</span>
                </div>
                <span class="absolute left-2 top-2 grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold text-white shadow" :class="hue(i).bar">{{ i + 1 }}</span>
                <span class="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-medium text-white">{{ Number(scene.duration_seconds).toFixed(1) }}s</span>
                <!-- On-screen text shown where the viewer will read it. -->
                <p v-if="scene.on_screen_text" class="absolute inset-x-2 bottom-2 rounded-md bg-black/65 px-2 py-1 text-center text-[11px] font-bold uppercase leading-snug tracking-wide text-white" :title="tr('On-screen text', 'Chữ trên hình')">{{ scene.on_screen_text }}</p>
              </div>
              <div class="flex flex-1 flex-col gap-1.5 p-2.5">
                <p class="text-sm font-semibold leading-tight text-ink-primary">{{ sceneName(variant, i + 1, scene.beat_name) }}</p>
                <div class="flex flex-wrap gap-1" data-test="scene-camera" :title="tr('Camera', 'Máy quay')">
                  <span v-for="tag in cameraTags(scene)" :key="tag" class="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] text-ink-secondary">{{ tag }}</span>
                </div>
                <blockquote v-if="scene.voice_over" class="rounded-md border-l-2 bg-surface-muted/60 px-2 py-1 italic text-ink-primary" :class="hue(i).edge" :title="tr('Voice-over', 'Lời thoại')">🔊 “{{ scene.voice_over }}”</blockquote>
                <p class="cursor-pointer text-ink-secondary" :class="!expanded[sceneId(batch, variant, i + 1)] && 'line-clamp-3'" :title="tr('Tap to read all', 'Bấm để đọc hết')" @click="expanded[sceneId(batch, variant, i + 1)] = !expanded[sceneId(batch, variant, i + 1)]">{{ String(scene.visual_camera || '').replace(/_/g, ' ') }} {{ plainAction(scene.action) }}</p>
                <template v-if="canRevise(batch, variant)">
                  <button v-if="!(key(batch, variant, i + 1) in drafts)" class="mt-auto self-start pt-1 text-rio-500 hover:underline" @click="drafts[key(batch, variant, i + 1)] = ''">✎ {{ tr('Add note', 'Thêm ghi chú') }}</button>
                  <textarea v-else v-model="drafts[key(batch, variant, i + 1)]" rows="2" class="mt-auto w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('What should change in this scene?', 'Cảnh này cần sửa gì?')" />
                </template>
              </div>
            </li>
          </ol>
          <textarea v-if="canRevise(batch, variant)" v-model="drafts[key(batch, variant, 0)]" rows="2" class="mt-3 w-full rounded border border-outline-border bg-transparent p-2" :placeholder="tr('Notes on the whole script (optional)', 'Ghi chú cho cả kịch bản (tuỳ chọn)')" />
        </details>

        <div class="flex flex-wrap items-center gap-2 text-xs">
          <button v-if="variant.status === 'Script Ready' && batch.status !== 'Cancelled'" class="jm-button-primary" :disabled="busy" @click="render(batch, variant)">{{ tr('Make this video', 'Tạo video này') }}</button>
          <button v-if="variant.status === 'Pictures Ready' && batch.status !== 'Cancelled'" class="jm-button-primary" :disabled="busy || variant.pictures?.some(p => !p.url)" @click="approvePictures(batch, variant)">{{ tr('Approve pictures & make video', 'Duyệt hình và tạo video') }}</button>
          <span v-if="variant.status === 'Pictures Ready' && variant.pictures?.some(p => !p.url)" class="text-ink-muted" data-test="approve-hint">{{ tr('Every scene needs a picture first: draw the missing ones again.', 'Cần đủ hình cho mọi cảnh: hãy vẽ lại các hình còn thiếu.') }}</span>
          <button v-if="canRevise(batch, variant)" class="jm-button-secondary" :disabled="busy || !notes(batch, variant).length" @click="revise(batch, variant)">{{ tr('Rewrite with my notes', 'Viết lại theo ghi chú') }}<span v-if="notes(batch, variant).length"> ({{ notes(batch, variant).length }})</span></button>
          <button v-if="variant.status === 'Needs Attention' && batch.status !== 'Cancelled' && !variant.held_clips?.length" class="jm-button-secondary" :disabled="busy" @click="retry(batch, variant)">{{ variant.resume_stage === 'Rendering' && variant.held_clips && !variant.held_clips.length ? tr('Continue to editing & music', 'Tiếp tục dựng & thêm nhạc') : variant.held_clips?.length ? tr('Render held scenes again', 'Tạo lại các cảnh bị giữ') : tr('Try again', 'Thử lại') }}</button>
          <a v-if="variant.workbook" :href="variant.workbook" download class="underline">{{ tr('Download script (.xlsx)', 'Tải kịch bản (.xlsx)') }}</a>
          <a v-if="variant.video && !finishedVideo(variant)" :href="variant.video" download class="underline">{{ tr('Download video', 'Tải video') }}</a>
        </div>
        <details v-if="variant.error || variant.script?.director_notes?.length || Object.keys(variant.picture_notes || {}).length" class="text-xs text-ink-muted" data-test="director-notes">
          <summary class="cursor-pointer">{{ tr('Details for the production team', 'Chi tiết cho nhóm sản xuất') }}</summary>
          <ul v-if="variant.script?.director_notes?.length" class="mt-1 list-disc pl-4"><li v-for="(note, i) in variant.script.director_notes" :key="i">{{ shortNote(note) }}</li></ul>
          <ul v-if="Object.keys(variant.picture_notes || {}).length" class="mt-1 list-disc pl-4"><li v-for="(note, shot) in variant.picture_notes" :key="shot">{{ shot }}: {{ shortNote(note) }}</li></ul>
          <p v-if="variant.error" class="mt-1 whitespace-pre-wrap break-words">{{ variant.error }}</p>
        </details>
      </div>
    </article>
    <p v-if="error" role="alert" class="text-xs text-rose-500">{{ error }}</p>
  </section>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue';
import { call } from 'frappe-ui';
import { tr } from '../../stores/i18n';
import { errorMessage } from '../../utils/errors';
import ReferenceRegistry from './ReferenceRegistry.vue';
import ReferencePreparation from './ReferencePreparation.vue';
// `focus` is the one video whose details are shown; the shelf above chooses it.
const props = defineProps({ project: { type: String, required: true }, focus: { type: String, default: '' } });
const emit = defineEmits(['loaded', 'show-video']);
const batches = ref([]), error = ref(''), busy = ref(false);
const drafts = reactive({});
let timer, epoch = 0;
const active = batch => ['Queued', 'Planning', 'Rendering', 'Finishing'].includes(batch.status);
// Current work first: active batches and the two most recent; older ones collapse.
// The one video chosen on the shelf, with its batch (for actions).
const focused = computed(() => batches.value.flatMap(batch => videos(batch).filter(v => props.focus && v.project === props.focus).map(variant => ({ batch, variant }))));
// A stopped batch's unfinished videos are stopped too, whatever stage they had reached.
const videos = batch => batch.variants.map(v => batch.status === 'Cancelled' && v.status !== 'Completed' ? { ...v, status: 'Cancelled', error: '' } : v);
const steps = [
  { key: 'script', label: tr('Script', 'Kịch bản') },
  { key: 'pictures', label: tr('Scene pictures', 'Hình cảnh') },
  { key: 'video', label: tr('Video', 'Video') },
  { key: 'music', label: tr('Edit & music', 'Dựng & nhạc') },
  { key: 'ready', label: tr('Ready', 'Hoàn tất') },
];
// The step the video is on (or waiting at); earlier steps show as done.
const stageIndex = { Queued: 0, Planning: 0, Rewriting: 0, 'Script Ready': 0, Locations: 1, Keyframes: 1, 'Pictures Ready': 1, Rendering: 2, Finishing: 3, Exporting: 3, Completed: 5 };
const progress = v => stageIndex[v.status === 'Needs Attention' ? v.resume_stage || 'Planning' : v.status] ?? 0;
const waiting = ['Script Ready', 'Pictures Ready'];
const working = v => ![...waiting, 'Completed', 'Needs Attention', 'Cancelled'].includes(v.status);
const pill = status => status === 'Completed' ? 'bg-emerald-100 text-emerald-800' : status === 'Needs Attention' ? 'bg-rose-100 text-rose-800' : waiting.includes(status) ? 'bg-amber-100 text-amber-900' : 'bg-rio-100 text-rio-800';
const label = status => ({
  Queued: tr('Queued', 'Đang chờ'), Planning: tr('Writing the script', 'Đang viết kịch bản'),
  Locations: tr('Preparing the setting', 'Đang chuẩn bị bối cảnh'),
  Keyframes: tr('Drawing scene pictures', 'Đang vẽ hình cảnh'), Rendering: tr('Making the video', 'Đang tạo video'),
  Finishing: tr('Editing and adding music', 'Đang dựng và thêm nhạc'), Completed: tr('Video ready', 'Video đã xong'),
  Exporting: tr('Exporting video', 'Đang xuất video'),
  'Needs Attention': tr('Needs your help', 'Cần bạn xem lại'), 'Scripts Ready': tr('Scripts ready to review', 'Kịch bản chờ duyệt'),
  'Script Ready': tr('Script ready to review', 'Kịch bản chờ duyệt'), Cancelled: tr('Stopped', 'Đã dừng'),
  'Pictures Ready': tr('Pictures ready to review', 'Hình cảnh chờ duyệt'), Rewriting: tr('Improving some scenes', 'Đang chỉnh lại một số cảnh'), 'Awaiting Review': tr('Waiting for your review', 'Đang chờ bạn duyệt'),
}[status] || status);
// Camera choices in plain words, from the shared storyboard shot vocabulary.
const words = value => String(value || '').replace(/_/g, ' ');
const cameraText = scene => [words(scene.shot_framing), words(scene.shot_angle), words(scene.camera_move || 'static')].filter(Boolean).join(' · ');
const plainAction = text => String(text || '').split('\n').map(line => line.replace(/^\[[^\]]*\]\s*/, '').trim()).filter(Boolean).join(' ');
// Machine notes, in reviewer terms; the full text stays in the scene's evidence.
// Only notes specific to one picture; the routine "please confirm" applies to all and is said once above.
const pictureNote = note => /qualify this geometry/i.test(note) ? ''
  : /not drawn after|no picture/i.test(note) ? tr('This picture could not be drawn. Press "Draw again", or add a note to rewrite the scene.', 'Chưa vẽ được hình này. Bấm "Vẽ lại", hoặc thêm ghi chú để viết lại cảnh.')
  : /^check that the picture shows:/i.test(note) ? tr('Check this detail in the picture: ', 'Hãy kiểm tra chi tiết này trong hình: ') + String(note).replace(/^check that the picture shows:\s*/i, '').replace(/\.? automatic screening could not confirm it\.?$/i, '')
  : findingText(note);
// The automatic check's own repairs: nothing for the client to do while they run.
const repairing = variant => ['Keyframes', 'Rewriting', 'Locations'].includes(variant.status);
// Scene names in the reviewer's language; production keeps the English originals.
const sceneName = (variant, number, english) => variant.script?.scenes?.[number - 1]?.display_name || tr(english || `Scene ${number}`, `Cảnh ${number}`);
const shortNote = note => String(note).split(/ Faulty action:| Replace its preparation/)[0];
const key = (batch, variant, scene) => `${batch.name}:${variant.index}:${scene}`;
const canRevise = (batch, variant) => batch.status !== 'Cancelled' && variant.script?.scenes && (waiting.includes(variant.status) || (variant.status === 'Needs Attention' && !variant.generation_request));
const notes = (batch, variant) => Object.entries(drafts)
  .filter(([k, text]) => k.startsWith(`${batch.name}:${variant.index}:`) && String(text).trim())
  .map(([k, text]) => ({ scene: Number(k.split(':')[2]) || null, text: String(text).trim() }));
// What the reviewer should do now, in one sentence; the panel below holds the controls.
function nextStep(batch, variant) {
  const calm = 'border-outline-border bg-surface-muted/40';
  const ask = 'border-amber-300 bg-amber-50/60 dark:bg-amber-950/40';
  const n = variant.pictures?.length || 0;
  if (variant.status === 'Completed') return { tone: 'border-emerald-300 bg-emerald-50/60 dark:bg-emerald-950/40', title: tr('Your video is ready.', 'Video đã xong.'), detail: tr('Watch it, leave comments and download it below.', 'Xem, góp ý và tải video ở bên dưới.') };
  if (variant.status === 'Pictures Ready') return { tone: ask, title: tr(`Check the ${n} scene pictures below.`, `Hãy xem ${n} hình cảnh bên dưới.`), detail: tr('If the product, label and character match your photos, press "Approve pictures & make video". Otherwise draw a picture again or add a note.', 'Nếu sản phẩm, nhãn và nhân vật giống ảnh của bạn, bấm "Duyệt hình và tạo video". Nếu chưa, bấm "Vẽ lại" hoặc thêm ghi chú.') };
  if (variant.status === 'Script Ready') return { tone: ask, title: tr('Check the storyboard below.', 'Hãy xem bảng phân cảnh bên dưới.'), detail: tr('Press "Make this video" when it is right, or add notes and rewrite it.', 'Bấm "Tạo video này" nếu đã ổn, hoặc thêm ghi chú để viết lại.') };
  if (variant.status === 'Needs Attention' && variant.held_clips?.length && batch.delivery_mode !== 'automatic') return { tone: ask, title: tr(`Watch the ${variant.held_clips.length} clips below.`, `Hãy xem ${variant.held_clips.length} đoạn clip bên dưới.`), detail: tr('The automatic check was not sure about these. For each clip choose "Use" if the action, character and product look right, or "Make again", then press Done.', 'Máy chưa chắc chắn về các clip này. Với mỗi clip, chọn "Dùng" nếu hành động, nhân vật và sản phẩm đúng, hoặc "Làm lại", rồi bấm Xong.') };
  if (variant.status === 'Needs Attention') return { tone: 'border-rose-300 bg-rose-50/60 dark:bg-rose-950/40', title: friendlyError(variant), detail: '' };
  if (variant.status === 'Cancelled') return { tone: calm, title: tr('This video was stopped.', 'Video này đã dừng.'), detail: '' };
  return { tone: calm, title: label(variant.status) + '…', detail: tr('This runs on its own; you can leave this page and come back later.', 'Hệ thống tự làm; bạn có thể rời trang và quay lại sau.') };
}
// The automatic check's English findings, in the reviewer's language.
const findingText = text => /product print not locked/i.test(text) ? tr('The pack moved too much to keep its exact print: compare the label with your product photo.', 'Gói giấy di chuyển nhiều nên chưa giữ được nhãn gốc: hãy so nhãn với ảnh sản phẩm.')
  : /passes through|no visible support|rests on the advertised product|stands on the advertised product/i.test(text) ? tr('The character is not placed physically right (it passes through furniture or has no real support).', 'Nhân vật đặt chưa đúng vật lý (xuyên qua đồ vật hoặc không có điểm tựa).')
  : /larger than the furniture/i.test(text) ? tr('The character is too big for the furniture it uses.', 'Nhân vật quá to so với đồ vật đang dùng.')
  : /Critical style/i.test(text) ? tr('This scene is drawn as a flat 2D picture instead of the 3D look of your photos.', 'Cảnh này bị vẽ phẳng 2D thay vì giống ảnh 3D của bạn.')
  : /product packages are drawn/i.test(text) ? tr('More than one product pack appears.', 'Xuất hiện nhiều hơn một gói sản phẩm.')
  : /breaks the scene rule/i.test(text) ? tr('The scene breaks one of its own rules.', 'Cảnh chưa đúng quy tắc của chính nó.')
  : /surface remains|remains (wet|dusty|dirty)|not visibly|no visible/i.test(text) ? tr('The result of the action is not clearly visible.', 'Kết quả của hành động chưa thấy rõ.')
  : /hand|human/i.test(text) ? tr('A human hand appears that should not be there.', 'Có bàn tay người xuất hiện không đúng.')
  : /temporal evidence|uncertain|could not (be )?(confirm|verif)/i.test(text) ? tr('The automatic check could not confirm the action: watch the clip.', 'Máy chưa xác nhận được hành động trong clip: hãy xem clip.')
  : tr(String(text).slice(0, 160), 'Máy chưa chắc chắn về cảnh này: hãy xem kỹ trước khi dùng.');
// Several findings often say the same thing once translated.
const findingLines = findings => [...new Set((findings || []).map(findingText))];
function friendlyError(variant) {
  const stage = variant.resume_stage || '';
  if (stage === 'Planning') return variant.script
    ? tr('The AI could not finish a usable script. Try again for a new story, or add notes.', 'AI chưa viết được kịch bản dùng được. Thử lại để có câu chuyện mới, hoặc thêm ghi chú.')
    : tr('The AI could not write a usable script this time. Try again for a new story.', 'Lần này AI chưa viết được kịch bản dùng được. Thử lại để có câu chuyện mới.');
  if (String(variant.error || '').startsWith('Scene rewrite failed')) return tr('The AI could not rewrite the noted scenes. Press "Try again" to keep the current pictures, or change your notes.', 'AI chưa viết lại được các cảnh có ghi chú. Bấm "Thử lại" để giữ hình hiện tại, hoặc sửa ghi chú.');
  if (['Keyframes', 'Locations'].includes(stage)) return tr('Some scene pictures could not be drawn. Press "Try again".', 'Một số hình cảnh chưa vẽ được. Bấm "Thử lại".');
  if (stage === 'Rendering') return tr('Some scenes did not pass the automatic quality check. Press "Make held scenes again" to redo only those scenes.', 'Một số cảnh chưa qua kiểm tra chất lượng tự động. Bấm "Tạo lại các cảnh bị giữ" để làm lại riêng các cảnh đó.');
  return tr('This step did not finish. Try again, or open the video to see what happened.', 'Bước này chưa hoàn tất. Thử lại, hoặc mở video để xem chi tiết.');
}
async function refresh() {
  const current = ++epoch;
  try {
    const result = await call('joymedia.api.creative.get_project_batches', { project_name: props.project });
    if (current !== epoch) return;
    batches.value = result || []; error.value = '';
    emit('loaded', { count: batches.value.length, focused: focused.value.length > 0 });
  } catch (e) {
    if (current === epoch) error.value = errorMessage(e, 'Could not load video variants.');
  }
  if (current === epoch) timer = setTimeout(refresh, batches.value.some(active) ? 5000 : 30000);
}
async function act(method, args, fallback) {
  if (busy.value) return;
  busy.value = true;
  try {
    await call(method, args);
    clearTimeout(timer); await refresh();
  } catch (e) { error.value = errorMessage(e, fallback); }
  finally { busy.value = false; }
}
const retry = (batch, variant) => act('joymedia.api.creative.retry_product_variant', { batch_name: batch.name, index: variant.index }, 'Could not resume the variant.');
const render = (batch, variant) => act('joymedia.api.creative.render_product_variant', { batch_name: batch.name, index: variant.index }, 'Could not start the video.');
const scenePrompts = reactive({});
const openRetry = ref('');
// Once the finished video plays above, progress and "done" banners only repeat its badge.
const finishedVideo = variant => Boolean(variant.video) && variant.status === 'Completed';
const readyScenes = variant => (variant.preview_scenes || []).filter(scene => scene.ready).length;
const sceneKey = (batch, variant, shot) => `retry:${batch.name}:${variant.index}:${shot}`;
async function retryScene(batch, variant, scene) {
  const key = sceneKey(batch, variant, scene.shot);
  const instruction = String(scenePrompts[key] || '').trim();
  await act('joymedia.api.creative.retry_variant_scene_with_prompt', {
    batch_name: batch.name, index: variant.index, shot_name: scene.shot, instruction,
  }, 'Could not revise and retry this scene.');
  if (!error.value) delete scenePrompts[key];
}
async function revise(batch, variant) {
  const list = notes(batch, variant);
  await act('joymedia.api.creative.revise_product_variant', { batch_name: batch.name, index: variant.index, notes: JSON.stringify(list) }, 'Could not rewrite the script.');
  if (!error.value) for (const k of Object.keys(drafts)) if (k.startsWith(`${batch.name}:${variant.index}:`)) delete drafts[k];
}
const approvePictures = (batch, variant) => act('joymedia.api.creative.approve_variant_pictures', { batch_name: batch.name, index: variant.index }, 'Could not approve the pictures.');
const redraw = (batch, variant, picture) => act('joymedia.api.creative.redraw_variant_picture', { batch_name: batch.name, index: variant.index, shot_name: picture.shot }, 'Could not draw the picture again.');
// Clip review works like a photo picker: each clip is marked Use or Make again, then one Done applies all.
// Watching the clip and choosing Use is the review; the note is optional.
const choices = reactive({}), broken = reactive({});
const playable = clip => !broken[clip.shot];
const usable = clip => clip.reviewable && playable(clip);
const choice = clip => (usable(clip) ? choices[clip.shot] : 'redo');
const decide = (clip, value) => { choices[clip.shot] = value; };
const undecided = variant => (variant.held_clips || []).filter(clip => !choice(clip));
// Storyboard helpers: one colour per scene ties the timeline segment to its panel.
const HUES = [
  { bar: 'bg-rio-500', edge: 'border-rio-500' }, { bar: 'bg-teal-500', edge: 'border-teal-500' },
  { bar: 'bg-emerald-500', edge: 'border-emerald-500' }, { bar: 'bg-amber-500', edge: 'border-amber-500' },
  { bar: 'bg-rose-500', edge: 'border-rose-500' }, { bar: 'bg-violet-500', edge: 'border-violet-500' },
  { bar: 'bg-slate-500', edge: 'border-slate-500' }, { bar: 'bg-orange-500', edge: 'border-orange-500' },
];
const hue = i => HUES[i % HUES.length];
// Rows without a lone panel: up to six scenes in one row, otherwise even rows of four or five.
const COLUMNS = { 4: 'lg:grid-cols-4', 5: 'lg:grid-cols-5', 6: 'lg:grid-cols-6' };
const columns = count => COLUMNS[count <= 6 ? Math.max(4, count) : count % 4 === 0 || count % 5 === 1 || count % 5 === 2 ? 4 : 5];
const expanded = reactive({});
const totalSeconds = variant => Math.round(variant.script.scenes.reduce((sum, scene) => sum + (Number(scene.duration_seconds) || 0), 0));
const cameraTags = scene => cameraText(scene).split(' · ').filter(Boolean);
const sceneId = (batch, variant, number) => `scene-${batch.name}-${variant.index}-${number}`;
const jump = (batch, variant, number) => document.getElementById(sceneId(batch, variant, number))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
// The scene's first frame, so the script reads like a storyboard.
const frame = (variant, number) => variant.pictures?.find(p => Number(p.shot_number) === number)?.url;
const poster = (variant, clip) => variant.pictures?.find(p => p.shot === clip.shot)?.url || undefined;
function doneLabel(variant) {
  const clips = variant.held_clips || [];
  const use = clips.filter(c => choice(c) === 'use').length, redo = clips.filter(c => choice(c) === 'redo').length;
  if (use && redo) return tr(`Done — use ${use}, make ${redo} again`, `Xong — dùng ${use} clip, làm lại ${redo} cảnh`);
  if (redo) return tr(`Done — make ${redo} scene(s) again`, `Xong — làm lại ${redo} cảnh`);
  return tr(`Done — use ${use} clip(s) and continue`, `Xong — dùng ${use} clip và làm tiếp`);
}
// Accepted clips are kept; the rest are rendered again, or the video goes on to editing and music.
async function applyChoices(batch, variant) {
  if (busy.value) return;
  busy.value = true; error.value = '';
  try {
    for (const clip of variant.held_clips.filter(c => choice(c) === 'use')) {
      const note = String(drafts['clip:' + clip.shot] || '').trim() || tr('Watched and accepted by the reviewer.', 'Người duyệt đã xem và chấp nhận.');
      await call('joymedia.api.creative.accept_held_clip', { batch_name: batch.name, index: variant.index, shot_name: clip.shot, attempt_name: clip.attempt || null, asset_version: clip.asset_version || null, note });
      delete drafts['clip:' + clip.shot]; delete choices[clip.shot];
    }
    for (const clip of variant.held_clips) delete choices[clip.shot];
    clearTimeout(timer); await refresh();
    const fresh = focused.value.find(item => item.batch.name === batch.name && item.variant.index === variant.index)?.variant;
    if (fresh?.status === 'Needs Attention' && fresh.resume_stage === 'Rendering') {
      await call('joymedia.api.creative.retry_product_variant', { batch_name: batch.name, index: variant.index });
      clearTimeout(timer); await refresh();
    }
  } catch (e) { error.value = errorMessage(e, 'Could not apply your choices.'); }
  finally { busy.value = false; }
}
const cancel = batch => act('joymedia.api.creative.cancel_product_batch', { batch_name: batch.name }, 'Could not stop the batch.');
watch(() => props.project, () => { clearTimeout(timer); refresh(); }, { immediate: true });
onUnmounted(() => { epoch++; clearTimeout(timer); });
</script>
