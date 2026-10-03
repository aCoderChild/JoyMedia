import { computed, ref, unref } from "vue";
import { call, toast } from "frappe-ui";

export function useProjectTimeline(projectName) {
  const timeline = ref(null);
  const busy = ref(false);
  const selectedClipName = ref(null);
  const playheadFrame = ref(0);

  const clips = computed(() => timeline.value?.clips || []);
  const videoClips = computed(() => clips.value.filter((clip) => (clip.track_type || "Video") === "Video"));
  const audioClips = computed(() => clips.value.filter((clip) => clip.track_type === "Audio"));
  const fps = computed(() => Number(timeline.value?.fps || 0));

  const selectedClip = computed(() =>
    clips.value.find((clip) => clip.name === selectedClipName.value) || videoClips.value[0] || audioClips.value[0] || null
  );

  function project() {
    return unref(projectName);
  }

  function applyTimeline(next, preferredClip = null, { preserveSelection = true, preservePlayhead = true } = {}) {
    const previousTimeline = timeline.value;
    const previousSelection = selectedClipName.value;
    const previousPlayhead = playheadFrame.value;
    timeline.value = next;

    const candidate =
      next?.clips?.find((clip) => clip.name === preferredClip) ||
      (preserveSelection && next?.clips?.find((clip) => clip.name === previousSelection)) ||
      next?.clips?.[0] ||
      null;

    selectedClipName.value = candidate?.name || null;

    if (preservePlayhead && previousTimeline && next) {
      playheadFrame.value = Math.min(previousPlayhead, Number(next.total_frames || previousPlayhead));
    } else if (candidate) {
      playheadFrame.value = candidate.timeline_start_frame;
    } else {
      playheadFrame.value = 0;
    }
  }

  async function loadTimeline(createIfPossible = false) {
    try {
      const result = await call(
        "joymedia.services.timeline_editor.get_project_timeline",
        {
          project_name: project(),
          create_if_possible: createIfPossible,
        }
      );

      applyTimeline(result);
      if (result && ["Queued", "Running"].includes(result.export_status)) {
        startExportPolling();
      }
      return result;
    } catch (_) {
      timeline.value = null;
      return null;
    }
  }

  async function mutate(method, payload, preferredClip = null) {
    if (busy.value) return null;

    busy.value = true;

    try {
      const result = await call(
        `joymedia.services.timeline_editor.${method}`,
        {
          project_name: project(),
          ...payload,
        }
      );

      applyTimeline(result, preferredClip, { preserveSelection: true, preservePlayhead: true });
      return result;
    } catch (error) {
      toast({
        title: "Timeline edit failed",
        text:
          error?.messages?.join(" ") ||
          error?.message ||
          "Please try again.",
        type: "error",
      });

      return null;
    } finally {
      busy.value = false;
    }
  }

  function trimClip(clip, sourceIn, sourceOut) {
    return mutate(
      "trim_timeline_clip",
      {
        clip_name: clip.name,
        source_in_frame: sourceIn,
        source_out_frame: sourceOut,
      },
      clip.name
    );
  }

  function reorderClip(clip, targetOrder) {
    return mutate(
      "reorder_timeline_clip",
      {
        clip_name: clip.name,
        target_order: targetOrder,
      },
      clip.name
    );
  }

  function splitClip(clip, frame) {
    return mutate("split_timeline_clip", {
      clip_name: clip.name,
      source_split_frame: frame,
    });
  }

  function duplicateClip(clip) {
    return mutate("duplicate_timeline_clip", {
      clip_name: clip.name,
    });
  }

  function deleteClip(clip) {
    return mutate("delete_timeline_clip", {
      clip_name: clip.name,
    });
  }

  function setTransition(clip, transition, frames = 0) {
    return mutate(
      "set_timeline_transition",
      {
        clip_name: clip.name,
        transition,
        transition_frames: frames,
      },
      clip.name
    );
  }

  function resetTimeline() {
    return mutate("reset_project_timeline", {});
  }

  function resetClip(clip) {
    return mutate(
      "reset_timeline_clip",
      {
        clip_name: clip.name,
      },
      clip.name
    );
  }

  function updateSourceForShot(shotName) {
    return mutate(
      "update_timeline_source_for_shot",
      { shot_name: shotName },
      selectedClipName.value
    );
  }

  let exportPollTimer = null;

  function stopExportPolling() {
    if (exportPollTimer) {
      clearTimeout(exportPollTimer);
      exportPollTimer = null;
    }
  }

  function startExportPolling(onSuccess = null, onError = null) {
    stopExportPolling();
    async function check() {
      try {
        const res = await call(
          "joymedia.services.timeline_editor.get_project_timeline_export_status",
          { project_name: project() }
        );
        if (timeline.value) {
          timeline.value.export_status = res.export_status;
          timeline.value.export_error = res.export_error;
        }
        if (res.export_status === "Completed") {
          stopExportPolling();
          await loadTimeline(false);
          if (onSuccess) onSuccess(res);
        } else if (res.export_status === "Failed") {
          stopExportPolling();
          toast({
            title: "Timeline export failed",
            text: res.export_error || "Export failed.",
            type: "error",
          });
          if (onError) onError(new Error(res.export_error || "Export failed"));
        } else {
          exportPollTimer = setTimeout(check, 2000);
        }
      } catch (err) {
        stopExportPolling();
        if (onError) onError(err);
      }
    }
    check();
  }

  async function exportTimeline() {
    if (isExporting.value) return null;
    try {
      const queueRes = await call(
        "joymedia.services.timeline_editor.queue_project_timeline_export",
        {
          project_name: project(),
        }
      );
      if (timeline.value) {
        timeline.value.export_status = queueRes.export_status || "Queued";
      }
      return new Promise((resolve, reject) => {
        startExportPolling(resolve, reject);
      });
    } catch (error) {
      toast({
        title: "Timeline export failed",
        text:
          error?.messages?.join(" ") ||
          error?.message ||
          "Please try again.",
        type: "error",
      });
      return null;
    }
  }

  function updateAudioClip(clip, settings) {
    return mutate(
      "update_timeline_clip_audio",
      {
        clip_name: clip.name,
        ...settings,
      },
      clip.name
    );
  }

  function fitAudioClipToVideo(clip) {
    return mutate(
      "fit_audio_clip_to_video",
      { clip_name: clip.name },
      clip.name
    );
  }

  function fitAudioClipToFullVideo(clip) {
    return mutate(
      "fit_audio_clip_to_full_video",
      { clip_name: clip.name },
      clip.name
    );
  }

  function moveClip(clip, timelineStartFrame, trackIndex = null) {
    return mutate(
      "move_timeline_clip",
      {
        clip_name: clip.name,
        timeline_start_frame: timelineStartFrame,
        track_index: trackIndex,
      },
      clip.name,
    );
  }

  function addAudioClip(assetVersionName, timelineStartFrame = 0, audioRole = "BGM") {
    return mutate(
      "add_timeline_audio_clip",
      {
        asset_version_name: assetVersionName,
        timeline_start_frame: timelineStartFrame,
        audio_role: audioRole,
      }
    );
  }

  const exportStatus = computed(() => timeline.value?.export_status || "Idle");
  const exportError = computed(() => timeline.value?.export_error || null);
  const isExporting = computed(() => ["Queued", "Running"].includes(exportStatus.value));
  const isOutdated = computed(() => Boolean(timeline.value?.is_outdated));

  return {
    timeline,
    clips,
    videoClips,
    audioClips,
    fps,
    busy,
    selectedClip,
    selectedClipName,
    playheadFrame,
    exportStatus,
    exportError,
    isExporting,
    isOutdated,

    applyTimeline,
    loadTimeline,
    trimClip,
    reorderClip,
    splitClip,
    duplicateClip,
    deleteClip,
    setTransition,
    resetTimeline,
    resetClip,
    updateSourceForShot,
    updateAudioClip,
    fitAudioClipToVideo,
    fitAudioClipToFullVideo,
    moveClip,
    addAudioClip,
    exportTimeline,
    stopExportPolling,
  };
}
