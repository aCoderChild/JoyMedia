# Optional upstream consistency tools

JoyMedia does not vendor model code or model weights. Its durable contract is
an immutable **Asset Version**, a canonical **Identity Key**, and a versioned
Generation Workflow. This keeps a project reproducible when an external model
or its ComfyUI nodes change.

The following shallow source checkouts are available outside the application
repository at `/workspace/development/upstream/joymedia`; no weights were
downloaded and none of these repositories are imported by the Frappe process.
They are deliberately separate from the app: a Frappe request must never load
model code or a GPU model in-process.

| Tool | Pinned source revision | Appropriate use | Not used for |
| --- | --- | --- | --- |
| [MV-Adapter](https://github.com/huanngzh/MV-Adapter) | `4277e0018232bac82bb2c103caf0893cedb711be` | Make candidate front/side/three-quarter character views from an approved image. | Choosing JoyMedia workflows or rendering H3 video. |
| [ComfyUI-MVAdapter](https://github.com/huanngzh/ComfyUI-MVAdapter) | `9d6d8afeff135d81a31f16dde5291d8b40dbb0a4` | Run MV-Adapter as an isolated ComfyUI custom-node workflow to create candidate character turnarounds. | Replacing the production FLUX keyframe or H3 video stages. |
| [Story2Board](https://github.com/DavidDinkevich/Story2Board) | `92ef11077c3a596a32241e434b0c527ec54f2546` | Optional human storyboard-preview research. | Workbook import, asset identity, or production scheduling. |
| [ViStoryBench](https://github.com/ViStoryBench/vistorybench) | checkout-local revision | Offline evaluation of story-level identity, narrative, and style consistency. | A production rendering dependency or an automatic approval authority. |
| [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) | `f8db63096c8282cb27354314d896feba5ba6ff8a` | Optional 3D mesh after multi-view images are approved, then deterministic renders from the mesh. | A required dependency of the FLUX → H3 pipeline. |

## Installing a pinned ComfyUI extension

Source checkout alone does **not** make a ComfyUI extension available.  On the
GPU host, an operator installs the exact pinned source into the ComfyUI Python
environment, restarts ComfyUI, and verifies the node metadata before a
workflow record can be imported:

```bash
sudo /path/to/joymedia/deploy/install-comfy-extension.sh \
  /home/ubuntu/ComfyUI /home/ubuntu/comfy_env/bin/python \
  https://github.com/huanngzh/ComfyUI-MVAdapter.git \
  9d6d8afeff135d81a31f16dde5291d8b40dbb0a4 ComfyUI-MVAdapter
sudo systemctl restart joymedia-comfyui
curl -fsS http://127.0.0.1:8188/object_info > /tmp/comfy-object-info.json
```

The resulting `object_info` must contain the exact MV-Adapter node classes
used by the exported graph.  JoyMedia performs this same node-type preflight
before it queues any workflow, so a missing extension fails safely before GPU
generation.  Do not hand-convert the upstream visual workflow JSON: open it
in the installed ComfyUI instance and export its API-format graph, then store
that immutable graph in a new Generation Workflow revision.

MV-Adapter is SDXL-based.  It is therefore an optional **asset-preparation**
step for making candidate character views, not a new model-selection branch
in the FLUX → H3 production pipeline.  A human must approve those views before
they become Asset Versions with one shared Identity Key.

## Operational contract

1. Generate candidate views in an isolated environment for an external tool.
2. Human-review the candidate sheet against the supplied reference; reject a
   view that changes markings, accessories, proportions, or the intended
   character.
3. Upload only approved views to JoyMedia as `Character` references. Give all
   views of the same subject one **Identity Key** in the asset inspector (for
   example `shera_mascot`). Keep each row's **Reference Key** unique (for
   example `shera_front`, `shera_side`).
4. The planner treats that group as one cast member. When a scene selects it,
   JoyMedia expands the group in a stable order into the frozen task inputs;
   the configured keyframe workflow decides whether it consumes individual
   slots or a deterministic reference board.
5. Approve the resulting keyframe before H3. The H3 first frame is the visual
   source of truth for the short clip. Use an explicit H3 last frame only for
   a planned continuous end state; it is never inferred from a character
   asset or forced onto every segment.

This design lets a future multi-view generator, rigging system, or ComfyUI
graph replace one preparation step without changing the Frappe data model or
the production pipeline.

## Physical action review strategies (2026-10-16)

Two additional shallow checkouts are pinned outside the application:

| Repository | Revision | Top-level code license | Strategy inspected |
| --- | --- | --- | --- |
| [VideoPhy](https://github.com/Hritikbansal/videophy) | `01d366c979e4a82875852adbf427ccc036e7373a` | MIT | VideoPhy-2 separates semantic adherence, physical commonsense and individual physical-rule judgments. |
| [VBench](https://github.com/Vchitect/VBench) | `fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490` | Apache-2.0 | Separate mechanics, action order, interaction and consistency dimensions; time-labelled video samples. |

Locations: `/workspace/development/upstream/joymedia/videophy` and `vbench`.
Their original licenses remain in those checkouts. No upstream source was copied
into application modules, no benchmark weights were downloaded, and neither
checkout is imported at runtime. Top-level code licenses do not establish the
terms of every model, dataset or embedded dependency. Future optional evaluator
installations must check those separately.

JoyMedia independently adapts these evaluation strategies through its configured
vision capability. It does **not** claim to run the official VideoPhy/VBench
AutoRaters or reproduce their benchmark scores. Research systems with
noncommercial or missing code terms were not incorporated into the product.

The durable integration is `services/review/temporal.py`, the consistency worker,
and a plain-language findings dialog. A single reviewed scene uses up to 16
actual-video samples around both uniform and authored event moments. Each vision
request has at most four full-frame images and one independent claim, fitting
small context services. Action occurrences and event order are separate from
continuous invariants. Authored times guide sampling but do not hide delayed
actions elsewhere in the clip; timing differences are reported separately.

The model must return a schema-constrained observation with real sample IDs.
Missing, duplicate, invented or ungrounded evidence becomes uncertainty. Known
violations dominate candidate results. An occurrence needs a positive witness;
an invariant needs support across its evaluated windows. Uncertainty is retained
in the raw evidence. A review does not submit new video jobs, select takes,
approve branding or release footage. Each private report binds its video hash,
asset version, direction hash, timestamps and image hashes. Late status writes
retain the existing compare-and-set protection.

### Structured output transport

The default HTTP encoding uses the standard `response_format.json_schema` field.
A runtime can explicitly select the alternate `structured_outputs` encoding with
`joymedia_vision.structured_output = {"transport": "structured_outputs", "compact": true}`.
This deployment's runtime otherwise produced whitespace loops despite a valid
schema; compact grammar decoding removes that format failure. No model/vendor
name appears in scene planning or evaluation decisions. Both transports retain
the same schema and the same independent evidence validation. Partial diagnostic
reports are labelled `partial` and cannot be returned as full scene findings.

The runtime option is described in the [vLLM structured-output documentation](https://docs.vllm.ai/en/latest/features/structured_outputs/).

The reference-consistency adaptation also uses a deterministic opening-state
comparison against the frozen conditioning artifact. It tolerates codec/VAE
texture variation and reports global/local errors, with substantial mismatch
requiring review. This independent check caught a reversed clip that the VLM
had incorrectly supported. It is not the official learned VBench metric and
cannot certify subsequent motion or exact identity.
