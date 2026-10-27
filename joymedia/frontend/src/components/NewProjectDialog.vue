<template>
  <Dialog v-model="open" :title="tr('New video', 'Video mới')" size="xl">
    <template #default>
      <div class="flex flex-col gap-4">
        <p class="text-sm text-ink-muted">
          {{ tr('Add photos of your product. The AI writes the story, draws every scene for you to check, then makes the video.', 'Thêm ảnh sản phẩm của bạn. AI viết kịch bản, vẽ từng cảnh để bạn duyệt, rồi làm video.') }}
        </p>

        <!-- 2. The images the film must show -->
        <div>
          <p class="mb-1.5 text-xs font-semibold text-ink-primary">{{ tr('1. Your product (and mascot) photos', '1. Ảnh sản phẩm (và nhân vật)') }}</p>
          <div v-if="form.autoScript && !workbook" class="grid grid-cols-1 gap-3 sm:grid-cols-2" data-test="photo-tiles">
            <input ref="productImagesInput" type="file" multiple accept="image/*,.pdf" class="hidden" @change="uploadImages($event, 'Product')" />
            <input ref="mascotImagesInput" type="file" multiple accept="image/*" class="hidden" @change="uploadImages($event, 'Character')" />
            <div
              v-for="tile in photoTiles" :key="tile.role" role="button" tabindex="0" :data-test="'photos-' + tile.role"
              class="cursor-pointer rounded-xl border-2 border-dashed p-3 transition-colors"
              :class="dragging === tile.role ? 'border-rio-500 bg-rio-50/40' : 'border-outline-border hover:border-rio-400'"
              @click="tile.input.value?.click()" @keydown.enter.prevent="tile.input.value?.click()"
              @dragover.prevent="dragging = tile.role" @dragleave="dragging = ''" @drop.prevent="dropFiles($event, tile.role)"
            >
              <p class="text-sm font-medium text-ink-primary">{{ tile.title }} <span class="text-xs font-normal" :class="tile.required ? 'text-rose-500' : 'text-ink-muted'">{{ tile.badge }}</span></p>
              <div v-if="photosFor(tile.role).length" class="mt-2 flex flex-wrap gap-2">
                <div v-for="reference in photosFor(tile.role)" :key="reference.file_url" class="relative size-16">
                  <span v-if="reference.pdf" class="grid size-16 place-items-center rounded-lg bg-surface-muted text-[10px] font-semibold">PDF</span>
                  <img v-else :src="reference.file_url" :alt="reference.label" :title="reference.label" class="size-16 rounded-lg object-cover bg-surface-muted" />
                  <button type="button" class="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-surface-card text-[10px] text-ink-muted shadow hover:text-rose-600" :aria-label="tr('Remove', 'Bỏ') + ' ' + reference.label" @click.stop="references.splice(references.indexOf(reference), 1)">✕</button>
                </div>
              </div>
              <p class="mt-2 text-xs text-rio-500">+ {{ tr('Click or drop photos here', 'Bấm hoặc kéo ảnh vào đây') }}</p>
              <p class="text-[11px] text-ink-muted">{{ tile.hint }}</p>
            </div>
          </div>
          <template v-else>
          <div v-for="(reference, index) in references" :key="reference.file_url" class="mb-2 flex items-center gap-2">
            <template v-if="reference.pdf">
              <span class="grid size-10 shrink-0 place-items-center rounded-lg bg-surface-muted text-[10px] font-semibold">PDF</span>
              <span class="grow truncate text-sm">{{ reference.label }}</span>
              <span class="w-36 text-[11px] text-ink-muted">{{ tr('Pictures are extracted; roles are guessed per page', 'Hình sẽ được tách ra; loại tự đoán theo trang') }}</span>
            </template>
            <template v-else>
              <img :src="reference.file_url" class="size-10 shrink-0 rounded-lg object-cover bg-surface-muted" alt="" />
              <span class="grow truncate text-sm">{{ reference.label }}</span>
              <details class="text-xs"><summary class="cursor-pointer text-ink-muted">{{ tr('Details', 'Chi tiết') }}</summary><div class="flex flex-col gap-2 py-2">
                <FormControl v-model="reference.label" type="text" :label="tr('Name', 'Tên')" />
                <FormControl v-model="reference.role" type="select" :options="roleOptions" :label="tr('Image type', 'Loại hình')" />
              </div></details>
            </template>
            <Button variant="ghost" @click="references.splice(index, 1)">✕</Button>
          </div>
          <FileUploader :file-types="['image/*', '.pdf']" @success="addReference" @failure="(e) => (error = String(e?.message || e))">
            <template #default="{ uploading, progress, openFileSelector }">
              <Button :loading="uploading" @click="openFileSelector">
                {{ uploading ? `${progress}%` : '+ ' + tr('Add images or a PDF', 'Thêm hình ảnh hoặc PDF') }}
              </Button>
            </template>
          </FileUploader>
          </template>
          <p v-if="uploadingImages" class="mt-1 text-xs text-ink-muted" role="status">{{ tr('Uploading', 'Đang tải lên') }} {{ uploadProgress }}…</p>
          <div v-if="form.autoScript && !workbook && sameProduct.length" class="mt-2 rounded-lg border border-rio-300 bg-rio-50/60 p-3 text-sm text-ink-primary dark:border-rio-700 dark:bg-rio-950/40" data-test="same-product-project">
            <p class="font-medium">{{ tr('This product already has a project', 'Sản phẩm này đã có dự án') }}</p>
            <label v-for="match in sameProduct" :key="match.name" class="flex gap-2 mt-1"><input type="radio" :value="match.name" v-model="intoProject" />{{ tr('Add the new videos to', 'Thêm video mới vào') }} “{{ match.project_name }}” ({{ match.video_count }} {{ tr('videos', 'video') }})</label>
            <label class="flex gap-2 mt-1"><input type="radio" value="" v-model="intoProject" />{{ tr('Start a separate project', 'Tạo dự án riêng') }}</label>
            <p v-if="intoProject" class="mt-1 text-xs text-ink-muted">{{ tr('The new videos use the same product and mascot pictures as that project, so every video stays consistent.', 'Video mới dùng cùng ảnh sản phẩm và mascot của dự án đó để mọi video đồng nhất.') }}</p>
          </div>
        </div>

        <div v-if="!workbook" class="space-y-3" data-test="video-basics">
          <p class="text-xs font-semibold text-ink-primary">{{ tr('2. The video you want', '2. Video bạn muốn') }}</p>
          <div v-if="form.autoScript" class="grid grid-cols-2 gap-3">
            <div>
              <FormControl v-model="form.variants" type="number" :min="1" :max="20" :label="tr('How many videos?', 'Bao nhiêu video?')" />
              <p class="mt-1 text-[11px] text-ink-muted" data-test="variants-hint">{{ tr('Each video has its own story and pictures. Stages can overlap; clips share the GPU queue.', 'Mỗi video có kịch bản và hình riêng. Các bước có thể chạy đồng thời; clip dùng chung hàng đợi GPU.') }}</p>
            </div>
            <FormControl v-model="form.duration" type="select" :label="tr('Video length', 'Độ dài video')" :options="durationOptions" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <FormControl v-model="form.format" type="select" :label="tr('Format', 'Định dạng')" :options="formatOptions" />
            <FormControl v-if="form.autoScript" v-model="form.language" type="select" data-test="viewer-language" :label="tr('Language of the voice and text', 'Ngôn ngữ lời thoại và chữ')" :options="[{ label: 'Tiếng Việt', value: 'vi' }, { label: 'English', value: 'en' }]" />
          </div>
          <FormControl v-if="form.format === 'Custom'" v-model="form.customRatio" :label="tr('Aspect ratio', 'Tỷ lệ khung hình')" placeholder="4:5, 21:9…" />
        </div>

        <details class="rounded-xl border border-outline-border p-3" data-test="project-options">
          <summary class="cursor-pointer text-sm font-medium text-ink-primary">{{ tr('More options', 'Tuỳ chọn thêm') }} <span class="text-xs font-normal text-ink-muted">· {{ tr('idea, example scripts, project name', 'ý tưởng, kịch bản mẫu, tên dự án') }}</span></summary>
          <div class="mt-4 flex flex-col gap-4">
            <FormControl
              v-model="form.brief" type="textarea" :rows="2" :label="tr('Your idea for the video', 'Ý tưởng cho video')"
              :placeholder="tr('e.g. for young mothers, warm and gentle, show how soft it is', 'VD: dành cho mẹ bỉm sữa, tông ấm áp, nhấn mạnh độ mềm mịn')"
            />
            <div data-test="example-scripts">
              <p class="text-xs font-medium text-ink-primary">{{ tr('Example scripts for the AI to learn from', 'Kịch bản mẫu để AI học theo') }}</p>
              <input ref="examplesInput" type="file" multiple accept=".xlsx" class="hidden" @change="uploadExamples" />
              <div class="mt-1 flex flex-wrap items-center gap-2">
                <Button :loading="uploadingExamples" @click="examplesInput?.click()">{{ tr('+ Example scripts (.xlsx)', '+ Kịch bản mẫu (.xlsx)') }}</Button>
                <span v-for="(file, index) in examples" :key="file.name" class="flex items-center gap-1 text-xs">✓ {{ file.file_name }} <button class="text-ink-muted" :aria-label="tr('Remove', 'Bỏ')" @click="examples.splice(index, 1)">✕</button></span>
              </div>
              <p class="mt-1 text-[11px] text-ink-muted">{{ tr('The AI copies their structure, pacing and tone, then writes a new story. Without examples it writes a random story.', 'AI học cấu trúc, nhịp và giọng văn rồi viết câu chuyện mới. Không có mẫu thì AI tự viết ngẫu nhiên.') }}</p>
            </div>
            <label v-if="productCount > 1" class="flex gap-2 text-sm" data-test="rotate-products"><input type="checkbox" v-model="form.everyProduct" />{{ tr('One product per video, rotating through all products', 'Mỗi video một sản phẩm, lần lượt qua tất cả sản phẩm') }}</label>
        <FormControl
          v-model="form.name" type="text" :label="tr('Project name', 'Tên dự án')"
          :placeholder="selectedDemo?.product_name || tr('You can rename it later', 'Có thể đổi tên sau')"
        />
          <div class="border-t border-outline-border pt-3" data-test="own-workbook">
          <p class="text-sm font-medium text-ink-primary">{{ tr('Already have your own script?', 'Đã có kịch bản riêng?') }}</p>
          <p class="mb-2 text-xs text-ink-muted">{{ tr('Upload your storyboard sheet and the video follows it instead of an AI-written story.', 'Tải bảng kịch bản lên, video sẽ làm theo bảng của bạn thay vì AI tự viết.') }}</p>
          <FileUploader
            :file-types="['.xlsx']" :validate-file="requireWorkbook" @success="onWorkbook"
            @failure="(e) => (error = String(e?.message || e))"
          >
            <template #default="{ uploading, progress, openFileSelector }">
              <div class="flex items-center gap-3 rounded-xl border border-dashed border-outline-border p-3">
                <Button :loading="uploading" @click="openFileSelector">
                  {{ uploading ? `${progress}%` : tr('Upload storyboard (.xlsx)', 'Tải bảng kịch bản (.xlsx)') }}
                </Button>
                <span v-if="workbook" class="text-sm text-ink-primary">✓ {{ workbook.file_name }}</span>
              </div>
            </template>
          </FileUploader>
          <p class="mt-1 text-[11px] text-ink-muted" data-test="template-download">
            {{ tr('No sheet yet?', 'Chưa có bảng?') }}
            <a :href="templateUrl('vi')" class="text-ink-primary underline">{{ tr('Download the template (Vietnamese)', 'Tải bảng mẫu (tiếng Việt)') }}</a>
            ·
            <a :href="templateUrl('en')" class="text-ink-primary underline">{{ tr('English', 'Tiếng Anh') }}</a>.
            {{ tr('Amber fields are required, grey ones optional; the AI reads the sheet and fills in the rest.', 'Ô vàng là bắt buộc, ô xám là tuỳ chọn; AI sẽ đọc bảng và điền phần còn lại.') }}
          </p>
          <!-- What the chosen sheet will produce, before anything is created -->
          <div v-if="preview.loading" class="mt-2 text-xs text-ink-muted">{{ tr('Reading the workbook…', 'Đang đọc bảng kịch bản…') }}</div>
          <div v-else-if="demos.length" class="mt-2 flex flex-col gap-2" data-test="workbook-preview">
            <FormControl
              v-if="demos.length > 1" v-model="form.demo" type="select" :label="tr('Which sheet?', 'Chọn trang nào?')"
              :options="demos.map((d) => ({ label: `${d.name}${d.product_name ? ' — ' + d.product_name : ''}`, value: d.name }))"
            />
            <div v-if="selectedDemo" class="flex flex-wrap gap-1.5">
              <Badge theme="blue" :label="selectedDemo.format_description || formatLabel(selectedDemo.format)" />
              <Badge v-if="selectedDemo.duration_seconds" theme="blue" :label="`${selectedDemo.duration_seconds}s`" />
              <Badge theme="blue" :label="tr(`${selectedDemo.scene_count} scenes`, `${selectedDemo.scene_count} cảnh`)" />
              <Badge v-if="selectedDemo.timing_gaps" theme="amber" :label="tr(`${selectedDemo.timing_gaps} timing gaps (closed on export)`, `${selectedDemo.timing_gaps} khoảng trống thời gian (nối lại khi xuất)`)" />
            </div>
          </div>
          <!-- What was understood from the sheet: must-have fields first, then the optional ones -->
          <details v-if="selectedDemo" :open="!selectedDemo.can_create" class="mt-2 rounded-xl border border-outline-border p-2.5" data-test="understood-fields">
            <summary class="cursor-pointer text-xs font-semibold text-ink-primary">{{ tr('Workbook details', 'Chi tiết bảng kịch bản') }}</summary>
            <p class="mb-1 text-xs font-semibold text-ink-primary">{{ tr('What we understood from the sheet', 'Hệ thống đã hiểu từ bảng') }}</p>
            <ul class="flex flex-col gap-0.5 text-xs">
              <li v-for="field in sortedFields" :key="field.key" class="flex gap-2">
                <span :class="field.found ? 'text-ink-primary' : field.required ? 'text-ink-red-4' : 'text-ink-muted'">{{ field.found ? '✓' : field.required ? '✗' : '–' }}</span>
                <span class="w-36 shrink-0 font-medium">{{ field.label }}<span v-if="field.required" class="text-ink-red-4"> *</span></span>
                <span class="min-w-0 truncate text-ink-muted" :title="field.value">{{ field.found ? firstLine(field.value) : field.required ? tr('Missing — fill it in the sheet', 'Thiếu — hãy điền vào bảng') : tr('Not given (optional)', 'Chưa có (tuỳ chọn)') }}</span>
              </li>
            </ul>
            <!-- The References sheet: the files to upload in step 2, by the names the scenes use -->
            <div v-if="sheetReferences.length" class="mt-2" data-test="sheet-references">
              <p class="mb-0.5 text-xs font-semibold text-ink-primary">{{ tr('Pictures named in the sheet (upload these files in step 2)', 'Ảnh được ghi trong bảng (tải đúng các tệp này ở bước 2)') }}</p>
              <ul class="flex flex-col gap-0.5 text-xs">
                <li v-for="item in sheetReferences" :key="item.name" class="flex gap-2">
                  <span class="w-36 shrink-0 font-medium truncate" :title="item.name">{{ item.name }}</span>
                  <span class="w-20 shrink-0 text-ink-muted">{{ item.type }}</span>
                  <span class="min-w-0 truncate" :class="item.drawn ? 'text-ink-muted' : 'text-ink-primary'">{{ item.drawn ? tr('drawn by the AI', 'AI tự vẽ') : item.file }}</span>
                </li>
              </ul>
            </div>
            <p v-if="sheetBrand.length" class="mt-1.5 text-[11px] text-ink-muted" data-test="sheet-brand">
              {{ tr('Brand sheet: ', 'Trang Thương hiệu: ') }}{{ sheetBrand.join(', ') }}
            </p>
            <p v-if="selectedDemo.scenes_drafted" class="mt-1.5 text-[11px] text-ink-muted">
              {{ tr('The sheet has no scene table: the AI will draft the scenes from the brief (Hook, one per selling point, Outro).', 'Bảng chưa có bảng cảnh: AI sẽ viết các cảnh từ thông tin chung (Hook, mỗi USP một cảnh, Outro).') }}
            </p>
          </details>

          </div>
          </div>
        </details>

        <Alert v-if="error" theme="red" :title="error" />
      </div>
    </template>
    <template #actions>
      <p v-if="!canCreate && !workbook" class="mr-auto self-center text-xs text-ink-muted" data-test="create-hint">{{ tr('Add at least one product photo to start.', 'Thêm ít nhất một ảnh sản phẩm để bắt đầu.') }}</p>
      <Button variant="solid" :loading="creating" :disabled="!canCreate || uploadingImages || uploadingExamples" @click="create">
        {{ form.autoScript && !workbook ? tr('Create videos', 'Tạo video') : tr('Create project', 'Tạo dự án') }}
      </Button>
    </template>
  </Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { Alert, Badge, Button, Dialog, FileUploader, FormControl, call, createResource, upload as uploadFile } from "frappe-ui";
