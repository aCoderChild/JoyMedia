<template>
  <div class="audio-timeline-tracks space-y-2">
    <div class="flex items-center justify-between px-1">
      <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider">Audio</span>
      <span class="text-[11px] text-ink-secondary">
        {{ audioTracks.length }} {{ currentLang === 'vi' ? 'track âm thanh' : 'audio tracks' }}
      </span>
    </div>

    <div class="audio-timeline-canvas" :style="{ width: `${timelineCanvasWidth}px` }">
        <div
          v-for="track in audioTracks"
          :key="track.trackIndex"
          class="audio-timeline-row"
        >
          <div class="audio-timeline-label">
            Audio {{ track.trackIndex + 1 }}<span v-if="track.trackIndex === 0"> · {{ currentLang === 'vi' ? 'Nguồn' : 'Source' }}</span>
          </div>
          <div class="audio-timeline-lane">
            <div v-if="!track.clips.length" class="audio-timeline-empty-label">
              {{ currentLang === 'vi' ? 'Không có audio nguồn' : 'No source audio' }}
            </div>
            <template v-for="clip in track.clips" :key="clip.name">
              <button
                v-if="!clip.is_silent_source && (clip.audio_role !== 'Source' || clip.source_has_audio)"
                type="button"
                class="audio-timeline-clip"
                :class="[
                  clip.audio_role === 'Source' ? 'audio-timeline-source-clip' : 'audio-timeline-user-clip',
                  { selected: selectedClipName === clip.name }
                ]"
                :style="clipStyle(clip)"
                :title="clip.source_asset_name || clipLabel(clip)"
                @pointerdown="startMove(clip, $event)"
                @click="$emit('selectClip', clip)"
                @dblclick.stop="$emit('openInspector', clip)"
              >
                <span class="truncate">{{ clip.source_asset_name || clipLabel(clip) }}</span>
                <span
                  v-if="clip.audio_role !== 'Source'"
                  class="audio-trim-handle audio-trim-handle-left"
                  title="Trim start"
                  @pointerdown.stop="startTrim(clip, 'left', $event)"
                />
                <AudioWaveform
                  :src="clip.source_file"
                  :source-in-frame="clip.source_in_frame"
                  :source-out-frame="clip.source_out_frame"
                  :fps="fps"
                />
                <span
                  v-if="clip.audio_role !== 'Source'"
                  class="audio-trim-handle audio-trim-handle-right"
                  title="Trim end"
                  @pointerdown.stop="startTrim(clip, 'right', $event)"
                />
                <span v-if="clip.audio_role !== 'Source'" class="audio-role-badge">{{ audioRoleLabel(clip.audio_role) }}</span>
              </button>
              <div v-else class="audio-timeline-empty-segment" :style="clipStyle(clip)">
                <span>{{ currentLang === 'vi' ? 'Không có audio nguồn' : 'No source audio' }}</span>
              </div>
            </template>
          </div>
        </div>

    </div>

    <button type="button" class="audio-add-track" @click="$emit('openAudioPicker')">
      + {{ currentLang === 'vi' ? 'Thêm track âm thanh' : 'Add audio track' }}
    </button>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import AudioWaveform from "./AudioWaveform.vue";

