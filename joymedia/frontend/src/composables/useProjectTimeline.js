import { computed, ref, unref } from "vue";
import { call, toast } from "frappe-ui";

export function useProjectTimeline(projectName) {
  const timeline = ref(null);
  const busy = ref(false);
  const selectedClipName = ref(null);
  const playheadFrame = ref(0);

  const clips = computed(() => timeline.value?.clips || []);
  const fps = computed(() => Number(timeline.value?.fps || 0));

  const selectedClip = computed(() =>
    clips.value.find((clip) => clip.name === selectedClipName.value) || clips.value[0] || null
  );

  function project() {
    return unref(projectName);
  }

  function applyTimeline(next, preferredClip = null) {
    timeline.value = next;

    const candidate =
      next?.clips?.find((clip) => clip.name === preferredClip) ||
      next?.clips?.find((clip) => clip.name === selectedClipName.value) ||
      next?.clips?.[0] ||
      null;

    selectedClipName.value = candidate?.name || null;

    if (candidate) {
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

      applyTimeline(result, preferredClip);
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

  const exportStatus = computed(() => timeline.value?.export_status || "Idle");
  const exportError = computed(() => timeline.value?.export_error || null);
  const isExporting = computed(() => ["Queued", "Running"].includes(exportStatus.value));
  const isOutdated = computed(() => Boolean(timeline.value?.is_outdated));

  return {
    timeline,
    clips,
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
    exportTimeline,
    stopExportPolling,
  };
}
