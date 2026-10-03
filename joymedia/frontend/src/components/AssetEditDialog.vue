<template>
  <div
    class="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs"
    @click.self="$emit('close')"
    @keydown.esc="$emit('close')"
  >
    <form
      class="w-full max-w-sm bg-surface-card border border-outline-border rounded-2xl p-5 shadow-2xl text-xs space-y-4 text-ink-primary"
      @submit.prevent="save"
    >
      <div class="flex items-center justify-between pb-3 border-b border-outline-border">
        <h3 class="text-sm font-bold">{{ isVi ? 'Sửa tư liệu' : 'Edit media' }}</h3>
        <button type="button" class="text-ink-secondary hover:text-ink-primary cursor-pointer" @click="$emit('close')">✕</button>
      </div>

      <div>
        <label class="block text-ink-secondary font-semibold mb-1" for="asset-edit-name">{{ isVi ? 'Tên' : 'Name' }}</label>
        <input
          id="asset-edit-name"
          ref="nameInput"
          v-model="name"
          type="text"
          maxlength="140"
          class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary focus:outline-none focus:border-indigo-500"
        />
        <p class="text-[10.5px] text-ink-muted mt-1">
          {{ isVi
            ? 'Đặt tên mô tả nội dung ảnh (vd: "hồ bơi", "sảnh") để AI hiểu đúng bối cảnh.'
            : 'Describe what the picture shows (e.g. "pool", "lobby") so the AI director uses it correctly.' }}
        </p>
      </div>

      <div>
        <label class="block text-ink-secondary font-semibold mb-1">{{ isVi ? 'Phân loại' : 'Category' }}</label>
        <FormControl v-model="category" type="select" :options="categoryOptions" />
      </div>

      <div class="flex items-center justify-end gap-2 pt-3 border-t border-outline-border">
        <Button type="button" variant="subtle" @click="$emit('close')">{{ isVi ? 'Hủy' : 'Cancel' }}</Button>
        <Button type="submit" variant="solid" :loading="saving" :disabled="!name.trim() || !changed">
          {{ isVi ? 'Lưu' : 'Save' }}
        </Button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import { Button, FormControl, call } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useI18n } from "../stores/i18n";

const props = defineProps({
  asset: { type: Object, required: true },
});
const emit = defineEmits(["close", "saved"]);

const { t, currentLang } = useI18n();
const isVi = computed(() => currentLang.value === "vi");
const name = ref(props.asset.asset_name || "");
const category = ref(props.asset.asset_category || "Reference");
const saving = ref(false);
const nameInput = ref(null);

const CATEGORIES = ["Product", "Character", "Background", "Brand", "Style", "Reference"];
const categoryOptions = computed(() => {
  const values = CATEGORIES.includes(props.asset.asset_category) || !props.asset.asset_category
    ? CATEGORIES
    : [...CATEGORIES, props.asset.asset_category];
  return values.map((value) => {
    const key = `cat_${value.toLowerCase()}`;
    const label = t(key);
    return { label: label === key ? value : label, value };
  });
});
const changed = computed(
  () => name.value.trim() !== (props.asset.asset_name || "") || category.value !== props.asset.asset_category
);

onMounted(() => nextTick(() => nameInput.value?.select()));

async function save() {
  if (!name.value.trim() || !changed.value || saving.value) return;
  saving.value = true;
  try {
    const result = await call("joymedia.services.media_asset_service.update_media_asset", {
      media_asset: props.asset.name,
      asset_name: name.value.trim(),
      asset_category: category.value,
    });
    notify({ title: isVi.value ? "Đã lưu tư liệu" : "Media updated", text: result.asset_name, type: "success" });
    emit("saved", result);
  } catch (err) {
    notify({ title: isVi.value ? "Không thể lưu" : "Could not save", text: errorMessage(err, ""), type: "error" });
  } finally {
    saving.value = false;
  }
}
</script>
