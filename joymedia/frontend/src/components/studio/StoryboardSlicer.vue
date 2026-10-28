<template>
  <div class="slicer-overlay" role="dialog" aria-modal="true" :aria-label="t('Slice a storyboard sheet', 'Cắt bảng phân cảnh')" @click.self="close">
    <div class="slicer-box">
      <header class="slicer-head">
        <strong>📐 {{ t('SLICE A STORYBOARD SHEET', 'CẮT BẢNG PHÂN CẢNH') }}</strong>
        <button type="button" :aria-label="t('Close', 'Đóng')" @click="close">✖</button>
      </header>

      <div class="slicer-body">
        <div class="slicer-controls">
          <label class="slicer-file">
            <span>{{ t('Storyboard image', 'Ảnh bảng phân cảnh') }}</span>
            <input type="file" accept="image/*" :disabled="busy" @change="pickImage" />
          </label>

          <div class="slicer-grid-pick">
            <label>
              <span>{{ t('Rows', 'Hàng') }}</span>
              <select v-model.number="rows" :disabled="!imageUrl || busy">
                <option v-for="n in 6" :key="`r${n}`" :value="n">{{ n }}</option>
              </select>
            </label>
            <label>
              <span>{{ t('Columns', 'Cột') }}</span>
              <select v-model.number="cols" :disabled="!imageUrl || busy">
                <option v-for="n in 6" :key="`c${n}`" :value="n">{{ n }}</option>
              </select>
            </label>
          </div>

          <button type="button" class="slicer-primary" :disabled="!imageUrl || busy" @click="slice">
            ✂️ {{ t('Cut the grid', 'Cắt lưới ngay') }} ({{ rows * cols }})
          </button>

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
          <button type="button" @click="close">{{ t('Cancel', 'Hủy bỏ') }}</button>
          <button type="button" class="slicer-primary" :disabled="!panels.length || busy || !applyCount" @click="apply">
            {{ busy ? progressLabel : `🚀 ${t('Use as scene images', 'Đặt làm ảnh đầu cảnh')} (${applyCount})` }}
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

const props = defineProps({
  projectName: { type: String, required: true },
  shots: { type: Array, default: () => [] },
  currentLang: { type: String, default: "vi" },
});
const emit = defineEmits(["close", "done"]);
const t = (en, vi) => (props.currentLang === "vi" ? vi : en);

const imageUrl = ref("");
const rows = ref(3);
const cols = ref(4);
const panels = ref([]);
const busy = ref(false);
const progressLabel = ref("");
let sourceImage = null;

// Only as many panels as there are scenes can be attached.
const applyCount = computed(() => Math.min(panels.value.length, props.shots.length));
const matchMessage = computed(() => {
  const p = panels.value.length, s = props.shots.length;
  if (p === s) return t(`${p} panels for ${s} scenes.`, `${p} ô cho ${s} cảnh.`);
  if (p > s) return t(`${p} panels but only ${s} scenes — the first ${s} will be used.`, `${p} ô nhưng chỉ có ${s} cảnh — sẽ dùng ${s} ô đầu.`);
  return t(`${p} panels for ${s} scenes — the first ${p} scenes will be set.`, `${p} ô cho ${s} cảnh — sẽ đặt cho ${p} cảnh đầu.`);
});
function shotLabel(index) {
  const shot = props.shots[index];
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
watch([rows, cols], releasePanels);

function pickImage(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  releasePanels();
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value);
  imageUrl.value = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => { sourceImage = image; };
  image.src = imageUrl.value;
}

