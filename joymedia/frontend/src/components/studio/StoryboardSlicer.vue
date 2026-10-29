<template>
  <div :class="embedded ? 'slicer-embedded' : 'slicer-overlay'" :role="embedded ? undefined : 'dialog'" :aria-modal="embedded ? undefined : true" :aria-label="t('Slice a storyboard sheet', 'Cắt bảng phân cảnh')" @click.self="!embedded && close()">
    <div class="slicer-box">
      <header v-if="!embedded" class="slicer-head">
        <strong>📐 {{ t('SLICE A STORYBOARD SHEET', 'CẮT BẢNG PHÂN CẢNH') }}</strong>
        <button type="button" :aria-label="t('Close', 'Đóng')" @click="close">✖</button>
      </header>

      <div class="slicer-body">
        <div class="slicer-controls">
          <label class="slicer-file">
            <span>{{ t('Storyboard image', 'Ảnh bảng phân cảnh') }}</span>
            <input type="file" accept="image/*" :disabled="busy" @change="pickImage" />
          </label>

          <label class="slicer-file"><span>{{ t('Import action', 'Cách nhập') }}</span><select v-model="mode" :disabled="busy"><option value="append">{{ t('Create a scene for every panel', 'Tạo cảnh mới cho tất cả các ô') }}</option><option value="existing">{{ t('Replace existing scene images', 'Thay ảnh các cảnh hiện có') }}</option></select></label>
          <div class="slicer-grid-pick">
            <label>
              <span>{{ t('Rows', 'Hàng') }}</span>
              <select v-model.number="rows" :aria-label="t('Rows', 'Hàng')" :disabled="!imageUrl || busy">
                <option v-for="n in 6" :key="`r${n}`" :value="n">{{ n }}</option>
              </select>
            </label>
            <label>
              <span>{{ t('Columns', 'Cột') }}</span>
              <select v-model.number="cols" :aria-label="t('Columns', 'Cột')" :disabled="!imageUrl || busy">
                <option v-for="n in 6" :key="`c${n}`" :value="n">{{ n }}</option>
              </select>
            </label>
          </div>

          <button type="button" class="slicer-primary" :disabled="!imageReady || busy" @click="slice">
            ✂️ {{ t('Cut the grid', 'Cắt lưới ngay') }} ({{ rows * cols }})
          </button>

          <p v-if="error" class="slicer-error" role="alert">{{ error }}</p>
          <p class="slicer-note">
            {{ t('Set the rows and columns to match your sheet. Panels are cut in reading order: left to right, top to bottom.', 'Chọn số hàng và cột đúng với bảng của bạn. Các ô được cắt theo thứ tự đọc: trái sang phải, trên xuống dưới.') }}
          </p>
        </div>

        <div class="slicer-preview">
          <div v-if="imageUrl" class="slicer-stage">
            <img :src="imageUrl" :alt="t('Storyboard sheet', 'Bảng phân cảnh')" />
            <div class="slicer-overlay-grid" :style="{ gridTemplateRows: `repeat(${rows}, 1fr)`, gridTemplateColumns: `repeat(${cols}, 1fr)` }">
              <span v-for="n in rows * cols" :key="n">{{ n }}</span>
            </div>
          </div>
          <p v-else class="slicer-empty">{{ t('Choose a storyboard image to begin.', 'Chọn ảnh bảng phân cảnh để bắt đầu.') }}</p>
        </div>

        <div class="slicer-panels">
          <strong>{{ t('Panels', 'Các ô') }} ({{ panels.length }})</strong>
          <div v-if="panels.length" class="slicer-panel-list">
            <figure v-for="(panel, index) in panels" :key="panel.url">
              <img :src="panel.url" :alt="`${t('Panel', 'Ô')} ${index + 1}`" />
              <figcaption>{{ shotLabel(index) }}</figcaption>
            </figure>
          </div>
          <p v-else class="slicer-empty">{{ t('Cut the grid to see the panels.', 'Bấm cắt lưới để xem các ô.') }}</p>
        </div>
      </div>

      <footer class="slicer-foot">
        <p v-if="panels.length" class="slicer-match" :class="{ warn: panels.length !== shots.length }">
          {{ matchMessage }}
        </p>
        <div class="slicer-foot-actions">
          <button type="button" @click="close">{{ embedded ? t('Back to storyboard', 'Về bảng phân cảnh') : t('Cancel', 'Hủy bỏ') }}</button>
          <button type="button" class="slicer-primary" :disabled="!panels.length || busy || !applyCount || (mode === 'existing' && panels.length !== shots.length)" @click="apply">
            {{ busy ? progressLabel : `🚀 ${(mode === 'append' ? t('Push all scenes to canvas', 'Đẩy tất cả cảnh vào canvas') : t('Replace scene images', 'Thay ảnh đầu cảnh'))} (${applyCount})` }}
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { call, upload as uploadFile } from "frappe-ui";
import { notify } from "../../utils/notify";
import { errorMessage } from "../../utils/errors";
import { rioConfirm } from "../../utils/rioDialog";

