<template>
  <Dialog v-model="open" :title="tr('New video', 'Video mới')" size="xl">
    <template #default>
      <div class="flex flex-col gap-4">
        <p class="text-sm text-ink-muted">
          {{ tr(
            'Upload your product and mascot images. AI can write the story and generate video variants. You can also supply your own brief or workbook.',
            'Tải ảnh sản phẩm và mascot. AI có thể tự viết kịch bản và tạo nhiều video. Bạn cũng có thể cung cấp ý tưởng hoặc bảng kịch bản.'
          ) }}
        </p>

        <!-- 1. The story: a storyboard workbook, or a written brief -->
        <div>
          <p class="mb-1.5 text-xs font-semibold text-ink-primary">{{ tr('1. Creative direction (optional)', '1. Ý tưởng (tuỳ chọn)') }}</p>
          <FormControl
            v-model="form.brief" type="textarea" class="mt-2" :rows="3"
            :placeholder="tr('Optional: mood, audience or creative direction', 'Tuỳ chọn: cảm xúc, khán giả hoặc hướng sáng tạo')"
          />
          <details class="mt-3 text-xs"><summary class="cursor-pointer text-ink-secondary">{{ tr('Or import a storyboard spreadsheet', 'Hoặc nhập bảng kịch bản') }}</summary>
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
                <span v-else class="text-xs text-ink-muted">{{ tr('or write a brief below', 'hoặc viết mô tả bên dưới') }}</span>
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

          </details>
        </div>

        <!-- 2. The images the film must show -->
        <div>
          <p class="mb-1.5 text-xs font-semibold text-ink-primary">{{ tr('2. Images the film must show', '2. Hình ảnh phải xuất hiện') }}</p>
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
          <p class="mt-1 text-[11px] text-ink-muted">
            {{ tr('Use clear photos of your product, logo and character.', 'Dùng ảnh rõ nét của sản phẩm, logo và nhân vật.') }}
          </p>
        </div>

        <div v-if="!workbook" class="rounded-xl border border-outline-border p-3 space-y-3">
          <label class="flex gap-2 text-sm"><input type="checkbox" v-model="form.autoScript" />{{ tr('Let AI write the script from my references', 'AI tự viết kịch bản từ ảnh tham chiếu') }}</label>
          <template v-if="form.autoScript">
            <FormControl v-model="form.variants" type="number" :min="1" :max="20" :label="tr('Number of video variants', 'Số video biến thể')" />
            <label class="flex gap-2 text-sm"><input type="checkbox" v-model="form.autoRender" />{{ tr('Continue through video generation and music', 'Tự tạo tiếp video và nhạc nền') }}</label>
            <p class="text-xs text-ink-muted">{{ tr('Multiple product photos are views of the same product. Variant count is independent of photo count. Assign mascot photos the Character role. Quality concerns remain visible for review.', 'Nhiều ảnh sản phẩm là các góc nhìn của cùng sản phẩm. Số video độc lập với số ảnh. Chọn vai trò Nhân vật cho ảnh mascot. Các vấn đề chất lượng vẫn được giữ để kiểm tra.') }}</p>
          </template>
        </div>

        <details class="rounded-xl border border-outline-border p-3" data-test="project-options">
          <summary class="cursor-pointer text-xs font-semibold text-ink-muted">{{ tr('Optional: name & format', 'Tuỳ chọn: tên và định dạng') }}</summary>
          <div class="mt-3 flex flex-col gap-3">
        <FormControl
          v-model="form.name" type="text" :label="tr('Project name', 'Tên dự án')"
          :placeholder="selectedDemo?.product_name || tr('Optional — you can rename it later', 'Tuỳ chọn — có thể đổi tên sau')"
        />

            <FormControl v-model="form.format" type="select" :label="tr('Format', 'Định dạng')" :options="formatOptions" />
            <FormControl v-if="form.format === 'Custom'" v-model="form.customRatio" :label="tr('Aspect ratio', 'Tỷ lệ khung hình')" placeholder="4:5, 21:9…" />
          </div>
        </details>

        <Alert v-if="error" theme="red" :title="error" />
      </div>
    </template>
    <template #actions>
      <Button variant="solid" :loading="creating" :disabled="!canCreate" @click="create">
        {{ form.autoScript && !workbook ? tr('Create videos', 'Tạo video') : tr('Create project', 'Tạo dự án') }}
      </Button>
    </template>
  </Dialog>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { Alert, Badge, Button, Dialog, FileUploader, FormControl, call, createResource } from "frappe-ui";
import { tr } from "../stores/i18n";
import { errorMessage } from "../utils/errors";

const open = defineModel({ type: Boolean, default: false });
const emit = defineEmits(["created"]);

const form = reactive({ name: "", brief: "", format: "", customRatio: "", demo: "", autoScript: true, autoRender: true, variants: 1 });
const workbook = ref(null);
const references = ref([]);
const creating = ref(false);
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

const canCreate = computed(() => workbook.value ? Boolean(selectedDemo.value?.can_create) : form.autoScript ? references.value.some(r => !r.pdf) && Number.isInteger(Number(form.variants)) && Number(form.variants) >= 1 && Number(form.variants) <= 20 : Boolean(form.brief.trim()));
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

function addReference(file) {
  const stem = String(file.file_name || "").replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  references.value.push({ file_name: file.name, file_url: file.file_url, label: stem, role: "", pdf: /\.pdf$/i.test(file.file_name || "") });
}

async function create() {
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
      references: references.value.map(({ file_name, label, role }) => ({ file_name, label, role })),
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
