<template>
  <div class="effects-overlay" @click.self="emit('close')">
    <section class="effects-dialog" role="dialog" aria-modal="true" :aria-label="t('Sound effects', 'Hiệu ứng âm thanh')">
      <header><strong>🎙 {{ t('SOUND EFFECTS', 'HIỆU ỨNG ÂM THANH') }}</strong><button :aria-label="t('Close', 'Đóng')" @click="emit('close')">×</button></header>
      <p>{{ t('Generate effects for the selected rendered scene, or choose an audio file for the timeline.', 'Tạo hiệu ứng cho cảnh đã dựng được chọn, hoặc chọn tệp âm thanh cho dòng thời gian.') }}</p>
      <p v-if="!available && !loading" class="notice">{{ t('No effects generation workflow is configured. You can still add an audio file.', 'Chưa cấu hình quy trình tạo hiệu ứng. Bạn vẫn có thể thêm tệp âm thanh.') }}</p>
      <p v-if="!rendered" class="notice">{{ t('Select a rendered scene to generate matching effects.', 'Chọn một cảnh đã dựng để tạo hiệu ứng phù hợp.') }}</p>
      <label>{{ t('Describe the sound', 'Mô tả âm thanh') }}<textarea v-model="prompt" maxlength="2000" rows="4" :disabled="running" :placeholder="t('Paper rustling, soft footsteps, rain…', 'Tiếng giấy, bước chân nhẹ, tiếng mưa…')" /></label>
      <p v-if="running" role="status">{{ t('Sound effects are queued or generating. You can close this panel; the job continues.', 'Hiệu ứng đang chờ hoặc đang tạo. Bạn có thể đóng bảng này; công việc vẫn tiếp tục.') }}</p>
      <p v-if="success" role="status">{{ t('Sound effects added to the timeline.', 'Đã thêm hiệu ứng vào dòng thời gian.') }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <footer><button @click="emit('upload'); emit('close')">＋ {{ t('Choose audio file', 'Chọn tệp âm thanh') }}</button><button :disabled="!available || !rendered || !prompt.trim() || running || loading" @click="generate">{{ running ? '…' : t('Generate SFX', 'Tạo hiệu ứng') }}</button></footer>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { call } from 'frappe-ui';
import { errorMessage } from '../../utils/errors';
const props = defineProps({ projectName: String, shot: Object, currentLang: String });
const emit = defineEmits(['close', 'upload', 'done']);
const t = (en, vi) => props.currentLang === 'vi' ? vi : en;
const prompt = ref(''), available = ref(false), loading = ref(true), running = ref(false), error = ref(''), success = ref(false);
const rendered = computed(() => Boolean(props.shot?.selected_output_asset_version || props.shot?.selected_output_file || props.shot?.output_video));
const key = `joymedia:effects:${props.projectName}`;
let timer, disposed = false, jobId = '', requestId = '';
function remember(value) { try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch { /* Storage is optional. */ } }
async function poll() {
  try {
    const result = await call('joymedia.api.studio_tools.effects_status', { project_name: props.projectName, job_id: jobId });
    if (disposed) return;
    if (result.status === 'finished') { running.value = false; success.value = true; remember(''); requestId = ''; emit('done'); return; }
    if (['failed', 'stopped', 'canceled', 'missing'].includes(result.status)) { running.value = false; error.value = result.error || t('This job stopped. You can try again.', 'Công việc đã dừng. Bạn có thể thử lại.'); remember(''); return; }
  } catch (err) { if (disposed) return; error.value = errorMessage(err, t('Cannot check progress. Reopen this panel to retry.', 'Chưa kiểm tra được tiến độ. Mở lại bảng này để thử lại.')); }
  if (!disposed) timer = setTimeout(poll, 3000);
}
async function generate() {
  if (running.value || !rendered.value || !available.value) return;
  running.value = true; error.value = ''; success.value = false;
  try {
    requestId ||= crypto.randomUUID();
    const result = await call('joymedia.api.studio_tools.queue_effects', { project_name: props.projectName, shot_name: props.shot.name, prompt: prompt.value.trim(), request_id: requestId });
    jobId = result.job_id; remember(jobId); if (!disposed) poll();
  } catch (err) { running.value = false; error.value = errorMessage(err, t('Could not queue sound effects.', 'Không thể tạo hiệu ứng.')); }
}
onMounted(async () => {
  try { available.value = (await call('joymedia.api.studio_tools.capabilities', { project_name: props.projectName })).effects; }
  catch (err) { error.value = errorMessage(err, 'Could not check audio tools.'); }
  finally { loading.value = false; }
  if (disposed) return;
  try { jobId = localStorage.getItem(key) || ''; } catch { /* Storage is optional. */ }
  if (jobId) { running.value = true; poll(); }
});
onUnmounted(() => { disposed = true; clearTimeout(timer); });
</script>

<style scoped>
.effects-overlay{position:fixed;inset:0;z-index:80;display:grid;place-items:center;padding:20px;background:#03060bc9;backdrop-filter:blur(4px)}
.effects-dialog{width:min(520px,100%);max-height:90vh;overflow:auto;padding:20px;border:1px solid #24576c;border-radius:13px;background:#101722;color:#e7f2f7;font:13px/1.6 Inter,system-ui,sans-serif;box-shadow:0 20px 60px #000a}
header,footer{display:flex;align-items:center;justify-content:space-between;gap:12px}header{color:#55e5f0}header button{font-size:24px}p{margin:14px 0;color:#a9bfcc}.notice{padding:10px;border:1px solid #624d27;border-radius:7px;color:#fcd58b}label{display:block}textarea{display:block;width:100%;margin:7px 0 16px;padding:10px;border:1px solid #2a4054;border-radius:7px;background:#090e17;color:#eff8ff;resize:vertical}.error{color:#fda4af}footer button{padding:8px 12px;border:1px solid #23657c;border-radius:7px;background:#11313e;color:#86eff7}button:disabled{opacity:.4;cursor:not-allowed}
</style>
