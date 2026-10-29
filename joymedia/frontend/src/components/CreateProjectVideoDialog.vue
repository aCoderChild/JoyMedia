<template>
  <div class="new-version-overlay" @click.self="close">
    <section ref="dialog" tabindex="-1" role="dialog" aria-modal="true" :aria-label="tr('Create another video', 'Tạo video khác')" class="new-version-dialog">
      <header><h2>{{ tr('Create another video', 'Tạo video khác') }}</h2><button type="button" :disabled="submitting" :aria-label="tr('Close', 'Đóng')" @click="close">×</button></header>
      <p class="project-name">{{ project.project_name }}</p>
      <p>{{ tr('This creates a separate script and scenes using this project’s references. Your current edit is kept. Review the new script before generating images or clips.', 'Tạo kịch bản và các cảnh riêng từ tư liệu của dự án này. Bản dựng hiện tại được giữ nguyên. Bạn sẽ duyệt kịch bản mới trước khi tạo ảnh hoặc đoạn phim.') }}</p>
      <template v-if="!batch">
        <label>{{ tr('Direction for the new video (optional)', 'Ý tưởng cho video mới (không bắt buộc)') }}<textarea v-model="direction" rows="4" maxlength="4000" :disabled="submitting" :placeholder="project.video_idea || ''" /></label>
        <label>{{ tr('Video length', 'Độ dài video') }}<select v-model="duration" :disabled="submitting"><option value="">{{ tr('Use project duration', 'Dùng độ dài của dự án') }}</option><option v-for="seconds in [15,30,45,60]" :key="seconds" :value="String(seconds)">{{ seconds }}s</option></select></label>
      </template>
      <p v-else role="status">{{ tr('Preparing the new script. You can close this dialog; preparation continues. Reopen Create another video to check it.', 'Đang chuẩn bị kịch bản mới. Bạn có thể đóng hộp thoại; công việc vẫn tiếp tục. Mở lại Tạo video khác để xem tiến độ.') }}</p>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <footer><button type="button" :disabled="submitting" @click="close">{{ tr('Close', 'Đóng') }}</button><button v-if="!batch" type="button" data-test="confirm-new-project-video" :disabled="submitting" @click="create">{{ submitting ? '…' : tr('Create new script', 'Tạo kịch bản mới') }}</button><button v-else-if="stopped" type="button" @click="resetRequest">{{ tr('Prepare a new request', 'Chuẩn bị yêu cầu mới') }}</button><button v-else type="button" @click="load">{{ tr('Check progress', 'Xem tiến độ') }}</button></footer>
    </section>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { call } from 'frappe-ui';
import { tr } from '../stores/i18n';
import { errorMessage } from '../utils/errors';
import { useDialogFocus } from '../composables/useDialogFocus';
const props = defineProps({ project: { type: Object, required: true } });
const emit = defineEmits(['close', 'created', 'started']);
const dialog = ref(null), direction = ref(''), duration = ref(''), submitting = ref(false), batch = ref(''), error = ref(''), stopped = ref(false);
const key = `joymedia:new-video:${props.project.name}`;
let timer, disposed = false, checking = false;
function remember(value) { try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch { /* Storage is optional. */ } }
function close() { if (!submitting.value) emit('close'); }
function resetRequest() { batch.value = ''; stopped.value = false; error.value = ''; remember(''); }
useDialogFocus(dialog, close);
async function load() {
  if (!batch.value || checking || disposed) return;
  clearTimeout(timer); checking = true; error.value = '';
  try {
    const result = await call('joymedia.api.creative.get_product_batch', { batch_name: batch.value });
    if (disposed) return;
    const video = result.variants?.find(variant => variant.project);
    if (video) { remember(''); emit('created', video.project); return; }
    if (['Needs Attention', 'Cancelled', 'Failed'].includes(result.status)) {
      stopped.value = true;
      error.value = result.variants?.find(variant => variant.error)?.error || tr('Script preparation stopped. Open the project to review its activity before starting another request.', 'Việc chuẩn bị kịch bản đã dừng. Mở dự án và xem lịch sử trước khi tạo yêu cầu khác.');
      return;
    }
  } catch (err) { if (!disposed) error.value = errorMessage(err, tr('Could not check progress.', 'Chưa kiểm tra được tiến độ.')); }
  finally { checking = false; }
  if (!disposed) timer = setTimeout(load, 4000);
}
async function create() {
  if (submitting.value || batch.value) return;
  submitting.value = true; error.value = '';
  try {
    const result = await call('joymedia.api.creative.create_product_batch', { source_project: props.project.name, count: 1, direction: direction.value.trim() || null, duration_seconds: duration.value ? Number(duration.value) : null, auto_render: false, delivery_mode: 'assisted' });
    batch.value = result.batch; remember(batch.value); emit('started'); load();
  } catch (err) { error.value = errorMessage(err, tr('Could not create the video.', 'Không thể tạo video.')); }
  finally { submitting.value = false; }
}
onMounted(() => { try { batch.value = localStorage.getItem(key) || ''; } catch { /* Storage is optional. */ } if (batch.value) load(); });
onUnmounted(() => { disposed = true; clearTimeout(timer); });
</script>

<style scoped>
.new-version-overlay{position:fixed;inset:0;z-index:90;display:grid;place-items:center;padding:20px;background:#030810b8;backdrop-filter:blur(5px)}
.new-version-dialog{width:min(540px,100%);max-height:90vh;overflow:auto;padding:22px;border:1px solid var(--outline-border);border-radius:14px;background:var(--surface-card);color:var(--ink-primary);box-shadow:0 18px 60px #0008;font-size:13px;line-height:1.6}
header,footer{display:flex;justify-content:space-between;align-items:center;gap:12px}h2{font-size:18px;font-weight:700}header button{font-size:24px}.project-name{font-weight:600;color:var(--primary-accent)}p{margin:12px 0;color:var(--ink-secondary)}label{display:block;margin:14px 0;font-size:12px}textarea,select{display:block;width:100%;padding:10px;margin-top:6px;border:1px solid var(--outline-border);border-radius:7px;background:var(--surface-muted);color:var(--ink-primary)}footer{margin-top:20px}footer button{padding:7px 12px;border:1px solid var(--outline-border);border-radius:7px}footer button:last-child{color:var(--primary-accent)}button:disabled{opacity:.5}.error{color:#f87171}
</style>
