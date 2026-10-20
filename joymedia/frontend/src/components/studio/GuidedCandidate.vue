<template>
  <Dialog :model-value="true" :title="tr('Guide the motion', 'Hướng dẫn chuyển động')" size="xl" @update:model-value="!$event && emit('close')">
    <template #default>
      <div class="space-y-3" data-test="guided-candidate">
        <p class="text-sm">{{ tr('Use a video showing the correct action and proportions. For a local appearance repair, use the current take and an editable-region mask (white means redraw).', 'Dùng video có hành động và tỷ lệ đúng. Để sửa một vùng hình ảnh, dùng bản hiện tại và video mặt nạ (trắng là vùng vẽ lại).') }}</p>
        <div v-for="field in fields" :key="field.role">
          <label class="block text-sm">{{ field.label }}
            <select v-model="inputs[field.role]" class="w-full rounded border bg-surface-card p-2" :disabled="Boolean(run)" :data-test="field.role">
              <option value="">{{ field.optional ? tr('Optional', 'Không bắt buộc') : tr('Choose a file', 'Chọn tệp') }}</option>
              <option v-if="field.role === 'control_video'" :value="shot.selected_output_asset_version">{{ tr('Current take (appearance repair)', 'Bản hiện tại (sửa hình ảnh)') }}</option>
              <option v-for="asset in candidates.filter(a => a.media_type === field.type)" :key="asset.asset_version" :value="asset.asset_version">{{ asset.asset_name || asset.label || asset.asset_version }}</option>
            </select>
          </label>
          <input v-if="!run" type="file" :accept="field.type === 'Video' ? 'video/*' : 'image/*'" class="mt-1 text-xs" :disabled="uploading" :aria-label="field.label" @change="upload($event, field.role)" />
        </div>
        <label v-if="!run" class="block text-sm">{{ tr('What should improve? (optional)', 'Cần cải thiện gì? (không bắt buộc)') }}
          <textarea v-model="instruction" maxlength="2400" class="mt-1 w-full rounded border bg-surface-card p-2" data-test="guided-instruction" />
        </label>
        <p v-if="error" role="alert" class="text-sm text-red-600">{{ error }}</p>
        <p v-if="run" class="text-sm">{{ status }} · {{ tr('Review this separate candidate before using it.', 'Xem kỹ bản thử riêng trước khi sử dụng.') }}</p>
        <video v-if="video" :src="video" controls class="max-h-96 w-full" data-test="guided-video" />
        <Button v-if="video && assetVersion" :loading="submitting" data-test="guided-use" @click="useCandidate">{{ tr('Use this candidate', 'Dùng bản thử này') }}</Button>
        <a v-if="video" :href="video" download class="block text-sm underline">{{ tr('Download candidate', 'Tải bản thử') }}</a>
        <Button v-if="!run" variant="solid" :loading="submitting" :disabled="uploading || !inputs.control_video || !inputs.identity_reference" data-test="guided-submit" @click="submit">{{ tr('Create guided candidate', 'Tạo bản thử có hướng dẫn') }}</Button>
      </div>
    </template>
    <template #actions><Button @click="emit('close')">{{ tr('Close', 'Đóng') }}</Button></template>
  </Dialog>
</template>
<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { Button, Dialog, call, upload as uploadFile } from 'frappe-ui';
import { tr } from '../../stores/i18n';
import { errorMessage } from '../../utils/errors';
const props = defineProps({ project: String, shot: Object, assets: { type: Array, default: () => [] } });
const emit = defineEmits(['close', 'done']);
const candidates = ref([...props.assets]), inputs = ref({ control_video: props.shot.selected_output_asset_version, identity_reference: '', control_mask: '' });
const fields = [
  { role: 'control_video', label: tr('Motion guide', 'Video hướng dẫn'), type: 'Video' },
  { role: 'identity_reference', label: tr('Appearance reference', 'Ảnh tạo hình'), type: 'Image' },
  { role: 'control_mask', label: tr('Editable-region mask', 'Mặt nạ vùng chỉnh sửa'), type: 'Video', optional: true },
];
const error = ref(''), run = ref(''), status = ref(''), video = ref(''), assetVersion = ref(''), instruction = ref(''), uploading = ref(false), submitting = ref(false);
const storageKey = `joymedia-guided:${props.project}:${props.shot.name}`;
let timer, disposed = false, failures = 0;
async function upload(event, role) {
  const file = event.target.files?.[0]; if (!file) return;
  uploading.value = true; error.value = '';
  try {
    const uploaded = await uploadFile(file, { private: true });
    const asset = await call('joymedia.services.intake.assets.create_media_asset', { asset_name: file.name, asset_category: 'Reference', file_url: uploaded.file_url, file_name: uploaded.name });
    candidates.value.push({ asset_version: asset.asset_version, asset_name: file.name, media_type: role === 'identity_reference' ? 'Image' : 'Video' });
    inputs.value[role] = asset.asset_version;
  } catch (err) { error.value = errorMessage(err, tr('Upload failed.', 'Tải tệp thất bại.')); }
  finally { uploading.value = false; }
}
async function poll() {
  try {
    const result = await call('joymedia.services.generation.guided.guided_candidate_status', { project_name: props.project, run_name: run.value });
    if (disposed) return;
    status.value = result.status; video.value = result.video || ''; assetVersion.value = result.asset_version || ''; error.value = result.error || ''; failures = 0;
    if (!['Completed', 'Failed', 'Cancelled'].includes(result.status)) timer = setTimeout(poll, 4000);
  } catch (err) { if (!disposed) { error.value = errorMessage(err, 'Could not load candidate.'); if (++failures <= 5) timer = setTimeout(poll, 4000); } }
}
async function submit() {
  submitting.value = true; error.value = '';
  try {
    const controls = Object.fromEntries(Object.entries(inputs.value).filter(([, value]) => value));
    const result = await call('joymedia.services.generation.guided.queue_guided_candidate', { project_name: props.project, shot_name: props.shot.name, expected_take: props.shot.selected_output_asset_version, inputs: controls, ...(instruction.value.trim() ? { instruction: instruction.value.trim() } : {}) });
    run.value = result.run; localStorage.setItem(storageKey, run.value); status.value = result.status; poll();
  } catch (err) { error.value = errorMessage(err, tr('Could not create candidate.', 'Không tạo được bản thử.')); }
  finally { submitting.value = false; }
}
async function useCandidate() {
  submitting.value = true; error.value = '';
  try {
    await call('joymedia.services.generation.guided.use_guided_candidate', { project_name: props.project, run_name: run.value, expected_take: props.shot.selected_output_asset_version });
    localStorage.removeItem(storageKey); emit('done');
  } catch (err) { error.value = errorMessage(err, 'Could not select candidate.'); }
  finally { submitting.value = false; }
}
onMounted(async () => {
  const saved = localStorage.getItem(storageKey);
  if (saved) { run.value = saved; poll(); }
  try { candidates.value = await call('joymedia.api.assets.get_project_reference_candidates', { media_project: props.project }); }
  catch (err) { error.value = errorMessage(err, 'Could not load reference files.'); }
});
onUnmounted(() => { disposed = true; clearTimeout(timer); });
</script>
