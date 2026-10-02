import { computed, ref, unref } from "vue";
import { call, toast } from "frappe-ui";

export function useProjectWorkspace(projectName) {
  const workspace = ref(null);
  const loading = ref(false);
  const error = ref(null);
  const studioMode = ref("scene"); // "scene" | "edit"
  const selectedTarget = ref("scene"); // "scene" | "asset" | "keyframe-start" | "keyframe-end"
  const selectedAsset = ref(null);
  const selectedShotIndex = ref(0);
  const inspectorOpen = ref(false);
  const showSettings = ref(false);
  const videoStyles = ref([]);
  const savingSettings = ref(false);

  function project() {
    return unref(projectName);
  }

  async function fetchWorkspace() {
    if (!project()) return null;
    loading.value = true;
    error.value = null;
    try {
      const data = await call("joymedia.joymedia.doctype.media_project.media_project.get_project_workspace", {
        name: project(),
      });
      workspace.value = data;
      return data;
    } catch (err) {
      error.value = err?.message || "Failed to load project workspace";
      return null;
    } finally {
      loading.value = false;
    }
  }

  function applyWorkspaceSnapshot(data) {
    workspace.value = data || null;
    return workspace.value;
  }

  async function fetchVideoStyles() {
    try {
      const styles = await call("joymedia.joymedia.doctype.media_project.media_project.get_video_styles");
      videoStyles.value = styles || [];
    } catch (_) {
      videoStyles.value = [];
    }
  }

  async function updateProjectName(newName) {
    if (!newName?.trim()) return;
    try {
      const res = await call("joymedia.joymedia.doctype.media_project.media_project.update_project_name", {
        media_project: project(),
        project_name: newName.trim(),
      });
      if (workspace.value?.project) {
        workspace.value.project.project_name = res.project_name;
      }
      toast({ title: "Updated", text: "Project name updated.", type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to rename project.", type: "error" });
    }
  }

  async function saveVideoSettings(settingsPayload) {
    savingSettings.value = true;
    try {
      const totalDurationSeconds =
        settingsPayload.total_duration_seconds ?? settingsPayload.duration;
      await call("joymedia.joymedia.doctype.media_project.media_project.save_project_video_settings", {
        project_name: project(),
        total_duration_seconds: totalDurationSeconds,
        delivery_preset: settingsPayload.delivery_preset,
        video_style: settingsPayload.video_style || null,
        generation_mode: settingsPayload.generation_mode || "Multi-shot",
        global_instructions: settingsPayload.global_instructions || "",
      });
      await fetchWorkspace();
      showSettings.value = false;
      toast({ title: "Saved", text: "Video settings saved.", type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to save settings.", type: "error" });
    } finally {
      savingSettings.value = false;
    }
  }

  const projectTitle = computed(() => workspace.value?.project?.project_name || project());
  const projectStatus = computed(() => workspace.value?.project?.status || "Draft");
  const projectAssets = computed(() => workspace.value?.assets || []);
  const storyboard = computed(() => workspace.value?.storyboard || null);
  const storyboardShots = computed(() => {
    if (Array.isArray(storyboard.value)) {
      return storyboard.value;
    }
    return storyboard.value?.shots || [];
  });
  const currentOutputAssetVersion = computed(() => workspace.value?.project?.current_output_asset_version || "");
  const finalVideo = computed(() => workspace.value?.final_video || null);

  const videoSettings = computed(() => {
    return workspace.value?.video_settings || {
      delivery_preset: "Landscape",
      duration: 15,
      total_duration_seconds: 15,
      generation_mode: "Multi-shot",
      global_instructions: "",
    };
  });

  const isOutdated = computed(() => Boolean(workspace.value?.production?.is_outdated));

  return {
    workspace,
    loading,
    error,
    studioMode,
    selectedTarget,
    selectedAsset,
    selectedShotIndex,
    inspectorOpen,
    showSettings,
    videoStyles,
    savingSettings,

    projectTitle,
    projectStatus,
    projectAssets,
    storyboard,
    storyboardShots,
    currentOutputAssetVersion,
    finalVideo,
    isOutdated,
    videoSettings,

    fetchWorkspace,
    applyWorkspaceSnapshot,
    fetchVideoStyles,
    updateProjectName,
    saveVideoSettings,
  };
}
