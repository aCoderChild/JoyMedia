<template>
  <aside class="studio-media-drawer flex flex-col h-full bg-surface-card border-r border-outline-border w-[270px] shrink-0 select-none z-20">
    <!-- Drawer Header -->
    <div class="flex items-center justify-between border-b border-outline-border px-3.5 py-2.5 bg-surface-muted/60">
      <div class="min-w-0">
        <h2 class="text-xs font-bold text-ink-primary uppercase tracking-wider flex items-center gap-1.5">
          <span>▧</span>
          <span>{{ currentLang === 'vi' ? 'Tư liệu' : 'Project Media' }}</span>
        </h2>
        <p class="text-[10px] text-ink-muted mt-0.5 truncate">
          {{ projectAssets.length }} {{ currentLang === 'vi' ? 'tư liệu' : 'ingredients' }}
        </p>
      </div>

      <div class="flex items-center gap-1">
        <!-- Compact + Button in Header -->
        <button
          type="button"
          class="p-1 rounded-lg text-ink-secondary hover:text-indigo-400 hover:bg-surface-hover cursor-pointer transition-colors"
          :title="currentLang === 'vi' ? 'Thêm tư liệu' : 'Add reference'"
          @click="$emit('openMediaPicker')"
        >
          <span class="text-base font-bold leading-none">+</span>
        </button>

        <button
          type="button"
          class="text-ink-muted hover:text-ink-primary p-1 rounded-lg hover:bg-surface-hover cursor-pointer transition-colors"
          :title="currentLang === 'vi' ? 'Đóng' : 'Close'"
          @click="$emit('close')"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Assets List: Compact Horizontal Ingredient Rows -->
    <div class="flex-1 overflow-y-auto p-2.5 space-y-1.5">
      <div v-if="projectAssets.length" class="space-y-1.5">
        <div
          v-for="asset in projectAssets"
          :key="asset.asset_version || asset.name"
          class="group relative flex items-center gap-2.5 p-1.5 rounded-xl border transition-all cursor-pointer"
          :class="[
            selectedAsset?.asset_version === asset.asset_version
              ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/30'
              : 'border-outline-border bg-surface-muted/60 hover:bg-surface-hover hover:border-indigo-400/50'
          ]"
          @click="$emit('selectAsset', asset)"
        >
          <!-- Thumbnail: 44px square -->
          <div class="size-11 rounded-lg overflow-hidden shrink-0 bg-surface-base border border-outline-border relative">
            <MediaThumbnail
              :src="asset.file"
              :media-type="asset.media_type"
              :alt="asset.asset_name"
              :duration="asset.duration_seconds"
              aspect="aspect-square"
            />
          </div>

          <!-- Name & Role -->
          <div class="min-w-0 flex-1">
            <span class="block truncate text-xs font-semibold text-ink-primary" :title="asset.asset_name">
              {{ asset.asset_name }}
            </span>
            <span class="block text-[10px] text-ink-muted capitalize">
              {{ formatRole(asset.reference_role || asset.asset_category) }}
            </span>
          </div>

          <!-- Remove hover button -->
          <button
            type="button"
            class="opacity-0 group-hover:opacity-100 text-ink-muted hover:text-rose-400 p-1 rounded-md hover:bg-surface-card cursor-pointer transition-all shrink-0"
            :title="currentLang === 'vi' ? 'Bỏ tư liệu này' : 'Remove reference'"
            @click.stop="$emit('removeAsset', asset)"
          >
            ✕
          </button>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="py-10 text-center text-xs text-ink-muted px-3">
        <span class="text-2xl block mb-1.5 opacity-50">📂</span>
        <p class="font-semibold text-ink-primary">{{ currentLang === 'vi' ? 'Chưa có tư liệu nào' : 'No references added yet' }}</p>
        <p class="mt-1 text-[11px]">
          {{ currentLang === 'vi' ? 'Bấm nút + ở trên để thêm hình ảnh hoặc video tham chiếu.' : 'Click + above to add reference media.' }}
        </p>
      </div>
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