import { tr } from "../stores/i18n";
import { errorMessage } from "../utils/errors";

const open = defineModel({ type: Boolean, default: false });
const emit = defineEmits(["created"]);

const form = reactive({ name: "", brief: "", format: "", customRatio: "", demo: "", autoScript: true, autoRender: true, variants: 1, duration: "", everyProduct: false, language: tr("en", "vi") });
const examples = ref([]), examplesInput = ref(null), uploadingExamples = ref(false);
const productCount = computed(() => references.value.filter((r) => r.role === "Product").length);
const durationOptions = computed(() => [
  { label: tr("Auto", "Tự động"), value: "" },
  ...[15, 30, 45, 60].map((s) => ({ label: `${s}s`, value: String(s) })),
]);
const workbook = ref(null);
const productImagesInput = ref(null), mascotImagesInput = ref(null), uploadingImages = ref(false), uploadProgress = ref("");
const references = ref([]);
const creating = ref(false);
// Every variation of one product stays in one project, as ad tools group variations under their product.
const sameProduct = ref([]), intoProject = ref("");
let matchEpoch = 0;
async function findSameProduct() {
  const epoch = ++matchEpoch;
  const files = references.value.filter((r) => r.role === "Product" && !r.pdf).map((r) => r.file_name);
  const matches = files.length ? await call("joymedia.services.intake.project.find_product_project", { file_names: files }).catch(() => []) : [];
  if (epoch !== matchEpoch) return;
  sameProduct.value = matches;
  if (!matches.some((m) => m.name === intoProject.value)) intoProject.value = matches[0]?.name || "";
}
watch(() => references.value.filter((r) => r.role === "Product").map((r) => r.file_name).join(), findSameProduct);
const error = ref("");

