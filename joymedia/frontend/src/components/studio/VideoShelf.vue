<template>
  <section v-if="videos.length" class="rounded-xl border border-outline-border p-3" data-test="video-shelf">
    <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
      <h2 class="text-sm font-semibold">{{ tr('Videos in this project', 'Các video trong dự án') }} · {{ videos.length }}</h2>
      <div class="flex items-center gap-2 text-xs">
        <button v-if="!readonly" class="jm-button-secondary" data-test="generate-from-references" :disabled="busy" @click="generate">{{ pendingBatch ? tr('Starting your video…', 'Đang khởi tạo video…') : tr('New video from these references', 'Tạo video mới từ ảnh tham chiếu') }}</button>
        <span v-if="comparing.length < 2" class="text-ink-muted">{{ tr('Tick two finished videos to compare them', 'Chọn hai video đã xong để so sánh') }}</span>
        <button v-else class="jm-button-primary" data-test="open-compare" @click="compareOpen = true">{{ tr('Compare', 'So sánh') }}</button>
      </div>
    </div>
    <p v-if="error" class="text-xs text-rose-500 mb-2">{{ error }}</p>
    <ol class="flex gap-3 overflow-x-auto pb-1">
      <li v-for="video in videos" :key="video.name" class="relative w-44 shrink-0 rounded-lg border p-2 flex flex-col gap-1" :class="video.is_open ? 'border-indigo-500 ring-1 ring-indigo-500' : 'border-outline-border'" :data-video="video.name">
        <button v-if="!readonly && !video.is_working_edit" class="absolute right-1 top-1 z-10 grid h-6 w-6 place-items-center rounded-full bg-surface-card/90 text-ink-muted hover:text-rose-600" :title="tr('Remove from project', 'Bỏ khỏi dự án')" :aria-label="tr('Remove from project', 'Bỏ khỏi dự án')" :disabled="busy" data-test="remove-video" @click.stop="remove(video)">✕</button>
        <button class="text-left" :aria-current="video.is_open ? 'page' : undefined" @click="open(video)">
          <video v-if="video.video" :src="video.video + '#t=1'" class="w-full aspect-video rounded bg-black object-contain" preload="metadata" muted playsinline />
          <div v-else class="w-full aspect-video rounded bg-surface-muted flex items-center justify-center text-[11px] text-ink-muted px-2 text-center">{{ statusLabel(video) }}</div>
          <p class="text-xs font-medium mt-1 line-clamp-2">{{ video.label }}</p>
        </button>
        <p class="text-[11px] text-ink-muted">{{ statusLabel(video) }}<span v-if="video.is_working_edit" class="ml-1 text-amber-600 font-semibold">★ {{ tr('Chosen', 'Đã chọn') }}</span></p>
        <div class="flex items-center justify-between gap-1 text-[11px]">
          <label v-if="video.video" class="flex items-center gap-1"><input type="checkbox" :checked="comparing.includes(video)" :disabled="comparing.length >= 2 && !comparing.includes(video)" @change="pick(video)" />{{ tr('Compare', 'So sánh') }}</label>
          <button v-if="!video.is_working_edit && video.video && !readonly" class="underline" :disabled="busy" data-test="choose-video" @click="choose(video)">{{ tr('Choose this one', 'Chọn bản này') }}</button>
        </div>
      </li>
    </ol>
    <CompareVideos v-if="compareOpen" :pair="comparing" @close="compareOpen = false" />
  </section>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { call } from 'frappe-ui';
import { tr } from '../../stores/i18n';
import { errorMessage } from '../../utils/errors';
import CompareVideos from './CompareVideos.vue';

