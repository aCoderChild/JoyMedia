<template>
  <section class="rounded-2xl border border-outline-border bg-surface-card p-3 space-y-2" data-test="timeline-comments">
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <span class="font-bold uppercase tracking-wider text-ink-primary">💬 {{ tr('Comments', 'Nhận xét') }}</span>
      <span class="font-mono text-ink-secondary" data-test="timeline-comment-position">
        {{ here ? `${tr('Scene', 'Cảnh')} ${here.number} · ${seconds(here.frame)}s · ${tr('frame', 'khung')} ${here.frame}` : tr('Move the playhead onto a scene', 'Đưa đầu đọc vào một cảnh') }}
      </span>
      <Button size="sm" variant="subtle" :disabled="!here" @click="markIn">{{ tr('Mark start', 'Đánh dấu đầu') }}</Button>
      <Button size="sm" variant="subtle" :disabled="!range || !here || here.shot !== range.shot" @click="markOut">{{ tr('Mark end', 'Đánh dấu cuối') }}</Button>
      <Button v-if="range" size="sm" variant="ghost" @click="range = null">✕ {{ rangeLabel }}</Button>
    </div>
    <div class="flex gap-2">
      <FormControl
        v-model="text" type="textarea" :rows="1" class="grow" maxlength="2000" data-test="timeline-comment-text"
        :placeholder="tr('What should change at the playhead (or in the marked range)? Ctrl+Enter to add', 'Cần sửa gì tại đầu đọc (hoặc trong đoạn đã đánh dấu)? Ctrl+Enter để thêm')"
        @keydown.ctrl.enter.prevent="add" @keydown.meta.enter.prevent="add"
      />
      <Button variant="solid" :loading="adding" :disabled="!text.trim() || !target" data-test="timeline-comment-add" @click="add">
        {{ tr('Add', 'Thêm') }}
      </Button>
    </div>

    <ul v-if="rows.length" class="max-h-48 space-y-1 overflow-y-auto" data-test="timeline-comment-list">
      <li
        v-for="row in rows" :key="row.name" :data-status="row.status"
        class="flex items-start gap-2 rounded-lg border border-outline-border p-1.5 text-[11px]" :class="{ 'opacity-60': row.status !== 'Open' }"
      >
        <button type="button" class="shrink-0 font-mono font-semibold text-indigo-400 hover:underline" :disabled="row.at === null" @click="$emit('seek', row.at)">
          {{ `${tr('Scene', 'Cảnh')} ${row.number}` }} · {{ row.when }}
        </button>
        <span class="grow whitespace-pre-wrap break-words text-ink-primary">{{ row.comment }}</span>
        <Badge :theme="row.status === 'Open' ? 'orange' : row.status === 'Addressed' ? 'blue' : 'green'" :label="statusLabel(row.status)" />
        <button v-if="row.status === 'Open'" type="button" class="text-ink-muted hover:text-ink-primary" @click="setStatus(row, 'Resolved')">{{ tr('Done', 'Xong') }}</button>
        <button type="button" class="text-ink-muted hover:text-rose-400" @click="remove(row)">✕</button>
      </li>
    </ul>

    <div v-if="openScenes.length" class="flex flex-wrap items-center gap-2 pt-1">
      <span class="text-[11px] text-ink-muted">{{ tr('Apply the open comments to a new take of:', 'Áp dụng nhận xét chưa xử lý để tạo bản mới cho:') }}</span>
      <Button
        v-for="scene in openScenes" :key="scene.shot" size="sm" variant="solid" theme="blue" :loading="applying === scene.shot"
        :disabled="busyShots.includes(scene.shot) || Boolean(applying)" data-test="timeline-comment-apply" @click="apply(scene.shot)"
      >
        {{ tr('Scene', 'Cảnh') }} {{ scene.number }} ({{ scene.count }})
      </Button>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Badge, Button, FormControl, call } from "frappe-ui";
import { tr } from "../../stores/i18n";
import { notify } from "../../utils/notify";
import { errorMessage } from "../../utils/errors";
import { useProjectRealtime } from "../../composables/useProjectRealtime";

// Comments on frames and ranges of the film, made in the timeline: the playhead tells which scene and which of its own
// frames. They are stored on the scene's take (services/review/comments.py) and applied to a new take of that scene.
const props = defineProps({
  projectName: { type: String, required: true },
  videoClips: { type: Array, default: () => [] },
  shots: { type: Array, default: () => [] },
  fps: { type: Number, default: 24 },
  playheadFrame: { type: Number, default: 0 },
  busyShots: { type: Array, default: () => [] },
});
const emit = defineEmits(["seek", "markers", "applied"]);

const comments = ref([]);
const text = ref("");
const range = ref(null);
const adding = ref(false);
const applying = ref("");

const seconds = (frame) => (frame / props.fps).toFixed(1);
const clock = (value) => Number(Number(value).toFixed(2)).toString();
const numberOf = (shot) => props.shots.find((row) => row.name === shot)?.shot_number ?? "?";
const statusLabel = (status) => ({ Open: tr("Open", "Chưa xử lý"), Addressed: tr("Sent to a new take", "Đã gửi tạo bản mới"), Resolved: tr("Done", "Đã xong") }[status]);

