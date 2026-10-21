import { ref, unref } from "vue";
import { call, upload as uploadFile } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { tr } from "../stores/i18n";

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
        "joymedia.api.assets.get_project_reference_candidates",
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
    uploadError.value = "";
    showMediaPicker.value = true;
    await fetchCandidates();
  }

  async function addReference({ asset, role }) {
    if (!asset?.name || savingReference.value) return;
    savingReference.value = true;
    try {
      await call("joymedia.api.assets.select_project_reference", {
        media_project: project(),
        asset_name: asset.name,
        reference_role: role || "General",
      });
      showMediaPicker.value = false;
      if (onRefresh) await onRefresh();
      notify({ title: "Reference added", text: tr(`Added ${asset.asset_name} as ${role}.`, `Đã thêm ${asset.asset_name} làm ${role}.`), type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to add reference."), type: "error" });
    } finally {
      savingReference.value = false;
    }
  }

  async function updateReferenceRole(asset, newRole) {
    if (!asset?.name) return;
    try {
      await call("joymedia.api.assets.select_project_reference", {
        media_project: project(),
        asset_name: asset.name || asset.media_asset,
        reference_role: newRole,
      });
      if (onRefresh) await onRefresh();
      notify({ title: "Role updated", text: tr(`Reference role updated to ${newRole}.`, `Đã đổi vai trò thành ${newRole}.`), type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to update role."), type: "error" });
    }
  }

  async function updateMotionReferenceUse(asset, use) {
    if (!asset?.asset_version) return;
    try {
      await call("joymedia.api.assets.set_motion_reference_use", { media_project: project(), asset_version: asset.asset_version, use });
      if (onRefresh) await onRefresh();
    } catch (err) { notify({ title: "Error", text: errorMessage(err, "Could not update reference use."), type: "error" }); }
  }

  async function analyzeCameraReference() {
    try {
      await call("joymedia.api.assets.analyze_project_camera_references", { project_name: project() });
      notify({ title: tr("Camera reference", "Máy quay tham chiếu"), text: tr("Analysis queued. Results are used when planning scenes.", "Đã xếp hàng phân tích. Kết quả sẽ được dùng khi lập kế hoạch cảnh."), type: "success" });
      if (onRefresh) await onRefresh();
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Camera reference analysis failed."), type: "error" });
    }
  }

  async function updateReferenceSize(asset, size) {
    if (!asset?.asset_version) return;
    try {
      await call("joymedia.api.assets.set_reference_size", {
        media_project: project(),
        asset_version: asset.asset_version,
        relative_size: size,
      });
      if (onRefresh) await onRefresh();
      notify({ title: "Size updated", text: tr(`Relative size set to ${size}.`, `Đã đặt kích thước tương đối ${size}.`), type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to update size."), type: "error" });
    }
  }

  async function updateReferenceIdentity(asset, identityKey) {
    if (!asset?.asset_version || !identityKey?.trim()) return;
    try {
      await call("joymedia.api.assets.set_reference_identity", {
        media_project: project(),
        asset_version: asset.asset_version,
        identity_key: identityKey.trim(),
      });
      if (onRefresh) await onRefresh();
      notify({ title: "Identity updated", text: tr("Approved views now share one identity.", "Các góc nhìn đã được gộp vào một nhận diện."), type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to update identity."), type: "error" });
    }
  }

  async function removeReference(asset) {
    const version = asset?.asset_version;
    if (!version) return;
    try {
      await call("joymedia.api.assets.remove_project_reference", {
        media_project: project(),
        asset_version: version,
      });
      if (onRefresh) await onRefresh();
      notify({ title: "Removed", text: "Reference removed from project.", type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to remove reference."), type: "error" });
    }
  }

  async function archiveMediaAsset(asset) {
    if (!asset?.name) return;
    try {
      const result = await call("joymedia.services.intake.assets.archive_media_asset", {
        media_asset: asset.name,
      });
      if (result?.in_use) {
        const confirmed = window.confirm(
          `${asset.asset_name} is used by ${result.projects?.length || 0} project(s). Archive it and remove it from those projects?`
        );
        if (!confirmed) return;
        await call("joymedia.services.intake.assets.archive_media_asset", {
          media_asset: asset.name,
          detach_projects: 1,
        });
      }
      await fetchCandidates();
      if (onRefresh) await onRefresh();
      notify({ title: "Asset archived", text: tr(`${asset.asset_name} was removed from the library.`, `Đã xoá ${asset.asset_name} khỏi thư viện.`), type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to archive asset."), type: "error" });
    }
  }

  async function setShotKeyframe({ shot, frameRole, asset }) {
    if (!shot?.name || !asset?.asset_version) return;
    try {
      await call("joymedia.api.storyboard.set_project_shot_keyframe", {
        project_name: project(),
        shot_name: shot.name,
        frame_role: frameRole === "start" || frameRole === "first_frame" ? "first_frame" : "last_frame",
        asset_version: asset.asset_version,
      });
      showMediaPicker.value = false;
      if (onRefresh) await onRefresh();
      notify({ title: "Keyframe set", text: tr(`Assigned keyframe reference to Scene ${shot.shot_number}.`, `Đã đặt khung hình chính cho cảnh ${shot.shot_number}.`), type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to set keyframe."), type: "error" });
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
        if (!uploaded?.file_url || !uploaded?.name) throw new Error("Upload failed");
		const isAudio = file.type.startsWith("audio");
		const category = isAudio ? "Audio" : "Reference";
        const created = await call("joymedia.services.intake.assets.create_media_asset", {
          asset_name: file.name.replace(/\.[^/.]+$/, ""),
          asset_category: category,
          file_url: uploaded.file_url,
          file_name: uploaded.name,
        });
        newestAssetVersion = created?.asset_version || newestAssetVersion;
      }
      lastUploadedAssetVersion.value = newestAssetVersion;
      await fetchCandidates({ throwOnError: true });
      notify({ title: "Uploaded", text: tr(`${files.length} file(s) added to the media library.`, `Đã thêm ${files.length} tệp vào thư viện.`), type: "success" });
    } catch (err) {
      uploadError.value = errorMessage(err, "Failed to upload file.");
      notify({ title: "Upload error", text: uploadError.value, type: "error" });
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
    analyzeCameraReference,
    updateMotionReferenceUse,
    updateReferenceIdentity,
    updateReferenceSize,
    removeReference,
    archiveMediaAsset,
    setShotKeyframe,
    uploadFilesToLibrary,
  };
}
