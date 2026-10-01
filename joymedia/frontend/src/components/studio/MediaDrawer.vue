<template>
  <aside class="studio-media-drawer flex flex-col h-full bg-surface-card border-r border-outline-border w-[270px] shrink-0 select-none z-20">
    <!-- Drawer Header -->
    <div class="flex items-center justify-between border-b border-outline-border px-4 py-3 bg-surface-muted/60">
      <div class="min-w-0">
        <h2 class="text-xs font-bold text-ink-primary uppercase tracking-wider flex items-center gap-1.5">
          <span>▧</span>
          <span>{{ currentLang === 'vi' ? 'Tư liệu Dự án' : 'Project Media' }}</span>
        </h2>
        <p class="text-[11px] text-ink-muted mt-0.5 truncate">
          {{ projectAssets.length }} {{ currentLang === 'vi' ? 'tư liệu được chọn' : 'selected ingredients' }}
        </p>
      </div>
      <button
        type="button"
        class="text-ink-muted hover:text-ink-primary p-1 rounded-lg hover:bg-surface-hover cursor-pointer transition-colors"
        @click="$emit('close')"
      >
        ✕
      </button>
    </div>

    <!-- Assets List -->
    <div class="flex-1 overflow-y-auto p-3 space-y-2">
      <div v-if="projectAssets.length" class="grid grid-cols-2 gap-2">
        <div
          v-for="asset in projectAssets"
          :key="asset.asset_version || asset.name"
          class="group relative rounded-xl border text-left transition-all overflow-hidden cursor-pointer"
          :class="[
            selectedAsset?.asset_version === asset.asset_version
              ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/30'
              : 'border-outline-border bg-surface-muted hover:border-indigo-400'
          ]"
          @click="$emit('selectAsset', asset)"
        >
          <!-- Media Thumbnail -->
          <MediaThumbnail
            :src="asset.file"
            :media-type="asset.media_type"
            :alt="asset.asset_name"
            :duration="asset.duration_seconds"
            :badge="asset.reference_role || asset.asset_category"
            aspect="aspect-square"
          />

          <!-- Asset Info -->
          <div class="p-2">
            <span class="block truncate text-[11px] font-semibold text-ink-primary" :title="asset.asset_name">
              {{ asset.asset_name }}
            </span>
            <div class="flex items-center justify-between text-[10px] text-ink-muted mt-0.5">
              <span class="truncate font-medium text-indigo-400">
                {{ formatRole(asset.reference_role || asset.asset_category) }}
              </span>
              <button
                type="button"
                class="opacity-0 group-hover:opacity-100 text-rose-400 hover:text-rose-300 p-0.5 rounded cursor-pointer transition-opacity"
                :title="currentLang === 'vi' ? 'Bỏ tư liệu này' : 'Remove reference'"
                @click.stop="$emit('removeAsset', asset)"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="py-12 text-center text-xs text-ink-muted px-3">
        <span class="text-3xl block mb-2 opacity-50">📂</span>
        <p class="font-semibold text-ink-primary">{{ currentLang === 'vi' ? 'Chưa có tư liệu nào' : 'No references added yet' }}</p>
        <p class="mt-1 text-[11px]">
          {{ currentLang === 'vi' ? 'Thêm hình ảnh sản phẩm, nhân vật hoặc phong cách để AI sử dụng.' : 'Add product, character, or style media to guide video generation.' }}
        </p>
      </div>
    </div>

    <!-- Drawer Footer Actions -->
    <div class="border-t border-outline-border p-3 bg-surface-muted/40 space-y-2">
      <button
        type="button"
        class="jm-btn-primary w-full text-xs !py-2 flex items-center justify-center gap-1.5 shadow-sm cursor-pointer"
        @click="$emit('openMediaPicker')"
      >
        <span>+</span>
        <span>{{ currentLang === 'vi' ? 'Thêm tư liệu tham chiếu' : 'Add Reference Media' }}</span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import MediaThumbnail from "../MediaThumbnail.vue";

const props = defineProps({
  projectAssets: { type: Array, default: () => [] },
  selectedAsset: { type: Object, default: null },
  currentLang: { type: String, default: "en" },
});

defineEmits(["close", "selectAsset", "removeAsset", "openMediaPicker"]);

function formatRole(role) {
  if (!role) return "General";
  return role;
}
</script>
