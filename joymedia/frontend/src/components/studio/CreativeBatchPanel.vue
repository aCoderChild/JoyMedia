<template>
  <section v-if="batches.length" class="rounded-xl border border-outline-border p-4 space-y-4" data-test="creative-batches">
    <h2 class="font-semibold">{{ focus ? tr('This video', 'Video này') : tr('AI video variants', 'Các video AI tự tạo') }}</h2>
    <p v-if="!focus" class="text-sm text-ink-muted" data-test="choose-video-hint">{{ tr('Choose a video above to see its script, pictures and progress.', 'Chọn một video ở trên để xem kịch bản, hình cảnh và tiến độ.') }}</p>
    <article v-for="batch in shown" :key="batch.name" class="space-y-3">
      <div class="flex justify-between gap-3 text-xs text-ink-muted">
        <span>{{ tr('Batch', 'Loạt') }} {{ batch.name }} · {{ label(batch.status) }}</span>
        <button v-if="active(batch)" class="underline" @click="cancel(batch)">{{ tr('Stop batch', 'Dừng loạt video') }}</button>
      </div>
      <div v-for="variant in videos(batch).filter(v => v.project === focus)" :key="variant.index" class="rounded-lg bg-surface-card p-3 text-sm space-y-3" :data-test="'variant-' + variant.index">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <p class="font-medium">{{ tr('Video', 'Video') }} {{ variant.index }} · {{ variant.title || variant.script?.title || (working(variant) ? tr('Writing a new story…', 'Đang viết câu chuyện mới…') : tr('No script yet', 'Chưa có kịch bản')) }}</p>
          <span class="rounded-full px-2 py-0.5 text-xs" :class="pill(variant.status)">{{ label(variant.status) }}</span>
        </div>
        <ol class="flex gap-1" :aria-label="tr('Progress', 'Tiến độ')">
          <li v-for="(step, i) in steps" :key="step.key" class="h-1.5 flex-1 rounded-full" :class="i < progress(variant) ? 'bg-indigo-500' : i === progress(variant) && working(variant) ? 'bg-indigo-300 animate-pulse' : i === progress(variant) && variant.status === 'Needs Attention' ? 'bg-rose-400' : 'bg-surface-muted'" :title="step.label" />
        </ol>
        <p class="text-[11px] text-ink-muted">{{ steps.map(s => s.label).join(' → ') }}</p>
        <p v-if="variant.script?.logline" class="text-xs text-ink-secondary">{{ variant.script.logline }}</p>
        <p v-if="variant.product" class="text-[11px] text-ink-muted">{{ tr('Product', 'Sản phẩm') }}: {{ variant.product }}</p>

        <video v-if="variant.video" :src="variant.video" controls playsinline preload="metadata" class="w-full max-w-xs rounded-lg bg-black" />

        <div v-if="variant.script?.director_notes?.length" class="rounded-lg border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100" data-test="director-notes">
          <p class="font-semibold">{{ tr('Production notes', 'Ghi chú sản xuất') }}</p>
          <ul class="list-disc pl-4"><li v-for="(note, i) in variant.script.director_notes" :key="i">{{ shortNote(note) }}</li></ul>
        </div>

        <div v-if="variant.pictures?.some(p => p.url) || variant.status === 'Pictures Ready'" class="space-y-2" data-test="picture-review">
          <p v-if="batch.delivery_mode === 'automatic'" class="text-xs text-ink-secondary">{{ tr('Storyboard first frames appear here as they finish. Video generation continues automatically.', 'Ảnh đầu của từng cảnh xuất hiện tại đây khi tạo xong. Hệ thống tự tiếp tục tạo video.') }}</p>
          <p v-else class="text-xs text-ink-secondary">{{ tr('Check each scene picture: the product, its label and the character must match your photos. Approve to make the video, or draw a picture again.', 'Kiểm tra từng hình cảnh: sản phẩm, nhãn và nhân vật phải giống ảnh của bạn. Duyệt để tạo video, hoặc vẽ lại hình.') }}</p>
          <ol class="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <li v-for="picture in variant.pictures" :key="picture.shot" class="rounded-lg border border-outline-border p-1.5 text-xs" :class="picture.note ? 'border-amber-300' : ''">
              <img v-if="picture.url" :src="picture.url" :alt="picture.shot_name" class="h-48 w-full rounded object-contain bg-surface-muted" loading="lazy" />
              <div v-else class="grid h-48 w-full place-items-center rounded bg-surface-muted text-ink-muted">{{ tr('No picture yet', 'Chưa có hình') }}</div>
              <p class="mt-1 font-medium truncate" :title="picture.shot_name">{{ picture.shot_number }}. {{ picture.shot_name }}</p>
              <p v-if="picture.label_unlocked" class="font-medium text-rose-600">{{ tr('Product label not locked (a paw covers it): compare the label with your product photo.', 'Nhãn sản phẩm chưa được khoá (bị tay che): hãy so nhãn với ảnh sản phẩm.') }}</p>
              <p v-if="picture.note" class="text-amber-700 dark:text-amber-300">{{ pictureNote(picture.note) }}</p>
              <div v-if="variant.status === 'Pictures Ready'" class="flex gap-2">
                <button class="underline text-ink-muted" :disabled="busy" @click="redraw(batch, variant, picture)">{{ tr('Draw again', 'Vẽ lại') }}</button>
                <button v-if="!(key(batch, variant, picture.shot_number) in drafts)" class="underline text-ink-muted" @click="drafts[key(batch, variant, picture.shot_number)] = ''">{{ tr('Add note', 'Thêm ghi chú') }}</button>
              </div>
              <textarea v-if="key(batch, variant, picture.shot_number) in drafts" v-model="drafts[key(batch, variant, picture.shot_number)]" rows="2" class="mt-1 w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('What should change in this scene?', 'Cảnh này cần sửa gì?')" />
            </li>
          </ol>
        </div>

        <div v-if="variant.held_clips?.length" class="space-y-2" data-test="clip-review">
          <p class="text-xs text-ink-secondary">{{ tr('These scenes need your eyes: the automatic check could not confirm them. Watch each clip and use it if the action, character and product look right; otherwise render it again.', 'Các cảnh này cần bạn xem: kiểm tra tự động chưa xác nhận được. Xem từng clip và dùng nếu hành động, nhân vật và sản phẩm đúng; nếu không thì tạo lại.') }}</p>
          <ol class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <li v-for="clip in variant.held_clips" :key="clip.shot" class="rounded-lg border border-amber-300 p-1.5 text-xs">
              <video v-if="clip.url" :src="clip.url" controls playsinline preload="metadata" class="h-56 w-full rounded bg-black object-contain" />
              <div v-else class="grid h-24 place-items-center rounded bg-surface-muted text-ink-muted">{{ tr('No clip yet', 'Chưa có clip') }}</div>
              <p class="mt-1 font-medium">{{ clip.shot_number }}. {{ clip.shot_name }}</p>
              <p v-for="(finding, i) in clip.findings" :key="i" class="text-amber-700 dark:text-amber-300">{{ finding }}</p>
              <template v-if="clip.reviewable">
                <textarea v-model="drafts['clip:' + clip.shot]" rows="2" class="mt-1 w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('What did you check? e.g. the bear lifts the pack, label stays correct', 'Bạn đã kiểm tra gì? vd. gấu nhấc gói giấy, nhãn vẫn đúng')" />
                <button class="jm-button-secondary mt-1" :disabled="busy || !String(drafts['clip:' + clip.shot] || '').trim()" @click="useClip(batch, variant, clip)">{{ tr('Looks right — use this clip', 'Đúng rồi — dùng clip này') }}</button>
              </template>
              <p v-else-if="clip.url" class="text-ink-muted">{{ tr('This clip has a problem that must be rendered again.', 'Clip này có lỗi, cần tạo lại.') }}</p>
            </li>
          </ol>
        </div>

        <details v-if="variant.script?.scenes" :open="variant.status === 'Script Ready'" class="text-xs">
          <summary class="cursor-pointer font-medium text-ink-primary">{{ tr('Read the script', 'Xem kịch bản') }} ({{ variant.script.scenes.length }} {{ tr('scenes', 'cảnh') }})</summary>
          <ol class="mt-2 space-y-2">
            <li v-for="(scene, i) in variant.script.scenes" :key="i" class="rounded-lg border border-outline-border p-2">
              <p class="font-medium">{{ i + 1 }}. {{ scene.beat_name }} <span class="text-ink-muted">· {{ Number(scene.duration_seconds).toFixed(1) }}s</span></p>
              <p class="text-ink-muted" data-test="scene-camera">🎥 {{ cameraText(scene) }}</p>
              <p class="text-ink-secondary">{{ scene.visual_camera }}</p>
              <p class="text-ink-secondary">{{ plainAction(scene.action) }}</p>
              <p v-if="scene.voice_over" class="mt-1"><span class="text-ink-muted">{{ tr('Voice-over', 'Lời thoại') }}:</span> {{ scene.voice_over }}</p>
              <p v-if="scene.on_screen_text" class="mt-0.5"><span class="text-ink-muted">{{ tr('On screen', 'Chữ trên hình') }}:</span> {{ scene.on_screen_text }}</p>
              <template v-if="canRevise(batch, variant)">
                <button v-if="!(key(batch, variant, i + 1) in drafts)" class="mt-1 underline text-ink-muted" @click="drafts[key(batch, variant, i + 1)] = ''">{{ tr('Add note', 'Thêm ghi chú') }}</button>
                <textarea v-else v-model="drafts[key(batch, variant, i + 1)]" rows="2" class="mt-1 w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('What should change in this scene?', 'Cảnh này cần sửa gì?')" />
              </template>
            </li>
          </ol>
          <textarea v-if="canRevise(batch, variant)" v-model="drafts[key(batch, variant, 0)]" rows="2" class="mt-2 w-full rounded border border-outline-border bg-transparent p-1" :placeholder="tr('Notes on the whole script (optional)', 'Ghi chú cho cả kịch bản (tuỳ chọn)')" />
        </details>

        <div class="flex flex-wrap items-center gap-2 text-xs">
          <button v-if="variant.status === 'Script Ready' && batch.status !== 'Cancelled'" class="jm-button-primary" :disabled="busy" @click="render(batch, variant)">{{ tr('Make this video', 'Tạo video này') }}</button>
          <button v-if="variant.status === 'Pictures Ready' && batch.status !== 'Cancelled'" class="jm-button-primary" :disabled="busy || variant.pictures?.some(p => !p.url)" @click="approvePictures(batch, variant)">{{ tr('Approve pictures & make video', 'Duyệt hình và tạo video') }}</button>
          <button v-if="canRevise(batch, variant)" class="jm-button-secondary" :disabled="busy || !notes(batch, variant).length" @click="revise(batch, variant)">{{ tr('Rewrite with my notes', 'Viết lại theo ghi chú') }}<span v-if="notes(batch, variant).length"> ({{ notes(batch, variant).length }})</span></button>
          <button v-if="variant.status === 'Needs Attention' && batch.status !== 'Cancelled'" class="jm-button-secondary" :disabled="busy" @click="retry(batch, variant)">{{ variant.resume_stage === 'Rendering' && variant.held_clips && !variant.held_clips.length ? tr('Continue to editing & music', 'Tiếp tục dựng & thêm nhạc') : variant.held_clips?.length ? tr('Render held scenes again', 'Tạo lại các cảnh bị giữ') : tr('Try again', 'Thử lại') }}</button>
          <RouterLink v-if="variant.project && (variant.script || variant.video)" :to="'/projects/' + variant.project" class="underline">{{ variant.video ? tr('Review & comment on the video', 'Duyệt và góp ý video') : tr('Open storyboard', 'Mở bảng phân cảnh') }}</RouterLink>
          <a v-if="variant.workbook" :href="variant.workbook" download class="underline">{{ tr('Download script (.xlsx)', 'Tải kịch bản (.xlsx)') }}</a>
          <a v-if="variant.video" :href="variant.video" download class="underline">{{ tr('Download video', 'Tải video') }}</a>
        </div>
        <div v-if="variant.error" class="text-xs text-rose-500" role="alert">
          <p>{{ friendlyError(variant) }}</p>
          <details><summary class="cursor-pointer text-ink-muted">{{ tr('Technical details', 'Chi tiết kỹ thuật') }}</summary><p class="whitespace-pre-wrap break-words text-ink-muted">{{ variant.error }}</p></details>
        </div>
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
// `focus` is the one video whose details are shown; the shelf above chooses it.
const props = defineProps({ project: { type: String, required: true }, focus: { type: String, default: '' } });
const emit = defineEmits(['loaded']);
const batches = ref([]), error = ref(''), busy = ref(false);
const drafts = reactive({});
let timer, epoch = 0;
const active = batch => ['Queued', 'Planning', 'Rendering', 'Finishing'].includes(batch.status);
// Current work first: active batches and the two most recent; older ones collapse.
const shown = computed(() => batches.value.filter(b => props.focus && b.variants.some(v => v.project === props.focus)));
// A stopped batch's unfinished videos are stopped too, whatever stage they had reached.
const videos = batch => batch.variants.map(v => batch.status === 'Cancelled' && v.status !== 'Completed' ? { ...v, status: 'Cancelled', error: '' } : v);
const steps = [
  { key: 'script', label: tr('Script', 'Kịch bản') },
  { key: 'pictures', label: tr('Scene pictures', 'Hình cảnh') },
  { key: 'video', label: tr('Video', 'Video') },
  { key: 'music', label: tr('Edit & music', 'Dựng & nhạc') },
  { key: 'ready', label: tr('Ready', 'Hoàn tất') },
];
const stageIndex = { Queued: 0, Planning: 0, Rewriting: 1, 'Script Ready': 1, Locations: 1, Keyframes: 1, 'Pictures Ready': 2, Rendering: 2, Finishing: 3, Exporting: 3, Completed: 5 };
const progress = v => stageIndex[v.status === 'Needs Attention' ? v.resume_stage || 'Planning' : v.status] ?? 0;
const waiting = ['Script Ready', 'Pictures Ready'];
const working = v => ![...waiting, 'Completed', 'Needs Attention', 'Cancelled'].includes(v.status);
const pill = status => status === 'Completed' ? 'bg-emerald-100 text-emerald-800' : status === 'Needs Attention' ? 'bg-rose-100 text-rose-800' : waiting.includes(status) ? 'bg-amber-100 text-amber-900' : 'bg-indigo-100 text-indigo-800';
const label = status => ({
  Queued: tr('Queued', 'Đang chờ'), Planning: tr('Writing the script', 'Đang viết kịch bản'),
  Locations: tr('Preparing the setting', 'Đang chuẩn bị bối cảnh'),
  Keyframes: tr('Drawing scene pictures', 'Đang vẽ hình cảnh'), Rendering: tr('Making the video', 'Đang tạo video'),
  Finishing: tr('Editing and adding music', 'Đang dựng và thêm nhạc'), Completed: tr('Video ready', 'Video đã xong'),
  Exporting: tr('Exporting video', 'Đang xuất video'),
  'Needs Attention': tr('Needs your help', 'Cần bạn xem lại'), 'Scripts Ready': tr('Scripts ready to review', 'Kịch bản chờ duyệt'),
  'Script Ready': tr('Script ready to review', 'Kịch bản chờ duyệt'), Cancelled: tr('Stopped', 'Đã dừng'),
  'Pictures Ready': tr('Pictures ready to review', 'Hình cảnh chờ duyệt'), Rewriting: tr('Rewriting the noted scenes', 'Đang viết lại các cảnh có ghi chú'), 'Awaiting Review': tr('Waiting for your review', 'Đang chờ bạn duyệt'),
}[status] || status);
// Camera choices in plain words, from the shared storyboard shot vocabulary.
const words = value => String(value || '').replace(/_/g, ' ');
const cameraText = scene => [words(scene.shot_framing), words(scene.shot_angle), words(scene.camera_move || 'static')].filter(Boolean).join(' · ');
const plainAction = text => String(text || '').split('\n').map(line => line.replace(/^\[[^\]]*\]\s*/, '').trim()).filter(Boolean).join(' ');
// Machine notes, in reviewer terms; the full text stays in the scene's evidence.
const pictureNote = note => /qualify this geometry/i.test(note) ? tr('Automatic checks passed; please confirm the pose and product contact look right.', 'Kiểm tra tự động đạt; hãy xác nhận tư thế và cách cầm sản phẩm hợp lý.')
  : /no picture/i.test(note) ? tr('This picture failed; draw it again.', 'Hình này bị lỗi; hãy vẽ lại.') : String(note).slice(0, 160);
