<template>
  <section v-if="rows.length" class="rounded-2xl border border-outline-border bg-surface-card p-3.5" data-test="keyframes">
    <header class="mb-2 flex items-center justify-between gap-3">
      <h3 class="text-sm font-bold text-ink-primary">
        {{ tr('Storyboard frames', 'Khung hình kịch bản') }}
        <Badge class="ml-1.5" :theme="allApproved ? 'green' : 'amber'"
          :label="allApproved ? tr('All approved', 'Đã duyệt hết') : `${approvedCount}/${needed.length} ${tr('approved', 'đã duyệt')}`" />
      </h3>
      <Button size="sm" variant="subtle" :loading="drawing" @click="draw()">
        {{ tr('Draw all frames', 'Vẽ tất cả khung hình') }}
      </Button>
    </header>
    <p class="mb-2 text-xs text-ink-muted">
      {{ tr('Approve each first frame before video is made: a frame takes about a minute, a video several.',
            'Hãy duyệt khung hình đầu của từng cảnh trước khi tạo video: một khung hình mất khoảng một phút, video mất nhiều phút hơn.') }}
    </p>

    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <figure v-for="row in rows" :key="row.shot" class="flex flex-col gap-1.5 text-xs">
        <div class="relative overflow-hidden rounded-xl border border-outline-border bg-surface-base" style="aspect-ratio: 9 / 16">
          <img v-if="row.url" :src="row.url" :alt="row.shot_name" class="h-full w-full object-cover" loading="lazy" />
          <div v-else class="flex h-full items-center justify-center px-2 text-center text-ink-muted">
            {{ row.needs_keyframe ? tr('No frame yet', 'Chưa có khung hình')
              : tr('Continues from the previous scene', 'Tiếp nối từ cảnh trước') }}
          </div>
        </div>
        <figcaption class="flex items-center justify-between gap-1">
          <span class="truncate font-semibold text-ink-primary" :title="row.shot_name">{{ row.shot_number }}. {{ row.shot_name }}</span>
          <Badge v-if="row.url" :theme="row.stale ? 'red' : row.status === 'Approved' ? 'green' : 'amber'"
            :label="row.stale ? tr('Out of date', 'Đã cũ') : row.status === 'Approved' ? tr('Approved', 'Đã duyệt') : tr('To review', 'Chờ duyệt')" />
        </figcaption>
        <div v-if="row.needs_keyframe" class="flex gap-1.5">
          <Button v-if="row.url && !row.stale" size="sm" :variant="row.status === 'Approved' ? 'subtle' : 'solid'" class="flex-1"
            @click="approve(row, row.status !== 'Approved')">
            {{ row.status === 'Approved' ? tr('Undo', 'Hoàn tác') : tr('Approve', 'Duyệt') }}
          </Button>
          <Button size="sm" variant="subtle" class="flex-1" :loading="busy === row.shot" @click="draw([row.shot])">
            {{ row.url ? tr('Redraw', 'Vẽ lại') : tr('Draw', 'Vẽ') }}
          </Button>
        </div>
      </figure>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { Badge, Button, call, createResource } from "frappe-ui";
import { tr } from "../../stores/i18n";
import { notify } from "../../utils/notify";
import { errorMessage } from "../../utils/errors";
import { useProjectRealtime } from "../../composables/useProjectRealtime";

const props = defineProps({ projectName: { type: String, required: true } });
const emit = defineEmits(["changed"]);

const keyframes = createResource({
  url: "joymedia.services.keyframes.stage.get_project_keyframes",
  params: { project_name: props.projectName },
  auto: true,
});
const rows = computed(() => keyframes.data || []);
const needed = computed(() => rows.value.filter((row) => row.needs_keyframe));
const approvedCount = computed(() => needed.value.filter((row) => row.status === "Approved" && !row.stale).length);
const allApproved = computed(() => needed.value.length > 0 && approvedCount.value === needed.value.length);

// Frappe pushes a change when a frame finishes or is approved; reload instead of polling.
let reloadTimer = null;
useProjectRealtime(props.projectName, {
  joymedia_project_updated: () => {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => keyframes.reload(), 400);
  },
});

const drawing = ref(false);
const busy = ref("");
async function draw(shots) {
  drawing.value = !shots;
  busy.value = shots?.[0] || "";
  try {
    await call("joymedia.services.keyframes.stage.generate_keyframes", { project_name: props.projectName, shot_names: shots || null });
    notify({ title: tr("Frames", "Khung hình"), text: tr("Drawing started. They appear here as they finish.", "Đã bắt đầu vẽ. Khung hình sẽ hiện ở đây khi xong."), type: "success" });
    emit("changed");
  } catch (err) {
    notify({ title: tr("Frames", "Khung hình"), text: errorMessage(err, tr("Unable to draw the frames.", "Không thể vẽ khung hình.")), type: "error" });
  } finally {
    drawing.value = false;
    busy.value = "";
  }
}

async function approve(row, approved) {
  try {
    await call("joymedia.services.keyframes.stage.set_keyframe_approval", { project_name: props.projectName, shot_name: row.shot, approved });
    keyframes.reload();
  } catch (err) {
    notify({ title: tr("Frames", "Khung hình"), text: errorMessage(err, tr("Unable to change the approval.", "Không thể đổi trạng thái duyệt.")), type: "error" });
  }
}
</script>