const roleOptions = computed(() => [
  { label: tr("Auto", "Tự động"), value: "" },
  { label: tr("Character (mascot)", "Nhân vật (mascot)"), value: "Character" },
  { label: tr("Person (real face)", "Người thật (khuôn mặt)"), value: "Person" },
  { label: tr("Product", "Sản phẩm"), value: "Product" },
  { label: tr("Logo", "Logo"), value: "Logo" },
  { label: tr("Environment", "Bối cảnh"), value: "Environment" },
  { label: tr("Other", "Khác"), value: "General" },
]);
const formatOptions = computed(() => [
  { label: tr("Auto (from your input)", "Tự động (theo nội dung)"), value: "" },
  { label: tr("Portrait 9:16 — TikTok, Reels", "Dọc 9:16 — TikTok, Reels"), value: "Portrait" },
  { label: tr("Landscape 16:9 — YouTube, web", "Ngang 16:9 — YouTube, web"), value: "Landscape" },
  { label: tr("Square 1:1", "Vuông 1:1"), value: "Square" },
  { label: tr("Custom ratio", "Tỷ lệ khác"), value: "Custom" },
]);

const canCreate = computed(() => workbook.value ? Boolean(selectedDemo.value?.can_create) : form.autoScript ? references.value.some(r => r.role === "Product") && Number.isInteger(Number(form.variants)) && Number(form.variants) >= 1 && Number(form.variants) <= 20 : Boolean(form.brief.trim()));
const templateUrl = (lang) => `/api/method/joymedia.services.intake.template.download_storyboard_template?lang=${lang}`;
const firstLine = (value) => String(value || "").split("\n")[0];
// Must-have fields first, so a missing one is the first thing the client sees.
const sortedFields = computed(() => [...(selectedDemo.value?.fields || [])].sort((a, b) => Number(b.required) - Number(a.required)));

