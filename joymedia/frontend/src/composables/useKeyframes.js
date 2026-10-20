import { computed, onUnmounted, ref } from "vue";
import { call, createResource } from "frappe-ui";
import { tr } from "../stores/i18n";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useProjectRealtime } from "./useProjectRealtime";

/**
 * Each scene's first frame (keyframe): prepared from the scene references, approved before its video is made.
 * Frappe pushes a change when a frame finishes or is approved, so the rows reload instead of polling.
 */
export function useKeyframes(projectName) {
  const resource = createResource({
    url: "joymedia.services.keyframes.stage.get_project_keyframes",
    params: { project_name: projectName },
    auto: true,
  });
  const rows = computed(() => resource.data || []);
  const byShot = computed(() => Object.fromEntries(rows.value.map((row) => [row.shot, row])));
  const needed = computed(() => rows.value.filter((row) => row.needs_keyframe));
  const approvedCount = computed(() => needed.value.filter((row) => row.status === "Approved" && !row.stale).length);
  const allApproved = computed(() => rows.value.length > 0 && approvedCount.value === needed.value.length);

  let reloadTimer = null;
  onUnmounted(() => clearTimeout(reloadTimer));
  useProjectRealtime(projectName, {
    joymedia_project_updated: () => {
      clearTimeout(reloadTimer);
      reloadTimer = setTimeout(() => resource.reload(), 400);
    },
  });

  const drawingAll = ref(false);
  const drawingShot = ref("");
  async function draw(shots) {
    drawingAll.value = !shots;
    drawingShot.value = shots?.[0] || "";
    try {
      const result = await call("joymedia.services.keyframes.stage.generate_keyframes", { project_name: projectName, shot_names: shots || null });
      notify({
        title: tr("Frames", "Khung hình"),
        text: result?.status === "Drawing places"
          ? tr("Each place is drawn once first, so every scene set there shows the same room. The frames follow.", "Mỗi bối cảnh được vẽ một lần trước, để các cảnh cùng nơi có cùng một căn phòng. Sau đó sẽ vẽ khung hình.")
          : tr("Drawing started. Each frame appears on its scene when it is ready.", "Đã bắt đầu vẽ. Khung hình sẽ hiện trên từng cảnh khi xong."),
        type: "success",
      });
    } catch (err) {
      notify({ title: tr("Frames", "Khung hình"), text: errorMessage(err, tr("Unable to draw the frames.", "Không thể vẽ khung hình.")), type: "error" });
    } finally {
      drawingAll.value = false;
      drawingShot.value = "";
    }
  }

  async function approve(shot, approved) {
    try {
      await call("joymedia.services.keyframes.stage.set_keyframe_approval", { project_name: projectName, shot_name: shot, approved });
      resource.reload();
    } catch (err) {
      notify({ title: tr("Frames", "Khung hình"), text: errorMessage(err, tr("Unable to change the approval.", "Không thể đổi trạng thái duyệt.")), type: "error" });
    }
  }

  return { rows, byShot, needed, approvedCount, allApproved, draw, approve, drawingAll, drawingShot, error: computed(() => resource.error), reload: () => resource.reload() };
}