const props = defineProps({
  projectName: { type: String, required: true },
  shots: { type: Array, default: () => [] },
  currentLang: { type: String, default: "vi" },
  embedded: Boolean,
});
const emit = defineEmits(["close", "done", "busy-change"]);
const t = (en, vi) => (props.currentLang === "vi" ? vi : en);

const imageUrl = ref("");
const imageReady = ref(false), error = ref(''), mode = ref('append');
let sourceFile = null, uploadedSource = null;
let requestId = crypto.randomUUID();
const rows = ref(3);
const cols = ref(4);
const panels = ref([]);
const busy = ref(false);
watch(busy, value => emit('busy-change', value));
const progressLabel = ref("");
let sourceImage = null;

const applyCount = computed(() => panels.value.length);
const matchMessage = computed(() => {
  const count = panels.value.length;
  if (mode.value === 'append') return t(`${count} new scenes will be added. Existing scenes stay unchanged.`, `Sẽ thêm ${count} cảnh mới. Các cảnh hiện có được giữ nguyên.`);
  return count === props.shots.length ? t(`${count} existing scene images will be replaced.`, `Sẽ thay ảnh của ${count} cảnh hiện có.`) : t('Use exactly one panel per existing scene, or choose create new scenes.', 'Cần đúng một ô cho mỗi cảnh hiện có, hoặc chọn tạo cảnh mới.');
});
function shotLabel(index) {
  const shot = mode.value === 'existing' ? props.shots[index] : null;
  if (mode.value === 'append') return `${t('New scene', 'Cảnh mới')} ${props.shots.length + index + 1}`;
  return shot ? `${t("Scene", "Cảnh")} ${shot.shot_number || index + 1}` : t("No scene", "Không có cảnh");
}

function releasePanels() {
  for (const panel of panels.value) URL.revokeObjectURL(panel.url);
  panels.value = [];
}
onUnmounted(() => {
  releasePanels();
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value);
});
watch([rows, cols], () => { releasePanels(); requestId = crypto.randomUUID(); error.value = ''; });
watch(mode, () => { requestId = crypto.randomUUID(); error.value = ''; });

function pickImage(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  releasePanels();
  imageReady.value = false; sourceImage = null; error.value = ''; sourceFile = file; uploadedSource = null; requestId = crypto.randomUUID();
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value);
  imageUrl.value = URL.createObjectURL(file);
  const image = new Image(), url = imageUrl.value;
  image.onload = () => {
    if (imageUrl.value !== url) return;
    if (image.naturalWidth * image.naturalHeight > 40000000) { error.value = t('Use an image up to 40 megapixels.', 'Dùng ảnh tối đa 40 megapixel.'); return; }
    sourceImage = image; imageReady.value = true;
  };
  image.onerror = () => { if (imageUrl.value === url) error.value = t('This image could not be opened.', 'Không thể mở ảnh này.'); };
  image.src = url;
}

function slice() {
  if (!sourceImage) return;
  releasePanels();
  if (sourceImage.naturalWidth < cols.value || sourceImage.naturalHeight < rows.value) { error.value = t('The image is too small for this grid.', 'Ảnh quá nhỏ cho lưới này.'); return; }
  const cut = [];
  for (let r = 0; r < rows.value; r += 1) {
    for (let c = 0; c < cols.value; c += 1) {
      const canvas = document.createElement("canvas");
      const x = Math.floor(c * sourceImage.naturalWidth / cols.value), y = Math.floor(r * sourceImage.naturalHeight / rows.value);
      const w = Math.floor((c + 1) * sourceImage.naturalWidth / cols.value) - x, h = Math.floor((r + 1) * sourceImage.naturalHeight / rows.value) - y;
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(sourceImage, x, y, w, h, 0, 0, w, h);
      cut.push(canvas);
    }
  }
  panels.value = cut.map((canvas, index) => ({ canvas, url: canvas.toDataURL("image/png"), index }));
}

async function apply() {
  if (!applyCount.value || busy.value) return;
  if (mode.value === 'existing' && !await rioConfirm(t('Replace the supplied first-frame images of all existing scenes?', 'Thay ảnh đầu cảnh của tất cả cảnh hiện có?'), { destructive: true })) return;
  busy.value = true; error.value = '';
  progressLabel.value = t('Importing storyboard…', 'Đang nhập bảng phân cảnh…');
  try {
    if (!uploadedSource) uploadedSource = await uploadFile(sourceFile, { private: true });
    if (!uploadedSource?.name) throw new Error(t('Upload failed.', 'Tải ảnh lên thất bại.'));
    const result = await call('joymedia.services.planning.storyboard_grid.import_grid', {
      project_name: props.projectName, file_name: uploadedSource.name, rows: rows.value, columns: cols.value, mode: mode.value, request_id: requestId,
    });
    notify({ title: t('Storyboard imported', 'Đã nhập bảng phân cảnh'), text: t(`${result.panels} panels saved as scene images. Review the storyboard before rendering.`, `Đã lưu ${result.panels} ô thành ảnh đầu cảnh. Hãy duyệt bảng phân cảnh trước khi dựng.`), type: 'success' });
    emit('done', result); emit('close');
  } catch (err) { error.value = errorMessage(err, t('Import failed. You can retry safely.', 'Nhập thất bại. Bạn có thể thử lại.')); }
  finally { busy.value = false; progressLabel.value = ''; }
}