const props = defineProps({
  audioClips: { type: Array, default: () => [] },
  videoClips: { type: Array, default: () => [] },
  selectedClipName: { type: String, default: null },
  totalFrames: { type: Number, default: 0 },
  fps: { type: Number, default: 24 },
  pixelsPerFrame: { type: Number, default: 2 },
  timelineCanvasWidth: { type: Number, default: 700 },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["selectClip", "openInspector", "openAudioPicker", "move", "trim"]);

const moveDrag = ref(null);
const trimDrag = ref(null);

const audioTracks = computed(() => {
  const groups = new Map();
  const sourceClips = props.audioClips.filter((clip) => clip.audio_role === "Source");
  const sourceByVideo = new Map(sourceClips.map((clip) => [clip.linked_video_clip, clip]));
  const sourceSegments = props.videoClips.length
    ? props.videoClips.map((videoClip) => sourceByVideo.get(videoClip.name) || {
        name: `silent-${videoClip.name}`,
        audio_role: "Source",
        is_silent_source: true,
        shot_number: videoClip.shot_number,
        timeline_start_frame: videoClip.timeline_start_frame,
        duration_frames: videoClip.duration_frames,
      })
    : sourceClips;
  for (const clip of [...sourceSegments, ...props.audioClips.filter((clip) => clip.audio_role !== "Source")]) {
    const trackIndex = Math.max(0, Number(clip.track_index || 0));
    if (!groups.has(trackIndex)) groups.set(trackIndex, []);
    groups.get(trackIndex).push(clip);
  }
  const tracks = [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([trackIndex, clips]) => ({ trackIndex, clips }));
  if (!tracks.length) tracks.push({ trackIndex: 0, clips: [] });
  return tracks;
});

function clipStyle(clip) {
  return {
    left: `${Number(clip.timeline_start_frame || 0) * props.pixelsPerFrame}px`,
    width: `${Math.max(48, Number(clip.duration_frames || 0) * props.pixelsPerFrame)}px`,
  };
}

function clipLabel(clip) {
  if (clip?.shot_number) return props.currentLang === "vi" ? `Cảnh ${clip.shot_number}` : `Shot ${clip.shot_number}`;
  return `Clip ${clip?.clip_order || ""}`;
}

function audioRoleLabel(role) {
  if (role === "Voiceover") return props.currentLang === "vi" ? "LỜI" : "VOICE";
  if (role === "SFX") return props.currentLang === "vi" ? "HIỆU ỨNG" : "SFX";
  return props.currentLang === "vi" ? "NHẠC" : "MUSIC";
}

function startMove(clip, event) {
  if (clip.audio_role === "Source") return;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  moveDrag.value = {
    clip,
    startX: event.clientX,
    originalStart: Number(clip.timeline_start_frame || 0),
  };
  window.addEventListener("pointermove", handleMove);
  window.addEventListener("pointerup", finishMove);
}

function handleMove(event) {
  if (!moveDrag.value) return;
  const delta = Math.round((event.clientX - moveDrag.value.startX) / props.pixelsPerFrame);
  moveDrag.value.nextStart = Math.max(0, moveDrag.value.originalStart + delta);
}

function finishMove() {
  const drag = moveDrag.value;
  moveDrag.value = null;
  window.removeEventListener("pointermove", handleMove);
  window.removeEventListener("pointerup", finishMove);
  if (drag && drag.nextStart != null && drag.nextStart !== drag.originalStart) {
    emit("move", {
      clip: drag.clip,
      timelineStartFrame: drag.nextStart,
      trackIndex: drag.clip.track_index,
    });
  }
}

function startTrim(clip, edge, event) {
  event.currentTarget.setPointerCapture?.(event.pointerId);
  trimDrag.value = {
    clip,
    edge,
    startX: event.clientX,
    originalIn: Number(clip.source_in_frame || 0),
    originalOut: Number(clip.source_out_frame || 0),
    originalTimelineStart: Number(clip.timeline_start_frame || 0),
  };
  window.addEventListener("pointermove", handleTrim);
  window.addEventListener("pointerup", finishTrim);
}

function handleTrim(event) {
  const drag = trimDrag.value;
  if (!drag) return;
  const delta = Math.round((event.clientX - drag.startX) / props.pixelsPerFrame);
  const minimum = 1;
  if (drag.edge === "left") {
    const earliestIn = Math.max(0, drag.originalIn - drag.originalTimelineStart);
    drag.nextIn = Math.max(earliestIn, Math.min(drag.originalOut - minimum, drag.originalIn + delta));
    drag.nextOut = drag.originalOut;
  } else {
    drag.nextIn = drag.originalIn;
    drag.nextOut = Math.max(
      drag.originalIn + minimum,
      Math.min(Number(drag.clip.source_total_frames || drag.originalOut), drag.originalOut + delta),
    );
  }
}

function finishTrim() {
  const drag = trimDrag.value;
  trimDrag.value = null;
  window.removeEventListener("pointermove", handleTrim);
  window.removeEventListener("pointerup", finishTrim);
  if (!drag || drag.nextIn == null || drag.nextOut == null) return;
  if (drag.nextIn === drag.originalIn && drag.nextOut === drag.originalOut) return;
  emit("trim", {
    clip: drag.clip,
    sourceInFrame: drag.nextIn,
    sourceOutFrame: drag.nextOut,
  });
}

onBeforeUnmount(() => {
  window.removeEventListener("pointermove", handleMove);
  window.removeEventListener("pointerup", finishMove);
  window.removeEventListener("pointermove", handleTrim);
  window.removeEventListener("pointerup", finishTrim);
});
</script>
