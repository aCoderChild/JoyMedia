# Choosing a render path per shot

The film owns one storyboard and one output geometry. Its **frozen shot snapshot**
selects the execution pipeline before any ComfyUI task is submitted. An operator
maps a promoted reference pipeline to a registered endpoint pipeline in site
configuration; customers supply references and describe actions, not model IDs.
The routes use versioned workflow bindings and the normal native task runner.

| Shot evidence | Render path | Reason |
| --- | --- | --- |
| Mascot/product manipulation, or no actual ending image | Pinned reference pipeline | The original product and character remain separate video references. |
| Exactly one explicit last-frame image, a moving camera, and no manipulation action | Configured endpoint pipeline | First and last images define the intended camera path. The two pipelines share the same image stage and output FPS; the endpoint workflow must expose one first-frame and one last-frame input. |
| Stationary source-art presentation with a locked camera | Existing source-frame hold route, when enabled in `joymedia_reference_retention` | The artwork is used directly instead of being repainted by the video model. |
| Stationary product detail requiring a controlled push or pull | Existing `compose_source_motion_take` candidate | FFmpeg animates the source image and records its hash. It is an unselected candidate until its crop and design are suitable. |

The operator mapping is `joymedia_endpoint_generation_pipelines`, for example
`{"PIPE-00058":"PIPE-00065"}` on this site. The mapping is consulted only when
an explicit ending image and suitable motion plan exist. A missing mapping leaves
the pinned reference route unchanged. An invalid configured pipeline fails before
submission. Changing the mapping cannot alter an already frozen run. Product-only
print details are not sent to the endpoint pipeline merely to create camera motion.

The registered candidate `PIPE-00065` reuses the promoted image stage `WF-02689`
and the existing MiniMax H3 FL2VA base 20-step workflow `WF-02683` from
`deploy/workflow-profiles/minimax_h3_i2v_base_20.json`. Its graph and sampling
remain in the workflow record. It needs no new model or application-specific
ComfyUI nodes. The FL2VA and Ref2VA checkpoints are different and cannot be
swapped inside one workflow version.

The endpoint frames must have the requested output aspect ratio before binding:
ComfyUI's native H3 image-to-video node stretches an off-aspect first frame and
centre-crops the last frame. The timeline prompt should describe one continuous
camera path between those images. MiniMax's base-mode prompt structure is
`integrated_multimodal_description`, `overall_soundscape`, then
`non_diegetic_music`; the full-reference structure has its separate reference
definitions and retention sections. The current JoyMedia serializer still uses
one internal five-part structure for both modes, so the route alone does not
establish prompt-format parity with the upstream guides. That is a separate
quality issue to qualify before broad promotion.

An ending sentence, generated final pose, or second identity view is **not** an
explicit last-frame image. The system cannot yet create and qualify such an
endpoint automatically from a brief. Most product-only automatic batches will
therefore remain on Ref2VA until that stage exists. An endpoint image still needs
the right subject, support, proportions and package art; a model can interpolate
incorrect anatomy or lettering between correct endpoints. Neither route repairs
a screenplay with actions in the wrong order. The existing causal review and
rendered-video quality evidence still govern those issues.

The current Shera automatic preview `PRJ-02618` used six Ref2VA tasks, so it
establishes the reference path only. Route tests and the site dry run show the
new endpoint route selects the candidate for an explicit moving endpoint while
retaining Ref2VA for an unanchored, unknown-action, or manipulation shot. A real
ComfyUI endpoint smoke render is under `verification/hybrid-routing-20261022/`.
It followed the two supplied compositions, but the middle frames invented an
implausible tissue transition and altered the product rendering. Its source
endpoints also came from an already defective wipe shot. This qualifies the
transport and conditioning, **not** the action quality. The candidate remains
registered but unpromoted in site configuration until a non-manipulation camera
shot passes visual review. Never use FL2VA to repair a physical-contact error.
