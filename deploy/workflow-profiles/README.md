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

`minimax_h3_i2v_base_20.json` retains the native first/last-frame graph and
installed checkpoint, switches turbo off, and selects the existing 20-step base
schedule. No additional model or inference node is required. This is an optional
comparison profile, not a global promotion or a guarantee of physical correctness.
The [official guide](https://github.com/Comfy-Org/docs/blob/main/tutorials/video/minimax/minimax-h3.mdx)
documents the base/turbo schedules. Preserve both the seed and input references
when comparing them.

The operator's per-project pipeline pin takes precedence over editor settings.
After changing that pin, allow the framework's site-config cache to expire or
refresh the relevant service. Inspect the frozen Run's workflow and the submitted
ComfyUI graph: the turbo switch must be false and base steps must be 20. An editor
selection alone is not execution evidence.

`minimax_h3_reference_only_base_20.json` reuses the deployed native Ref2VA
checkpoint, 20-step base scheduler and role-separated original image inputs.
It needs no FLUX keyframes or additional weights. It declares reference-only
execution through the existing generic adapter. Delivery uses the requested
aspect ratio with a short-edge quality target, rather than a fixed portrait
canvas. This is a comparison profile; original-reference conditioning does not
qualify identity, support or action correctness. Native visual admission and
release evidence still apply.