function close() {
  if (busy.value) return;
  emit("close");
}
</script>

<style scoped>
.slicer-overlay { position: fixed; inset: 0; z-index: 90; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(3, 6, 10, 0.72); backdrop-filter: blur(5px); }
.slicer-box { display: flex; flex-direction: column; width: 1040px; max-width: 100%; max-height: 92vh; overflow: hidden; border: 1px solid #323d5a; border-radius: 12px; background: #0e121a; color: #f8fafc; font: 13px Inter, system-ui, sans-serif; box-shadow: 0 24px 70px rgba(0, 0, 0, 0.8); }
.slicer-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid #22293d; }
.slicer-head strong { font-size: 12px; letter-spacing: 0.9px; color: #00f0ff; }
.slicer-head button, .slicer-foot button { cursor: pointer; color: #cbd5e1; }
.slicer-body { display: flex; gap: 14px; padding: 14px; overflow: auto; }
.slicer-controls { width: 240px; flex: none; display: flex; flex-direction: column; gap: 12px; }
.slicer-file { display: flex; flex-direction: column; gap: 6px; font-size: 11px; color: #94a3b8; }
.slicer-file input { font-size: 11px; }
.slicer-grid-pick { display: flex; gap: 8px; }
.slicer-grid-pick label { flex: 1; display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: #94a3b8; }
.slicer-grid-pick select { padding: 5px; border: 1px solid #22293d; border-radius: 5px; background: #141824; color: #f8fafc; font-size: 12px; }
.slicer-primary { border: 1px solid #00f0ff; border-radius: 7px; background: #00f0ff; color: #04121a; font-weight: 700; padding: 7px 12px; cursor: pointer; }
.slicer-primary:disabled { opacity: 0.4; cursor: not-allowed; }
.slicer-note { margin: 0; color: #64748b; font-size: 11px; line-height: 1.5; }
.slicer-preview { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; border-radius: 8px; background: #000; overflow: hidden; }
.slicer-stage { position: relative; max-height: 420px; }
.slicer-stage img { display: block; max-width: 100%; max-height: 420px; object-fit: contain; }
.slicer-overlay-grid { position: absolute; inset: 0; display: grid; pointer-events: none; }
.slicer-overlay-grid span { display: flex; align-items: flex-start; justify-content: flex-start; padding: 2px 4px; outline: 1px dashed rgba(0, 240, 255, 0.75); color: #00f0ff; font-size: 10px; font-weight: 700; text-shadow: 0 0 6px #000; }
.slicer-panels { width: 190px; flex: none; display: flex; flex-direction: column; gap: 8px; }
.slicer-panels > strong { font-size: 11px; color: #94a3b8; }
.slicer-panel-list { display: flex; flex-direction: column; gap: 8px; overflow: auto; max-height: 420px; }
/* flex: none, or a long list squashes every thumbnail and hides its caption. */
.slicer-panel-list figure { flex: none; margin: 0; border: 1px solid #22293d; border-radius: 6px; overflow: hidden; background: #141824; }
.slicer-panel-list img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; }
.slicer-panel-list figcaption { padding: 4px 7px; font-size: 10px; font-weight: 700; color: #cbd5e1; }
.slicer-error{color:#fda4af;font-size:12px;line-height:1.5}.slicer-file select{padding:8px;border:1px solid #323d5a;border-radius:6px;background:#141824;color:#f8fafc}
.slicer-empty { margin: 0; color: #64748b; font-size: 11px; text-align: center; }
.slicer-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-top: 1px solid #22293d; }
.slicer-match { margin: 0; font-size: 11px; color: #94a3b8; }
.slicer-match.warn { color: #f59e0b; }
.slicer-foot-actions { display: flex; gap: 8px; margin-left: auto; }
.slicer-foot-actions > button:first-child { border: 1px solid #323d5a; border-radius: 7px; background: transparent; padding: 7px 12px; }
.slicer-embedded{display:flex;flex:1;min-height:0}.slicer-embedded .slicer-box{width:100%;max-height:none;border:0;border-radius:0;box-shadow:none}.slicer-embedded .slicer-body{flex:1;min-height:0}.slicer-embedded .slicer-preview{min-height:200px}
@media(max-width:800px){.slicer-body{flex-wrap:wrap}.slicer-controls{width:100%}.slicer-preview{flex-basis:100%}.slicer-panels{width:100%}.slicer-panel-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.slicer-foot{flex-wrap:wrap}}
</style>
