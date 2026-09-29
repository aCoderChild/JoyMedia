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

  async function exportTimeline() {
    if (busy.value) return null;
    busy.value = true;
    try {
      const result = await call(
        "joymedia.services.timeline_editor.compose_project_timeline",
        {
          project_name: project(),
        }
      );

      await loadTimeline(false);
      return result;
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
    } finally {
      busy.value = false;
    }
  }

  return {
    timeline,
    clips,
    fps,
    busy,
    selectedClip,
    selectedClipName,
    playheadFrame,

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
  };
}
