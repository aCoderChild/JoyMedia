import { ref, unref } from "vue";
import { call, toast, upload as uploadFile } from "frappe-ui";

export function useProjectReferences(projectName, onRefresh) {
  const showMediaPicker = ref(false);
  const mediaCandidates = ref([]);
  const candidatesLoading = ref(false);
  const savingReference = ref(false);
  const uploadingMedia = ref(false);
  const uploadError = ref("");
  const lastUploadedAssetVersion = ref("");

  function project() {
    return unref(projectName);
  }

  async function fetchCandidates({ throwOnError = false } = {}) {
    candidatesLoading.value = true;
    try {
      const candidates = await call(
        "joymedia.joymedia.doctype.media_project.media_project.get_project_reference_candidates",
        { media_project: project() }
      );
      mediaCandidates.value = candidates || [];
      return mediaCandidates.value;
    } catch (err) {
      mediaCandidates.value = [];
      if (throwOnError) throw err;
      return [];
    } finally {
      candidatesLoading.value = false;
    }
  }

  async function openPicker() {
    showMediaPicker.value = true;
    await fetchCandidates();
  }

  async function addReference({ asset, role }) {
    if (!asset?.name || savingReference.value) return;
    savingReference.value = true;
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.select_project_reference", {
        media_project: project(),
        asset_name: asset.name,
        reference_role: role || "Product",
      });
      showMediaPicker.value = false;
      if (onRefresh) await onRefresh();
      toast({ title: "Reference added", text: `Added ${asset.asset_name} as ${role}.`, type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to add reference.", type: "error" });
    } finally {
      savingReference.value = false;
    }
  }

  async function updateReferenceRole(asset, newRole) {
    if (!asset?.name) return;
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.select_project_reference", {
        media_project: project(),
        asset_name: asset.name || asset.media_asset,
        reference_role: newRole,
      });
      if (onRefresh) await onRefresh();
      toast({ title: "Role updated", text: `Reference role updated to ${newRole}.`, type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to update role.", type: "error" });
    }
  }

  async function removeReference(asset) {
    const version = asset?.asset_version;
    if (!version) return;
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.remove_project_reference", {
        media_project: project(),
        asset_version: version,
      });
      if (onRefresh) await onRefresh();
      toast({ title: "Removed", text: "Reference removed from project.", type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to remove reference.", type: "error" });
    }
  }

  async function setShotKeyframe({ shot, frameRole, asset }) {
    if (!shot?.name || !asset?.asset_version) return;
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.set_project_shot_keyframe", {
        project_name: project(),
        shot_name: shot.name,
        frame_role: frameRole === "start" || frameRole === "first_frame" ? "first_frame" : "last_frame",
        asset_version: asset.asset_version,
      });
      showMediaPicker.value = false;
      if (onRefresh) await onRefresh();
      toast({ title: "Keyframe set", text: `Assigned keyframe reference to Shot ${shot.shot_number}.`, type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to set keyframe.", type: "error" });
    }
  }

  async function uploadFilesToLibrary(files) {
    if (!files?.length || uploadingMedia.value) return;
    uploadingMedia.value = true;
    uploadError.value = "";
    try {
      let newestAssetVersion = "";
      for (const file of files) {
        const uploaded = await uploadFile(file, { private: true });
        if (!uploaded?.file_url) throw new Error("Upload failed");
        const isAudio = file.type.startsWith("audio");
        const category = isAudio ? "Audio" : "Reference";
        const created = await call("joymedia.services.media_asset_service.create_media_asset", {
          asset_name: file.name.replace(/\.[^/.]+$/, ""),
          asset_category: category,
          file_url: uploaded.file_url,
        });
        newestAssetVersion = created?.asset_version || newestAssetVersion;
      }
      lastUploadedAssetVersion.value = newestAssetVersion;
      await fetchCandidates({ throwOnError: true });
      toast({ title: "Uploaded", text: `${files.length} file(s) added to the media library.`, type: "success" });
    } catch (err) {
      uploadError.value = err?.message || "Failed to upload file.";
      toast({ title: "Upload error", text: uploadError.value, type: "error" });
    } finally {
      uploadingMedia.value = false;
    }
  }

  return {
    showMediaPicker,
    mediaCandidates,
    candidatesLoading,
    savingReference,
    uploadingMedia,
    uploadError,
    lastUploadedAssetVersion,

    fetchCandidates,
    openPicker,
    addReference,
    updateReferenceRole,
    removeReference,
    setShotKeyframe,
    uploadFilesToLibrary,
  };
}