function slice() {
  if (!sourceImage) return;
  releasePanels();
  const cellW = Math.floor(sourceImage.naturalWidth / cols.value);
  const cellH = Math.floor(sourceImage.naturalHeight / rows.value);
  const cut = [];
  for (let r = 0; r < rows.value; r += 1) {
    for (let c = 0; c < cols.value; c += 1) {
      const canvas = document.createElement("canvas");
      canvas.width = cellW; canvas.height = cellH;
      canvas.getContext("2d").drawImage(sourceImage, c * cellW, r * cellH, cellW, cellH, 0, 0, cellW, cellH);
      cut.push(canvas);
    }
  }
  panels.value = cut.map((canvas, index) => ({ canvas, url: canvas.toDataURL("image/png"), index }));
}

function toFile(canvas, name) {
  return new Promise((resolve) => canvas.toBlob((blob) => resolve(new File([blob], name, { type: "image/png" })), "image/png"));
}

async function apply() {
  const total = applyCount.value;
  if (!total) return;
  busy.value = true;
  let done = 0;
  try {
    for (let index = 0; index < total; index += 1) {
      const shot = props.shots[index];
      progressLabel.value = t(`Setting scene ${index + 1} of ${total}…`, `Đang đặt cảnh ${index + 1}/${total}…`);
      const file = await toFile(panels.value[index].canvas, `storyboard-panel-${index + 1}.png`);
      const uploaded = await uploadFile(file, { private: true });
      if (!uploaded?.file_url || !uploaded?.name) throw new Error("Upload failed");
      const created = await call("joymedia.services.intake.assets.create_media_asset", {
        asset_name: `${t("Storyboard panel", "Ô phân cảnh")} ${index + 1}`,
        asset_category: "Reference",
        file_url: uploaded.file_url,
        file_name: uploaded.name,
      });
      // A panel describes the framing of a shot, so it enters the project as Composition.
      const selected = await call("joymedia.api.assets.select_project_asset", {
        media_project: props.projectName,
        asset_name: created.media_asset || created.name,
        reference_role: "Composition",
        label: `${t("Storyboard panel", "Ô phân cảnh")} ${index + 1}`,
      });
      const assetVersion = selected?.asset_version || created?.asset_version;
      if (!assetVersion) throw new Error("No asset version returned");
      await call("joymedia.api.storyboard.set_project_shot_keyframe", {
        project_name: props.projectName,
        shot_name: shot.name,
        frame_role: "first_frame",
        asset_version: assetVersion,
      });
      done += 1;
    }
    // These scenes now have a supplied first frame, so the AI will skip them.
    const remaining = Math.max(0, props.shots.length - done);
    notify({
      title: t("Storyboard sliced", "Đã cắt bảng phân cảnh"),
      text: remaining
        ? t(`${done} scenes now use your storyboard. The AI will draw the other ${remaining}.`,
            `${done} cảnh dùng ảnh từ bảng phân cảnh của bạn. AI sẽ vẽ ${remaining} cảnh còn lại.`)
        : t(`${done} scenes now use your storyboard, so the AI will not redraw them.`,
            `${done} cảnh dùng ảnh từ bảng phân cảnh của bạn, AI sẽ không vẽ lại.`),
      type: "success",
    });
    emit("done");
    // close() refuses while busy, and busy only clears in finally, so emit directly.
    emit("close");
  } catch (err) {
    notify({
      title: t("Could not finish slicing", "Không thể hoàn tất"),
      text: `${errorMessage(err, "")} ${done ? t(`${done} scenes were set before this.`, `Đã đặt được ${done} cảnh trước đó.`) : ""}`.trim(),
      type: "error",
    });
    if (done) emit("done");
  } finally {
    busy.value = false;
    progressLabel.value = "";
  }
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
.slicer-empty { margin: 0; color: #64748b; font-size: 11px; text-align: center; }
.slicer-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-top: 1px solid #22293d; }
.slicer-match { margin: 0; font-size: 11px; color: #94a3b8; }
.slicer-match.warn { color: #f59e0b; }
.slicer-foot-actions { display: flex; gap: 8px; margin-left: auto; }
.slicer-foot-actions > button:first-child { border: 1px solid #323d5a; border-radius: 7px; background: transparent; padding: 7px 12px; }
</style>
