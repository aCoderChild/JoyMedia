<template>
  <section class="space-y-2 border-t border-outline-border pt-2" data-test="scene-review">
    <div class="flex items-center justify-between">
      <label class="block text-[11px] font-semibold text-ink-secondary">{{ tr('Comments on this scene', 'Nhận xét cảnh này') }}</label>
      <Badge v-if="openHere.length" theme="orange" :label="tr(`${openHere.length} open`, `${openHere.length} chưa xử lý`)" />
    </div>

    <FormControl
      v-model="text" type="textarea" :rows="2" maxlength="2000" data-test="review-text"
      :placeholder="tr('What should change in this scene as a whole? (Ctrl+Enter to add)', 'Cả cảnh này cần sửa gì? (Ctrl+Enter để thêm)')"
      @keydown.ctrl.enter.prevent="add" @keydown.meta.enter.prevent="add"
    />
    <Button variant="solid" class="w-full" :loading="adding" :disabled="!text.trim()" data-test="review-add" @click="add">
      {{ compact ? tr('Save feedback', 'Lưu yêu cầu') : tr('Comment on the whole scene', 'Nhận xét cho cả cảnh') }}
    </Button>
    <p v-if="!compact" class="text-[10px] text-ink-muted">
      {{ tr('To comment on a moment or a range of frames, use the Timeline view: the playhead picks the frame.', 'Để nhận xét một khoảnh khắc hoặc một đoạn khung hình, dùng chế độ Dòng thời gian: đầu đọc chọn khung hình.') }}
    </p>

    <ul v-if="comments.length" class="space-y-1" data-test="review-list">
      <li
        v-for="item in comments" :key="item.name" :data-status="item.status"
        class="rounded-lg border border-outline-border p-1.5 text-[11px]" :class="{ 'opacity-60': item.status !== 'Open' || !item.current_take }"
      >
        <div class="flex items-center gap-1">
          <span class="font-mono font-semibold text-rio-400">{{ when(item) }}</span>
          <Badge :theme="item.status === 'Open' ? 'orange' : item.status === 'Addressed' ? 'blue' : 'green'" :label="statusLabel(item)" />
          <span class="ml-auto truncate text-ink-muted">{{ item.author_name }}</span>
        </div>
        <p class="mt-0.5 whitespace-pre-wrap break-words text-ink-primary">{{ item.comment }}</p>
        <div class="mt-0.5 flex gap-2 text-ink-muted">
          <button v-if="item.status === 'Open'" type="button" class="hover:text-ink-primary" @click="setStatus(item, 'Resolved')">{{ tr('Mark done', 'Đã xong') }}</button>
          <button v-else-if="item.status === 'Resolved'" type="button" class="hover:text-ink-primary" @click="setStatus(item, 'Open')">{{ tr('Reopen', 'Mở lại') }}</button>
          <button type="button" class="hover:text-rose-400" @click="remove(item)">{{ tr('Delete', 'Xoá') }}</button>
        </div>
      </li>
    </ul>

    <Button
      v-if="openHere.length" variant="solid" theme="blue" class="w-full" :loading="applying" :disabled="busy" data-test="review-apply" @click="apply"
    >
      {{ compact ? tr('Create revised scene', 'Tạo cảnh đã chỉnh sửa') : tr(`Apply ${openHere.length} comment(s): new take`, `Áp dụng ${openHere.length} nhận xét: tạo bản mới`) }}
    </Button>
    <p v-if="openHere.length" class="text-[10px] text-ink-muted">
      {{ busy ? tr('The scene is rendering. Wait for it to finish.', 'Cảnh đang được tạo. Hãy chờ hoàn tất.')
        : tr('Your comments are written into the scene and a new take is made from the same approved first frame; the current take stays until it is ready.', 'Nhận xét được ghi vào cảnh và bản mới được tạo từ cùng khung hình đầu đã duyệt; bản hiện tại được giữ đến khi bản mới xong.') }}
    </p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Badge, Button, FormControl, call } from "frappe-ui";
