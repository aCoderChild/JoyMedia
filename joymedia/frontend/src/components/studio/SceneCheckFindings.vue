<template>
  <Dialog :model-value="true" :title="tr('Scene review findings', 'Kết quả kiểm tra cảnh')" size="xl" @update:model-value="!$event && emit('close')">
    <template #default>
      <p class="mb-3 text-xs text-ink-muted">{{ tr('These are sampled observations. Product, logo and character approval is separate.', 'Đây là đánh giá trên các khung hình mẫu. Việc duyệt sản phẩm, logo và nhân vật được thực hiện riêng.') }}</p>
      <p v-if="loading" class="text-sm">{{ tr('Loading findings…', 'Đang tải kết quả…') }}</p>
      <Alert v-else-if="error" theme="red" :title="error" />
      <p v-else-if="!report" class="text-sm text-ink-muted">{{ tr('No matching findings yet. Run the scene check and return when it finishes.', 'Chưa có kết quả phù hợp. Chạy kiểm tra cảnh rồi mở lại sau khi hoàn tất.') }}</p>
      <div v-else class="space-y-3" data-test="scene-check-findings">
        <p class="text-xs text-ink-muted">{{ tr(`${report.samples.length} sampled frames`, `${report.samples.length} khung hình mẫu`) }}</p>
        <article v-for="row in report.results" :key="row.id" class="rounded-xl border border-outline-border p-3">
          <Badge :theme="row.verdict === 'supported' ? 'green' : row.verdict === 'violated' ? 'red' : 'orange'"
            :label="row.verdict === 'supported' ? tr('Observed support', 'Có bằng chứng phù hợp') : row.verdict === 'violated' ? tr('Problem observed', 'Phát hiện vấn đề') : tr('Uncertain — review needed', 'Chưa rõ — cần xem lại')" />
          <p class="mt-2 text-sm font-semibold text-ink-primary">{{ row.claim }}</p>
          <p class="mt-1 text-xs text-ink-muted">{{ row.reason }}</p>
          <p v-if="row.timing_alignment === 'observed outside authored window'" class="mt-1 text-xs text-amber-500">{{ tr('Observed later or earlier than planned. Check the pacing.', 'Hành động sớm hoặc muộn hơn dự kiến. Hãy kiểm tra nhịp phim.') }}</p>
          <p v-if="row.frames.length" class="mt-1 text-xs text-ink-muted">{{ tr('Sample times: ', 'Thời điểm mẫu: ') }}{{ row.frames.map(i => `${report.samples[i].time.toFixed(2)}s`).join(', ') }}</p>
        </article>
      </div>
    </template>
    <template #actions><Button @click="emit('close')">{{ tr('Close', 'Đóng') }}</Button></template>
  </Dialog>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { Alert, Badge, Button, Dialog, call } from 'frappe-ui';
import { tr } from '../../stores/i18n';
import { errorMessage } from '../../utils/errors';
const props = defineProps({ project: { type: String, required: true }, shot: { type: Object, required: true } });
const emit = defineEmits(['close']);
const loading = ref(true), report = ref(null), error = ref('');
onMounted(async () => {
  try {
    report.value = await call('joymedia.services.review.consistency.get_scene_check_evidence', {
      project_name: props.project, shot_name: props.shot.name, expected_take: props.shot.selected_output_asset_version,
    });
  } catch (err) { error.value = errorMessage(err, tr('Could not load findings.', 'Không tải được kết quả.')); }
  finally { loading.value = false; }
});
</script>
