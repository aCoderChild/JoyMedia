import { computed, watch, onUnmounted } from "vue";
import { call } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";

/** Finishing commands and their polling lifecycle, separate from scene playback. */
export function useProjectFinishing({
	projectName,
	postProduction,
	videoSettings,
	currentLang,
	fetchWorkspace,
	loadTimeline,
}) {
	const isFinishing = computed(() =>
		["Queued", "Running"].includes(postProduction.value.status)
	);
	let finishPollTimer = null;
	let disposed = false;

	async function finishFilm() {
		const withMusic =
			(videoSettings.value?.soundtrack_mode || "Sound effects only") === "Full soundtrack";
		const confirmed = window.confirm(
			currentLang.value === "vi"
				? `Dựng lại phim${
						withMusic ? " với nhạc nền" : " từ các cảnh đã duyệt"
				  }? Các chỉnh sửa thủ công trên timeline sẽ bị thay thế.`
				: `Rebuild the film${
						withMusic ? " with the soundtrack" : " from the approved scenes"
				  }? Manual timeline edits will be replaced.`
		);
		if (!confirmed) return;
		try {
			await call("joymedia.services.editing.post_production.queue_post_production", {
				project_name: projectName.value,
			});
			await fetchWorkspace();
		} catch (err) {
			notify({
				title:
					currentLang.value === "vi"
						? "Không thể hoàn thiện phim"
						: "Could not finish the film",
				text: errorMessage(err, ""),
				type: "error",
			});
		}
	}

	async function replaceMusic() {
		try {
			await call("joymedia.services.editing.post_production.queue_music_bed", {
				project_name: projectName.value,
			});
			await fetchWorkspace();
		} catch (err) {
			notify({
				title:
					currentLang.value === "vi"
						? "Không thể tạo nhạc nền"
						: "Could not replace music",
				text: errorMessage(err, ""),
				type: "error",
			});
		}
	}

	async function cancelFinishing() {
		try {
			await call("joymedia.services.editing.post_production.cancel_post_production", {
				project_name: projectName.value,
			});
			if (finishPollTimer) clearTimeout(finishPollTimer);
			finishPollTimer = null;
			await fetchWorkspace();
			notify({
				title:
					currentLang.value === "vi" ? "Đã dừng hoàn thiện phim" : "Finishing stopped",
				type: "success",
			});
		} catch (err) {
			notify({
				title:
					currentLang.value === "vi"
						? "Không thể dừng hoàn thiện phim"
						: "Could not stop finishing",
				text: errorMessage(err, ""),
				type: "error",
			});
		}
	}

	async function pollFinishing() {
		if (disposed) return;
		finishPollTimer = null;
		const previous = postProduction.value.status;
		try {
			// Reports a finishing job that died (worker restart) as Failed instead of Running forever.
			await call("joymedia.services.editing.post_production.get_post_production_status", {
				project_name: projectName.value,
			});
		} catch {
			// the next poll retries; the workspace fetch below shows the stored state
		}
		await fetchWorkspace();
		if (disposed) return;
		const { status, error } = postProduction.value;
		if (["Queued", "Running"].includes(status)) {
			finishPollTimer = setTimeout(pollFinishing, 10000);
			return;
		}
		if (!["Queued", "Running"].includes(previous)) return;
		await loadTimeline(true);
		if (status === "Completed") {
			notify({
				title: currentLang.value === "vi" ? "Đã hoàn thiện phim" : "Film finished",
				text:
					currentLang.value === "vi"
						? "Phim đã được dựng lại. Bấm Xuất & tải xuống."
						: "The film is rebuilt. Click Export & download.",
				type: "success",
			});
		} else if (status === "Failed") {
			notify({
				title:
					currentLang.value === "vi" ? "Hoàn thiện phim thất bại" : "Finishing failed",
				text: error,
				type: "error",
			});
		}
	}

	watch(
		isFinishing,
		(finishing) => {
			if (!disposed && finishing && !finishPollTimer)
				finishPollTimer = setTimeout(pollFinishing, 10000);
		},
		{ immediate: true }
	);

	onUnmounted(() => {
		disposed = true;
		if (finishPollTimer) clearTimeout(finishPollTimer);
	});

	return { isFinishing, finishFilm, replaceMusic, cancelFinishing };
}
