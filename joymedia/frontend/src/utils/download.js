/** Download a private asset through the active browser session. */
export async function downloadFile(url) {
	if (!url) throw new Error("The exported video has no download URL.");

	// Asset files may be private Frappe files. A plain anchor lets the browser
	// navigate to the file instead of downloading it (and fails in Safari when
	// the response does not expose Content-Disposition). Fetch with the active
	// session, then download the authenticated blob.
	const response = await fetch(url, { credentials: "same-origin" });
	if (!response.ok) {
		throw new Error(`The exported video could not be downloaded (${response.status}).`);
	}
	const blob = await response.blob();
	const objectUrl = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = objectUrl;
	link.download = "edited-video.mp4";
	document.body.appendChild(link);
	link.click();
	link.remove();
	window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