// Read the workbook before creating anything: which sheets it has and what each will produce.
const preview = createResource({
  url: "joymedia.services.intake.project.preview_workbook",
  onSuccess: (data) => { form.demo = (data?.demos?.find((d) => d.can_create) || data?.demos?.[0])?.name || ""; },
  onError: (err) => { error.value = errorMessage(err, tr("Could not read the workbook.", "Không đọc được bảng kịch bản.")); workbook.value = null; },
});
const demos = computed(() => preview.data?.demos || []);
const sheetReferences = computed(() => preview.data?.references || []);
const sheetBrand = computed(() => preview.data?.brand || []);
const selectedDemo = computed(() => demos.value.find((d) => d.name === form.demo));

function onWorkbook(file) {
  workbook.value = file;
  error.value = "";
  preview.submit({ workbook_file: file.name });
}

function formatLabel(preset) {
  return { Portrait: tr("Portrait 9:16", "Dọc 9:16"), Landscape: tr("Landscape 16:9", "Ngang 16:9"), Square: tr("Square 1:1", "Vuông 1:1") }[preset]
    || tr("Format: set it below", "Định dạng: chọn bên dưới");
}

function requireWorkbook(file) {
  return file.name.toLowerCase().endsWith(".xlsx") ? null : tr("Please choose an .xlsx workbook.", "Vui lòng chọn tệp .xlsx.");
}