const shortNote = note => String(note).split(/ Faulty action:| Replace its preparation/)[0];
const key = (batch, variant, scene) => `${batch.name}:${variant.index}:${scene}`;
const canRevise = (batch, variant) => batch.status !== 'Cancelled' && variant.script?.scenes && (waiting.includes(variant.status) || (variant.status === 'Needs Attention' && !variant.generation_request));
const notes = (batch, variant) => Object.entries(drafts)
  .filter(([k, text]) => k.startsWith(`${batch.name}:${variant.index}:`) && String(text).trim())
  .map(([k, text]) => ({ scene: Number(k.split(':')[2]) || null, text: String(text).trim() }));
function friendlyError(variant) {
  const stage = variant.resume_stage || '';
  if (stage === 'Planning') return variant.script
    ? tr('The AI could not finish a usable script. Try again for a new story, or add notes.', 'AI chưa viết được kịch bản dùng được. Thử lại để có câu chuyện mới, hoặc thêm ghi chú.')
    : tr('The AI could not write a usable script this time. Try again for a new story.', 'Lần này AI chưa viết được kịch bản dùng được. Thử lại để có câu chuyện mới.');
  if (['Keyframes', 'Locations'].includes(stage)) return tr('Some scene pictures need a look. Open the storyboard to check them, then try again.', 'Một số hình cảnh cần kiểm tra. Mở bảng phân cảnh để xem, rồi thử lại.');
  if (stage === 'Rendering') return tr('Some scenes did not pass the automatic quality check. Open the storyboard to review them, then try again.', 'Một số cảnh chưa qua kiểm tra chất lượng tự động. Mở bảng phân cảnh để xem, rồi thử lại.');
  return tr('This step did not finish. Try again, or open the video to see what happened.', 'Bước này chưa hoàn tất. Thử lại, hoặc mở video để xem chi tiết.');
}
async function refresh() {
  const current = ++epoch;
  try {
    const result = await call('joymedia.api.creative.get_project_batches', { project_name: props.project });
    if (current !== epoch) return;
    batches.value = result || []; error.value = '';
    emit('loaded', batches.value.length);
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
async function revise(batch, variant) {
  const list = notes(batch, variant);
  await act('joymedia.api.creative.revise_product_variant', { batch_name: batch.name, index: variant.index, notes: JSON.stringify(list) }, 'Could not rewrite the script.');
  if (!error.value) for (const k of Object.keys(drafts)) if (k.startsWith(`${batch.name}:${variant.index}:`)) delete drafts[k];
}
const approvePictures = (batch, variant) => act('joymedia.api.creative.approve_variant_pictures', { batch_name: batch.name, index: variant.index }, 'Could not approve the pictures.');
const redraw = (batch, variant, picture) => act('joymedia.api.creative.redraw_variant_picture', { batch_name: batch.name, index: variant.index, shot_name: picture.shot }, 'Could not draw the picture again.');
async function useClip(batch, variant, clip) {
  const key = 'clip:' + clip.shot;
  await act('joymedia.api.creative.accept_held_clip', { batch_name: batch.name, index: variant.index, shot_name: clip.shot, attempt_name: clip.attempt || null, asset_version: clip.asset_version || null, note: drafts[key] }, 'Could not use this clip.');
  if (!error.value) delete drafts[key];
}
const cancel = batch => act('joymedia.api.creative.cancel_product_batch', { batch_name: batch.name }, 'Could not stop the batch.');
watch(() => props.project, () => { clearTimeout(timer); refresh(); }, { immediate: true });
onUnmounted(() => { epoch++; clearTimeout(timer); });
</script>
