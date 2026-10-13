<template>
  <Dialog v-model="open" :title="tr('New video', 'Video mới')" size="xl">
    <template #default>
      <div class="flex flex-col gap-4">
        <p class="text-sm text-ink-muted">
          {{ tr(
            'Give us the story and the images the film must show. Format, duration and each scene\'s references are worked out for you.',
            'Chỉ cần cung cấp kịch bản và những hình ảnh phải xuất hiện. Định dạng, thời lượng và tham chiếu từng cảnh sẽ được tự động xác định.'
          ) }}
        </p>

        <FormControl
          v-model="form.name" type="text" :label="tr('Project name', 'Tên dự án')"
          :placeholder="tr('Optional — taken from the workbook', 'Tuỳ chọn — lấy từ bảng kịch bản')"
        />

        <!-- 1. The story: a storyboard workbook, or a written brief -->
        <div>
          <p class="mb-1.5 text-xs font-semibold text-ink-primary">{{ tr('1. The story', '1. Kịch bản') }}</p>
          <FileUploader
            :file-types="['.xlsx']" :validate-file="requireWorkbook" @success="(f) => (workbook = f)"
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
          <FormControl
            v-model="form.brief" type="textarea" class="mt-2" :rows="3"
            :placeholder="tr('Describe the video you want (optional when a workbook is uploaded)', 'Mô tả video bạn muốn (không bắt buộc nếu đã tải bảng kịch bản)')"
          />
        </div>

        <!-- 2. The images the film must show -->
        <div>
          <p class="mb-1.5 text-xs font-semibold text-ink-primary">{{ tr('2. Images the film must show', '2. Hình ảnh phải xuất hiện') }}</p>
          <div v-for="(reference, index) in references" :key="reference.file_url" class="mb-2 flex items-center gap-2">
            <img :src="reference.file_url" class="size-10 shrink-0 rounded-lg object-cover bg-surface-muted" alt="" />
            <FormControl v-model="reference.label" type="text" class="grow" :placeholder="tr('Name (e.g. Shera mascot)', 'Tên (vd. Gấu Shera)')" />
            <FormControl v-model="reference.role" type="select" class="w-36" :options="roleOptions" />
            <Button variant="ghost" @click="references.splice(index, 1)">✕</Button>
          </div>
          <FileUploader :file-types="['image/*']" @success="addReference" @failure="(e) => (error = String(e?.message || e))">
            <template #default="{ uploading, progress, openFileSelector }">
              <Button :loading="uploading" @click="openFileSelector">
                {{ uploading ? `${progress}%` : '+ ' + tr('Add an image', 'Thêm hình ảnh') }}
              </Button>
            </template>
          </FileUploader>
          <p class="mt-1 text-[11px] text-ink-muted">
            {{ tr('Leave the type on Auto; it is guessed from the name.', 'Để loại là Tự động; hệ thống đoán theo tên.') }}
          </p>
        </div>

        <!-- 3. Format -->
        <FormControl v-model="form.format" type="select" :label="tr('3. Format', '3. Định dạng')" :options="formatOptions" />

        <Alert v-if="error" theme="red" :title="error" />
      </div>
    </template>
    <template #actions>
      <Button variant="solid" :loading="creating" :disabled="!canCreate" @click="create">
        {{ tr('Create project', 'Tạo dự án') }}
      </Button>
    </template>
  </Dialog>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { Alert, Button, Dialog, FileUploader, FormControl, call } from "frappe-ui";
import { tr } from "../stores/i18n";
import { errorMessage } from "../utils/errors";

const open = defineModel({ type: Boolean, default: false });
const emit = defineEmits(["created"]);

const form = reactive({ name: "", brief: "", format: "" });
const workbook = ref(null);
const references = ref([]);
const creating = ref(false);
const error = ref("");

const roleOptions = computed(() => [
  { label: tr("Auto", "Tự động"), value: "" },
  { label: tr("Character", "Nhân vật"), value: "Character" },
  { label: tr("Product", "Sản phẩm"), value: "Product" },
  { label: tr("Environment", "Bối cảnh"), value: "Environment" },
  { label: tr("Other", "Khác"), value: "General" },
]);
const formatOptions = computed(() => [
  { label: tr("Auto (from the storyboard)", "Tự động (theo kịch bản)"), value: "" },
  { label: tr("Portrait 9:16 — TikTok, Reels", "Dọc 9:16 — TikTok, Reels"), value: "Portrait" },
  { label: tr("Landscape 16:9 — YouTube, web", "Ngang 16:9 — YouTube, web"), value: "Landscape" },
  { label: tr("Square 1:1", "Vuông 1:1"), value: "Square" },
]);

const canCreate = computed(() => Boolean(workbook.value || form.brief.trim()));

function requireWorkbook(file) {
  return file.name.toLowerCase().endsWith(".xlsx") ? null : tr("Please choose an .xlsx workbook.", "Vui lòng chọn tệp .xlsx.");
}

function addReference(file) {
  const stem = String(file.file_name || "").replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  references.value.push({ file_name: file.name, file_url: file.file_url, label: stem, role: "" });
}

async function create() {
  creating.value = true;
  error.value = "";
  try {
    const result = await call("joymedia.services.project_intake.create_project_from_brief", {
      project_name: form.name || null,
      video_idea: form.brief || null,
      workbook_file: workbook.value?.name || null,
      format: form.format || null,
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