const props = defineProps({ project: { type: String, required: true }, readonly: Boolean });
const router = useRouter();
const data = ref(null), comparing = ref([]), compareOpen = ref(false), busy = ref(false), error = ref('');
const videos = computed(() => data.value?.videos || []);
const pendingBatch = ref('');
let timer, epoch = 0;
// An AI-written video reports its batch stage; any other video its project status.
const STATUS = {
  Queued: ['Waiting to start', 'Đang chờ'],
  Planning: ['Writing the script', 'Đang viết kịch bản'],
  Rewriting: ['Rewriting scenes', 'Đang viết lại cảnh'],
  'Script Ready': ['Script ready to read', 'Kịch bản chờ đọc'],
  Locations: ['Drawing scene pictures', 'Đang vẽ hình cảnh'],
  Keyframes: ['Drawing scene pictures', 'Đang vẽ hình cảnh'],
  'Pictures Ready': ['Pictures waiting for you', 'Hình chờ bạn duyệt'],
  Rendering: ['Making the video', 'Đang tạo video'],
  Finishing: ['Editing and adding music', 'Đang dựng và thêm nhạc'],
  Draft: ['Storyboard ready', 'Đã có bảng phân cảnh'],
  Generating: ['Making the video', 'Đang tạo video'],
  'Needs Attention': ['Needs your help', 'Cần bạn hỗ trợ'],
  Completed: ['Ready to watch', 'Sẵn sàng xem'],
  Cancelled: ['Stopped', 'Đã dừng'],
};
const statusLabel = (video) => {
  const status = video.video && video.status === 'Completed' ? 'Completed' : video.stage || video.status;
  return tr(...(STATUS[status] || [status, status]));
};

async function load() {
  const current = ++epoch;
  try {
    const result = await call('joymedia.services.project.versions.get_videos', { project_name: props.project });
    if (current !== epoch) return;
    data.value = result;
    comparing.value = comparing.value.map((v) => videos.value.find((x) => x.name === v.name)).filter(Boolean);
    if (pendingBatch.value) {
      const batch = await call('joymedia.api.creative.get_product_batch', { batch_name: pendingBatch.value });
      if (current !== epoch) return;
      const variant = batch.variants?.find(v => v.project);
      if (variant) {
        pendingBatch.value = ''; busy.value = false;
        router.push('/projects/' + variant.project);
      } else if (['Needs Attention', 'Cancelled'].includes(batch.status)) {
        pendingBatch.value = ''; busy.value = false;
        error.value = batch.variants?.[0]?.error || tr('The video could not start.', 'Chưa khởi tạo được video.');
      }
    }
  } catch (e) {
    if (current === epoch) error.value = errorMessage(e);
  }
  if (current === epoch && (pendingBatch.value || videos.value.some(v => ['Queued', 'Planning', 'Locations', 'Keyframes', 'Rendering', 'Finishing', 'Exporting', 'Generating'].includes(v.stage || v.status)))) timer = setTimeout(load, 5000);
}
async function generate() {
  if (busy.value) return;
  busy.value = true; error.value = '';
  try {
    const result = await call('joymedia.api.creative.create_product_batch', { source_project: props.project, count: 1, auto_render: true, delivery_mode: 'automatic' });
    pendingBatch.value = result.batch;
    clearTimeout(timer); await load();
  } catch (e) { busy.value = false; error.value = errorMessage(e); }
}
const open = (video) => { if (!video.is_open) router.push('/projects/' + video.name); };
function pick(video) {
  comparing.value = comparing.value.includes(video) ? comparing.value.filter((v) => v !== video) : [...comparing.value, video];
}
// Removal archives the video: it leaves the shelf and can be restored from Version history.
async function remove(video) {
  if (!window.confirm(tr(`Remove "${video.label}" from this project? You can restore it from Version history.`, `Bỏ "${video.label}" khỏi dự án? Bạn có thể khôi phục trong Lịch sử phiên bản.`))) return;
  busy.value = true;
  error.value = '';
  try {
    await call('joymedia.api.projects.archive_project', { project_name: video.name });
    comparing.value = comparing.value.filter((v) => v.name !== video.name);
    if (video.is_open) router.push('/projects/' + data.value.root);
    else await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function choose(video) {
  busy.value = true;
  error.value = '';
  try {
    await call('joymedia.services.project.versions.set_working_edit', { project_name: props.project, edit_name: video.name, expected_current: data.value.working_edit });
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
watch(() => props.project, () => { clearTimeout(timer); load(); }, { immediate: true });
onUnmounted(() => { epoch++; clearTimeout(timer); });
</script>