// The two photo tiles: the product is required, a mascot is optional.
const dragging = ref("");
const photoTiles = [
  { role: "Product", input: productImagesInput, required: true, title: tr("Product photos", "Ảnh sản phẩm"), badge: tr("required", "bắt buộc"), hint: tr("Clear photos of the pack from the front and other angles, or a PDF product sheet.", "Ảnh rõ nét của bao bì, mặt trước và các góc khác, hoặc tệp PDF sản phẩm.") },
  { role: "Character", input: mascotImagesInput, required: false, title: tr("Mascot / character photos", "Ảnh mascot / nhân vật"), badge: tr("if you have one", "nếu có"), hint: tr("The mascot appears in every scene exactly as in these photos.", "Mascot sẽ xuất hiện trong video đúng như ảnh này.") },
];
const photosFor = (role) => references.value.filter((r) => (role === "Product" ? r.role === "Product" : ["Character", "Person"].includes(r.role)));
function dropFiles(event, role) {
  dragging.value = "";
  uploadFiles(Array.from(event.dataTransfer?.files || []).filter((f) => /^image\//.test(f.type) || (role === "Product" && /\.pdf$/i.test(f.name))), role);
}
async function uploadImages(event, role) {
  await uploadFiles(Array.from(event.target.files || []), role);
  event.target.value = '';
}
// Files added while an upload runs wait their turn instead of being dropped.
let uploadQueue = Promise.resolve();
function uploadFiles(files, role) {
  uploadQueue = uploadQueue.then(() => uploadNow(files, role));
  return uploadQueue;
}
async function uploadNow(files, role) {
  if (!files.length) return;
  uploadingImages.value = true; error.value = '';
  try {
    for (let i = 0; i < files.length; i++) {
      uploadProgress.value = `${i + 1} / ${files.length}`;
      const file = await uploadFile(files[i], { private: true });
      if (!file?.name || !file?.file_url) throw new Error('Image upload did not complete.');
      addReference(file, role);
    }
  } catch (e) { error.value = errorMessage(e, 'Could not upload the images.'); }
  finally { uploadingImages.value = false; }
}

function addReference(file, role = "") {
  const stem = String(file.file_name || "").replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  references.value.push({ file_name: file.name, file_url: file.file_url, label: stem, role, pdf: /\.pdf$/i.test(file.file_name || "") });
}

async function uploadExamples(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length || uploadingExamples.value) return;
  uploadingExamples.value = true; error.value = "";
  try {
    for (const file of files) {
      if (!file.name.toLowerCase().endsWith(".xlsx")) throw new Error(tr("Please choose .xlsx workbooks.", "Vui lòng chọn tệp .xlsx."));
      const uploaded = await uploadFile(file, { private: true });
      if (!uploaded?.name) throw new Error("Upload did not complete.");
      examples.value.push(uploaded);
    }
  } catch (e) { error.value = errorMessage(e, "Could not upload the example scripts."); }
  finally { uploadingExamples.value = false; event.target.value = ""; }
}

async function create() {
  if (creating.value || uploadingImages.value) return;
  creating.value = true;
  error.value = "";
  try {
    const result = await call("joymedia.services.intake.project.create_project_from_brief", {
      project_name: form.name || null,
      video_idea: form.brief || null,
      workbook_file: workbook.value?.name || null,
      demo_name: form.demo || null,
      format: form.format === "Custom" ? form.customRatio : form.format || null,
      auto_script: form.autoScript && !workbook.value,
      auto_render: form.autoRender,
      variants: Number(form.variants),
      duration_seconds: form.autoScript && !workbook.value && form.duration ? Number(form.duration) : null,
      hero_products: form.autoScript && !workbook.value && form.everyProduct ? "all" : null,
      example_workbooks: form.autoScript && !workbook.value ? examples.value.map((f) => f.name) : null,
      language: form.autoScript && !workbook.value ? form.language : null,
      references: references.value.map(({ file_name, label, role }) => ({ file_name, label, role })),
      into_project: form.autoScript && !workbook.value ? intoProject.value || null : null,
    });
    open.value = false;
    emit("created", result.project);
  } catch (err) {
    error.value = errorMessage(err, tr("Could not create the project.", "Không thể tạo dự án."));
  } finally {
    creating.value = false;
  }
}
</script>
