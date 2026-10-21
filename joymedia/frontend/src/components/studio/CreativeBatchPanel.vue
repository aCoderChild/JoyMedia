<template>
  <section v-if="batches.length" class="rounded-xl border border-outline-border p-4 space-y-4" data-test="creative-batches">
    <h2 class="font-semibold">{{ tr('AI video variants', 'Các video AI tự tạo') }}</h2>
    <article v-for="batch in batches" :key="batch.name" class="space-y-2">
      <div class="flex justify-between gap-3 text-sm">
        <span>{{ batch.name }} · {{ label(batch.status) }}</span>
        <button v-if="active(batch)" class="underline" @click="cancel(batch)">{{ tr('Stop batch', 'Dừng loạt video') }}</button>
      </div>
      <div v-for="variant in batch.variants" :key="variant.index" class="rounded-lg bg-surface-card p-3 text-sm space-y-1">
        <p>{{ variant.index }}. {{ variant.title || variant.script?.title || tr('Writing a new story…', 'Đang viết câu chuyện mới…') }} · {{ label(variant.status) }}</p>
        <p v-if="variant.script?.logline" class="text-xs text-ink-muted">{{ variant.script.logline }}</p>
        <div class="flex flex-wrap gap-4 text-xs">
          <RouterLink v-if="variant.project" :to="'/projects/' + variant.project" class="underline">{{ tr('Open version', 'Mở phiên bản') }}</RouterLink>
          <a v-if="variant.workbook" :href="variant.workbook" download class="underline">{{ tr('Download script', 'Tải kịch bản') }}</a>
          <a v-if="variant.video" :href="variant.video" class="underline">{{ tr('Watch video', 'Xem video') }}</a>
        </div>
        <button v-if="variant.status === 'Needs Attention' && batch.status !== 'Cancelled'" class="text-xs underline" @click="retry(batch, variant)">{{ tr('Retry after correction', 'Chạy lại sau khi sửa') }}</button>
        <p v-if="variant.error" class="text-xs text-rose-500">{{ variant.error }}</p>
      </div>
    </article>
    <p v-if="error" role="alert" class="text-xs text-rose-500">{{ error }}</p>
  </section>
</template>

<script setup>
import { onUnmounted, ref, watch } from 'vue';
import { call } from 'frappe-ui';
import { tr } from '../../stores/i18n';
import { errorMessage } from '../../utils/errors';
const props = defineProps({ project: { type: String, required: true } });
const batches = ref([]), error = ref('');
let timer, epoch = 0;
const active = batch => ['Queued', 'Planning', 'Rendering', 'Finishing'].includes(batch.status);
const label = status => ({
  Queued: tr('Queued', 'Đang chờ'), Planning: tr('Writing and planning', 'Đang viết và lập kế hoạch'),
  Locations: tr('Preparing shared settings', 'Đang chuẩn bị bối cảnh chung'),
  Keyframes: tr('Drawing scene references', 'Đang tạo hình cảnh'), Rendering: tr('Generating video', 'Đang tạo video'),
  Finishing: tr('Editing and adding music', 'Đang dựng và thêm nhạc'), Completed: tr('Video ready', 'Video đã xong'),
  Exporting: tr('Exporting video', 'Đang xuất video'),
  'Needs Attention': tr('Needs review', 'Cần kiểm tra'), 'Scripts Ready': tr('Scripts ready', 'Kịch bản đã xong'),
  'Script Ready': tr('Script ready', 'Kịch bản đã xong'), Cancelled: tr('Stopped', 'Đã dừng'),
}[status] || status);
async function refresh() {
  const current = ++epoch;
  try {
    const result = await call('joymedia.api.creative.get_project_batches', { project_name: props.project });
    if (current !== epoch) return;
    batches.value = result || []; error.value = '';
  } catch (e) {
    if (current === epoch) error.value = errorMessage(e, 'Could not load video variants.');
  }
  if (current === epoch) timer = setTimeout(refresh, batches.value.some(active) ? 5000 : 30000);
}
async function retry(batch, variant) {
  try {
    await call('joymedia.api.creative.retry_product_variant', { batch_name: batch.name, index: variant.index });
    clearTimeout(timer); await refresh();
  } catch (e) { error.value = errorMessage(e, 'Could not resume the variant.'); }
}
async function cancel(batch) {
  try {
    await call('joymedia.api.creative.cancel_product_batch', { batch_name: batch.name });
    clearTimeout(timer); await refresh();
  } catch (e) { error.value = errorMessage(e, 'Could not stop the batch.'); }
}
watch(() => props.project, () => { clearTimeout(timer); refresh(); }, { immediate: true });
onUnmounted(() => { epoch++; clearTimeout(timer); });
</script>
