# Reference view preparation

`reference_image_crop.json` is an optional Generation Workflow document using
ComfyUI's built-in `LoadImage → ImageCropV2 → SaveImage` path and JoyMedia's
existing generic adapter. It needs no additional model or custom node.
[Upstream implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_images.py).

An operator can register this document with Frappe's existing document API, then
call the existing workflow resolver with `first_frame` and `crop_region` inputs.
The rectangle contains integer pixel `x`, `y`, `width` and `height` within the
original image. Author the rectangle explicitly; do not infer anatomy from an
asset category. Keep the resulting view as a derived Asset Version with its
original source, rectangle, workflow hash, ComfyUI prompt ID and pixel comparison.
Select that named view in the workbook's References/cast columns.

A wide identity photo can make a reference-conditioned model reproduce its full
body framing despite a close-up instruction. A separately prepared portrait view
provides the appropriate visible anatomy while retaining the source identity.
Keep the full view for wide shots. This prepares references; it does not replace
the workbook's scene planning, video workflow or review gates.