const clipEnd = (clip) => Number(clip.timeline_start_frame || 0) + Number(clip.source_out_frame || 0) - Number(clip.source_in_frame || 0);
// The scene under the playhead and the frame of its own take the playhead shows.
const here = computed(() => {
  const clip = props.videoClips.find((row) => row.shot && props.playheadFrame >= Number(row.timeline_start_frame || 0) && props.playheadFrame < clipEnd(row));
  if (!clip) return null;
  const frame = Number(clip.source_in_frame || 0) + Math.round(props.playheadFrame) - Number(clip.timeline_start_frame || 0);
  return { shot: clip.shot, number: numberOf(clip.shot), frame, clip };
});
// Where a frame of a scene's take sits on the timeline, or null when the edit no longer shows it.
function timelineFrame(shot, frame) {
  const clip = props.videoClips.find((row) => row.shot === shot && frame >= Number(row.source_in_frame || 0) && frame < Number(row.source_out_frame || 0));
  return clip ? Number(clip.timeline_start_frame || 0) + frame - Number(clip.source_in_frame || 0) : null;
}

const target = computed(() => (range.value && here.value && range.value.shot === here.value.shot ? range.value : here.value
  ? { shot: here.value.shot, start: here.value.frame, end: here.value.frame } : null));
const rangeLabel = computed(() => (range.value
  ? `${tr('Scene', 'Cảnh')} ${numberOf(range.value.shot)} · ${seconds(range.value.start)}–${seconds(range.value.end + 1)}s` : ""));

function markIn() {
  if (!here.value) return;
  range.value = { shot: here.value.shot, start: here.value.frame, end: here.value.frame };
}
function markOut() {
  if (!range.value || !here.value || here.value.shot !== range.value.shot) return;
  const [start, end] = [range.value.start, here.value.frame].sort((a, b) => a - b);
  range.value = { ...range.value, start, end };
}

const rows = computed(() => comments.value
  .filter((row) => row.current_take)
  .map((row) => {
    const frames = row.scope === "Frames";
    return {
      ...row,
      number: numberOf(row.shot),
      at: frames ? timelineFrame(row.shot, row.start_frame) : null,
      when: !frames ? tr("whole scene", "cả cảnh") : row.start_frame === row.end_frame
        ? `${clock(row.start_seconds)}s` : `${clock(row.start_seconds)}–${clock(row.end_seconds)}s`,
    };
  })
  .sort((a, b) => (a.number - b.number) || ((a.start_frame ?? -1) - (b.start_frame ?? -1))));

const openScenes = computed(() => {
  const counts = {};
  for (const row of rows.value) if (row.status === "Open") counts[row.shot] = (counts[row.shot] || 0) + 1;
  return Object.entries(counts).map(([shot, count]) => ({ shot, count, number: numberOf(shot) })).sort((a, b) => a.number - b.number);
});

// Markers for the timeline: every frame comment on the current takes, and the range being marked.
watch([rows, range, () => props.videoClips], () => {
  const markers = [];
  for (const row of rows.value) {
    if (row.scope !== "Frames" || row.at === null) continue;
    markers.push({ key: row.name, start: row.at, end: timelineFrame(row.shot, row.end_frame) ?? row.at, status: row.status, text: row.comment });
  }
  if (range.value) {
    const start = timelineFrame(range.value.shot, range.value.start);
    if (start !== null) markers.push({ key: "pending", kind: "pending", start, end: timelineFrame(range.value.shot, range.value.end) ?? start, text: rangeLabel.value });
  }
  emit("markers", markers);
}, { immediate: true, deep: true });

async function load() {
  try {
    comments.value = await call("joymedia.services.review.comments.get_review_comments", { project_name: props.projectName });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, ""), type: "error" });
  }
}

async function add() {
  const note = text.value.trim();
  if (!note || !target.value || adding.value) return;
  adding.value = true;
  try {
    await call("joymedia.services.review.comments.add_review_comment", {
      project_name: props.projectName, shot_name: target.value.shot, comment: note, start_frame: target.value.start, end_frame: target.value.end,
    });
    text.value = "";
    range.value = null;
    await load();
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, tr("Could not add the comment.", "Không thêm được nhận xét.")), type: "error" });
  } finally {
    adding.value = false;
  }
}

async function setStatus(row, status) {
  try {
    await call("joymedia.services.review.comments.set_review_comment_status", { project_name: props.projectName, comment_name: row.name, status });
    await load();
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, ""), type: "error" });
  }
}

async function remove(row) {
  try {
    await call("joymedia.services.review.comments.delete_review_comment", { project_name: props.projectName, comment_name: row.name });
    await load();
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, ""), type: "error" });
  }
}

async function apply(shot) {
  applying.value = shot;
  try {
    const result = await call("joymedia.services.review.comments.apply_review_comments", { project_name: props.projectName, shot_names: [shot] });
    const failed = result.scenes.find((row) => !row.applied);
    if (failed) throw new Error(failed.error);
    notify({ title: tr("Making a new take", "Đang tạo bản mới"), text: tr("The current take stays until the new one is ready.", "Bản hiện tại được giữ cho đến khi bản mới xong."), type: "success" });
    await load();
    emit("applied", { regenerating: true });
  } catch (err) {
    notify({ title: tr("Comments", "Nhận xét"), text: errorMessage(err, tr("Could not apply the comments.", "Không áp dụng được nhận xét.")), type: "error" });
  } finally {
    applying.value = "";
  }
}

let reloadTimer = null;
useProjectRealtime(props.projectName, { joymedia_project_updated: () => { clearTimeout(reloadTimer); reloadTimer = setTimeout(load, 300); } });
onBeforeUnmount(() => clearTimeout(reloadTimer));
load();
</script>
