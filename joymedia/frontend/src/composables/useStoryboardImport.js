import { ref } from "vue";
import { call, upload as uploadFile } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";

/** Workbook upload, sheet selection and import form one editor action. */
export function useStoryboardImport({ projectName, currentLang, fetchWorkspace }) {
	// An uploaded sheet is read first; a workbook with several sheets asks which one to import.
	const sheetPicker = ref({ open: false, file: null, demos: [], choice: "" });

	async function importStoryboardWorkbook(file) {
		try {
			const uploaded = await uploadFile(file, { private: true });
			if (!uploaded?.name) throw new Error("Storyboard upload failed.");
			const { demos } = await call("joymedia.services.intake.project.preview_workbook", {
				workbook_file: uploaded.name,
			});
			const usable = demos.filter((demo) => demo.can_create);
			if (!usable.length) {
				const missing = demos[0]?.missing_required?.join(", ");
				throw new Error(
					currentLang.value === "vi"
						? `Bảng còn thiếu các mục bắt buộc: ${missing}.`
						: `The sheet is missing must-have fields: ${missing}.`
				);
			}
			if (usable.length === 1) return await importSheet(uploaded.name, usable[0].name);
			sheetPicker.value = {
				open: true,
				file: uploaded.name,
				demos: usable,
				choice: usable[0].name,
			};
		} catch (err) {
			notify({
				title: "Storyboard",
				text: errorMessage(err, "Unable to import storyboard."),
				type: "error",
			});
		}
	}

	async function importSheet(workbookFile, demoName) {
		try {
			const result = await call("joymedia.api.storyboard.import_storyboard_workbook", {
				project_name: projectName.value,
				workbook_file: workbookFile,
				demo_name: demoName,
			});
			sheetPicker.value.open = false;
			await fetchWorkspace();
			notify({
				title: currentLang.value === "vi" ? "Đã nhập kịch bản" : "Storyboard imported",
				text: `${result.shot_count} scene(s) imported. Review and approve before generation.`,
				type: "success",
			});
		} catch (err) {
			notify({
				title: "Storyboard",
				text: errorMessage(err, "Unable to import storyboard."),
				type: "error",
			});
		}
	}

	return { sheetPicker, importStoryboardWorkbook, importSheet };
}