import { tr } from "../../stores/i18n";
import { notify } from "../../utils/notify";
import { errorMessage } from "../../utils/errors";
import { useProjectRealtime } from "../../composables/useProjectRealtime";

// General comments on a whole scene, from the storyboard. Frame and range comments are made in the timeline view
// (TimelineComments.vue); both kinds are listed here and applied together to a new take.
const props = defineProps({
  projectName: { type: String, required: true },
  shot: { type: Object, required: true },
  fps: { type: Number, default: 24 },
  busy: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
});
const emit = defineEmits(["applied"]);

const comments = ref([]);
const text = ref("");
const adding = ref(false);
const applying = ref(false);

const openHere = computed(() => comments.value.filter((item) => item.current_take && item.status === "Open"));
const clock = (value) => Number(Number(value).toFixed(2)).toString();
const when = (item) => (item.scope !== "Frames" ? tr("Whole scene", "Cả cảnh")
  : item.start_frame === item.end_frame ? `${clock(item.start_seconds)}s` : `${clock(item.start_seconds)}–${clock(item.end_seconds)}s`);
const statusLabel = (item) => (!item.current_take
  ? tr("Earlier take", "Bản cũ")
  : { Open: tr("Open", "Chưa xử lý"), Addressed: tr("Sent to a new take", "Đã gửi tạo bản mới"), Resolved: tr("Done", "Đã xong") }[item.status]);

async function load() {
  try {
    comments.value = await call("joymedia.services.review.comments.get_review_comments", { project_name: props.projectName, shot_name: props.shot.name });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, tr("Could not load the comments.", "Không tải được nhận xét.")), type: "error" });
  }
}

async function add() {
  const note = text.value.trim();
  if (!note || adding.value) return;
  adding.value = true;
  try {
    await call("joymedia.services.review.comments.add_review_comment", {
      project_name: props.projectName, shot_name: props.shot.name, comment: note, whole_scene: 1,
    });
    text.value = "";
    await load();
    emit("applied", { refresh: true });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, tr("Could not add the comment.", "Không thêm được nhận xét.")), type: "error" });
  } finally {
    adding.value = false;
  }
}

async function setStatus(item, status) {
  try {
    await call("joymedia.services.review.comments.set_review_comment_status", { project_name: props.projectName, comment_name: item.name, status });
    await load();
    emit("applied", { refresh: true });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, ""), type: "error" });
  }
}

async function remove(item) {
  try {
    await call("joymedia.services.review.comments.delete_review_comment", { project_name: props.projectName, comment_name: item.name });
    await load();
    emit("applied", { refresh: true });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, ""), type: "error" });
  }
}

async function apply() {
  if (applying.value || !openHere.value.length) return;
  applying.value = true;
  try {
    const result = await call("joymedia.services.review.comments.apply_review_comments", { project_name: props.projectName, shot_names: [props.shot.name] });
    const failed = result.scenes.find((row) => !row.applied);
    if (failed) throw new Error(failed.error);
    notify({
      title: tr("Making a new take", "Đang tạo bản mới"),
      text: tr("The current take stays until the new one is ready.", "Bản hiện tại được giữ cho đến khi bản mới xong."),
      type: "success",
    });
    await load();
    emit("applied", { regenerating: true });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, tr("Could not apply the comments.", "Không áp dụng được nhận xét.")), type: "error" });
    await load();
  } finally {
    applying.value = false;
  }
}

let reloadTimer = null;
useProjectRealtime(props.projectName, { joymedia_project_updated: () => { clearTimeout(reloadTimer); reloadTimer = setTimeout(load, 300); } });
onBeforeUnmount(() => clearTimeout(reloadTimer));
watch(() => [props.shot.name, props.shot.output_video], load, { immediate: true });
</script>
