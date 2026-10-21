# Original product references during video generation

The opt-in `reference_conditioned_product_video` pipeline reuses the currently
promoted image stage and native MiniMax H3 Ref2VA for video. Registration is
idempotent and does not promote it. Existing jobs retain their frozen workflows.

`joymedia.patches.register_ref2va_pipeline.execute()` registers the workflow and
pipeline. On 19 October 2026 these were `WF-02668` and `PIPE-00039`. The current
production pipeline remains unchanged until a live qualification passes.

The first input is the approved scene opening. It conditions Ref2VA as Picture 1
and feeds `MiniMaxH3AddGuide` at frame zero. A distinct original product image is
Picture 2, bound by the semantic `product` role to both the text and video VAE
reference path. It preserves package appearance guidance without treating the
product photograph as the scene or a second product. Product-free shots omit
Picture 2 and its prompt instruction. Only a supplied `last_frame` adds an
endpoint guide. No endpoint is inferred from the product reference.

The current anchored workflow revision accepts an optional third, separate
`character` image. It supplies the original mascot identity independently of
the opening pose and product photo. A live Shera task verified that the image
bytes submitted to ComfyUI matched the original mascot Asset Version SHA-256.

Later stages and continuation segments retain the original Asset Version when
their workflow declares its role; upstream Primary Image / Last Frame controls
stay separate. Multiple different products exceeding this graph's single slot
fail explicitly. The implementation does not choose a model from a product name,
reference count or category. The optional prompt gating is adapter configuration.

## Upstream sources

- Native R2V template from https://github.com/Comfy-Org/workflow_templates,
  revision `59a3b48bf369c5a15f29a1308bae3e279fa15505`,
  `templates/video_minimax_h3_r2v.json`. Its MIT license is retained in
  `docs/licenses/Comfy-Org-workflow-templates-MIT.txt`.
- Native nodes on the GPU host: ComfyUI
  `d91ed5f5b7fa60fa18464c2ad7c80254da2f0f29`. Both
  `MiniMaxH3ReferenceToVideo` and `MiniMaxH3AddGuide` are installed.
- Official native-node guide:
  https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native
- Ref2VA INT8 model: `Comfy-Org/MiniMax-H3` revision
  `e5eb578a89295337b8ff433a035929ce0279e0b6`,
  `diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors`.
  Size: 20,970,379,616 bytes; SHA-256:
  `9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779`.

The existing sampler and AV decode graph are reused. Ref2VA uses its own weights;
FL2VA weights and its turbo LoRA must not be substituted. The candidate uses the
base 20-step beta schedule, without turbo. The first reference and product are
separate images, with `ref_image_size=match`, avoiding a stitched contact sheet.

## Qualification status

Local contract tests cover product/reference separation, frame-zero anchoring,
optional product/endpoint handling, continuation-safe asset forwarding, slot
limits and idempotent registration without promotion. Existing generic adapter
and generation orchestrator regressions also run separately.

The initial storage failure was resolved and the pinned checkpoint is now used
by live ComfyUI jobs. Shera tests exposed the limit of soft reference guidance:
even with original product art and first/last guides, Ref2VA can invent a hand,
extract another sheet, change mascot proportions, or rewrite package text. Such
takes remain rejected. Reference images and guide latents do not guarantee exact
pixels or physically correct action.

For a stationary product detail requiring exact print, the generic
`compose_source_motion_take` path applies the authored camera behavior to an
assigned original image with FFmpeg `zoompan`. It creates an unselected take
with source/output hashes and the planned frame count. Keep Ref2VA for actual
mascot movement; inspect topology, contact and object continuity before selecting
each action take. A source-motion take cannot replace an authored interaction.
