# Shera workflow verification and production strategy

Verified against the supplied workbook and photographs, the existing JoyMedia application,
and the configured ComfyUI server on 2026-10-15. Test workspace: `PRJ-02502`, owned by
`uitest@example.com`. No account password is stored in this report or the browser tests.

## Follow-up: general preservation system

The later refactor and research are documented in
[identity-preservation.md](identity-preservation.md). The revised review export is
`ASTV-04021`; the original package front is restored across all 96 frames of scene 3
in immutable take `ASTV-03997`. Its source hashes, protected frame coverage and
tracking measurements are stored on the Asset Version, independent of the video
provider. The account's full film retains seven scenes, six narration cues and stereo
audio. `../videos/identity_preservation_verification.json` records the current output
checksum and exact timeline sources; the historical runs described below remain
useful evidence of the earlier failure and correction sequence.

The additional mascot-expression candidate still changed the eyes. A localized
source-face repair was rejected at frame 22 for ambiguous tracking and produced no
promoted output. Six moving scenes remain without brand approval. The new release
endpoint blocks that film; review export remains available. A planar source-label
repair is not proof that a deforming mascot's identity has been solved.

## Source requirements

`SAN PHAM AI/kich_ban/Shera_TVC_30s_JoyMedia.xlsx`, sheet `TVC 30s`, specifies **30 seconds,
9:16, one Shera mascot**, with these exact edit ranges at 24 fps:

| Scene | Time | Frames | Essential action / finishing requirement |
|---|---|---:|---|
| Buổi sáng êm đềm | 0–4 s | 0–95 | Cookies, one glass, blue pack visible on the table |
| Sự cố đáng yêu | 4–7 s | 96–167 | Accidental small spill; intact glass; “Ối!” |
| Shera luôn ở đây | 7–11 s | 168–263 | Paw physically pulls one sheet from the pack |
| Thấm hút – bốn lớp | 11–16 s | 264–383 | Gradual absorption; approximately 1 s four-layer illustration; USP caption |
| Mềm mại khi chạm da | 16–21 s | 384–503 | Discard used sheet, take a NEW sheet for the cheek |
| Khoảnh khắc dịu dàng | 21–25 s | 504–599 | Correct pink-heart variant and emotional pause |
| Packshot & kết thúc | 25–30 s | 600–719 | Source packaging, Vietnamese caption/CTA, stable final 48 frames |

The workbook's scene words, captions and voice-over remain the source of truth. A 30-second
film is 720 delivery frames, rather than seven untrimmed 124-frame model clips.

## Four supplied files

All four originals contained non-breaking spaces outside JSON strings. Standard JSON parsers
rejected them at line 2. Their original bytes are retained in `workflows/originals/`.

| File | Actual type | Findings and repair |
|---|---|---|
| `workflows/1.json` | `/prompt` request containing an API graph | Repaired JSON; removed unsupported H3 `batch_size`; corrected landscape dimensions and mother/yellow-pack prompt to portrait, one mascot, blue packaging. Raw API companion is `workflows/api/1_api.json`. |
| `workflows/2.json` | ComfyUI UI graph | Repaired JSON, portrait dimensions and prompt; removed obsolete extra H3 widget. UI links and widget order checked against live schemas; API companion generated. |
| `workflows/3.json` | MMAudio UI graph | Repaired JSON. `best_netG.pt` was incorrectly assigned to `clip_model`; replaced with the installed Apple DFN5B CLIP feature checkpoint. Seed control is a UI widget, not the next API argument. API companion generated. |
| `workflows/4.json` | Combined UI graph | Same repairs. It contains independent H3 and music branches. It does **not** assemble seven scenes, schedule narration/captions, mix audio, or export the complete TVC. API companion generated. |

All four repaired exports pass `joymedia.services.workflows.audit` against the live server's
`/object_info`, including node availability, required inputs, model options, link output indices,
socket types, dependency cycles and UI link destinations. The verifier understands V3 dynamic
inputs and polymorphic sockets. Dynamic/custom validation remains ComfyUI's responsibility;
a schema pass alone does not prove successful inference or acceptable creative quality.

The native PNG workflow exports listed in the screenshot were not among these four files.
The screenshots themselves are documentation, not embedded ComfyUI graph metadata.

## Parameters verified against the deployed server

- ComfyUI reports version `0.39.0` and an NVIDIA RTX PRO 6000 Blackwell Server Edition.
  Its model dropdowns contain the H3 INT8 model, Qwen3-VL minimax encoder, two H3 VAEs,
  turbo LoRA, FLUX.2 klein 4B and its text encoder/VAE, and MMAudio large 44k v2 files.
- The deployed H3 source creates a **nested pair of video and audio latents**. Sampling that
  pair once and sending it to both decoders is intentional. `cfg=1` also makes the reused
  positive/negative conditioning in the supplied turbo graph an unguided path, not two
  independently meaningful prompt directions.
- H3 frame lengths snap upward to `17k+5`: 124 frames is **5.1667 s**, not exactly 5 s.
  JoyMedia retains the requested scene frame count and normalizes/trims the generated clip.
- Native working sizes are 1344×768, 768×1344 and 1024×1024. The production binding now
  chooses the nearest native shape from the delivery aspect ratio. It no longer turns
  720×1280 into an arbitrary 704×1280 canvas. Delivery/export remains the project format.
- Video/audio shifts are explicit: **12.0 / 3.0**, between the selected base/LoRA model
  and both scheduler and guider.
- The supplied graph's turbo recipe is LoRA strength 1, 8 steps, Euler/simple, CFG 1.
  The registered production graph retains the existing 20-step base-model recipe and
  `res_multistep` sampler. Eight steps is an available speed/quality tradeoff, not a
  universally demonstrated optimum. The screenshots' timing and quality claims were not
  treated as measured benchmarks.
- MMAudio uses `mmaudio_large_44k_v2.pth`, `v1-44.pth`, `synchformer_state_dict.pth` and
  `apple_DFN5B-CLIP-ViT-H-14-384_hfcache_fp32.bin`. The native model outputs 44.1 kHz audio;
  final audio encoding follows the exporter.
- The screenshot's OmniGen directory and Python executable exist on the GPU host. That
  does not verify its weights, Transformers patch, latency or concurrency claims. It is
  not a registered node in this ComfyUI installation. The installed, reference-aware
  **FLUX.2 klein** stage is used instead of adding an untested execution service.

## Reference photographs

All three supplied photographs are opaque JPEGs. The screenshot's RGBA-flattening advice
does not apply to these inputs. Transparent art should stay transparent when used by the
compositor; only image-model reference boards need a neutral background.

- `mascot.jpg` is a four-view turnaround, not four characters. It has a cream body, small
  ears, brown paw pads/claws and a yellow flower. A native ComfyUI `ImageCrop` workflow
  and its generated single-view derivative are in
  `workflows/shera_mascot_single_view_api.json` and `workflows/references/mascot_single_view.png`.
  The source is preserved. Existing immutable runs retain their original reference snapshots;
  the derivative is available for a revised reference selection rather than silently replacing them.
- `mascot_front.jpg` is the pink-heart pose. It is assigned to the final two scenes as the
  workbook specifies, rather than introducing a second bear into the scene.
- `product.jpg` is **blue** Shera packaging, with “400 TỜ | 4 LỚP.” The original workflow's
  yellow pack description was inconsistent with it. Reference conditioning cannot guarantee
  exact small print after diffusion. The closing-card compositor now includes opaque JPEGs
  as source-art panels on a white board; it previously only pasted transparent art.
  Product layers are no longer colour-matched/tinted to the room.

## Implemented production path

1. Upload the workbook and three references in Frappe UI. Intake reads `TVC 30s`, derives
   portrait format and exact timings, and matches named reference rows by filename.
2. Follow the sheet, review the storyboard, and draw each recurring location once. FLUX.2
   klein receives separate character, product and location references. Explicit still-frame
   edits now take priority over the motion paragraph; long source directions are no longer
   truncated at 300 characters.
3. Review the frames before H3. A still image cannot prove successful spilling, gradual
   absorption or use of a fresh sheet; those are also take-review requirements.
4. Animate from each approved frame. New runs use immutable pipeline `PIPE-00037`,
   keyframe workflow `WF-02656`, and H3 workflow `WF-02659`. Older runs remain pinned.
   One endpoint dispatcher preserves GPU capacity and fairness with other existing projects.
5. Keep sound in separate layers. H3 supplies candidate foley; the existing audio screen can
   substitute scene-conditioned MMAudio effects. `mmaudio_bgm` (`WF-02657`) independently
   generates an 8-second instrumental phrase with no video conditioning. Finishing crossfades
   it to film length and ducks it under narration/effects. Music requests no longer inherit
   the foley workflow's negative “music” conditioning or require throwaway H3 picture.
6. Generate or upload voice-over separately. The optional `narration` extra supplies the
   tested Vietnamese female `vi-VN-HoaiMyNeural` voice. The per-scene menu places it on the
   voice-over track. Only quoted dialogue / narration text is spoken; “VO nữ” and “Không
   thoại” are not read aloud. Synthesis preserves complete words and checks scene duration;
   excessive speed-up fails visibly. Existing recordings are preserved on repeated clicks.
7. Compose exact scene durations, captions and CTA in the editor. New product-closing runs
   use the approved source-art frame for their final two seconds; FFmpeg verification confirms
   that this changes neither frame count nor total duration.

The absorption scene's explicit request for a graphic showing four paper layers now creates
a deterministic one-second insert at scene-local 3–4 s (film time 14–15 s). The count comes
from the storyboard request, is frozen in the run snapshot, and is drawn by the compositor.
An ordinary product description mentioning layers does not create an unsolicited graphic.

Still-frame QA now compares the planned starting image rather than requiring later motions,
feelings or intentions to be visible in a still. Character counts exclude pictures printed
on packaging. A delayed automated concern remains visible but cannot redraw an approved
frame. Project Stop cancels all of that project's active runs; stop intent is committed
before network calls, and conditional updates preserve work that finishes concurrently.

Task preparation now retries transient InnoDB conflicts from a rolled-back transaction,
under a per-run lock. This addresses the actual failure encountered in the live account run.
Preparation does not queue GPU inference, so these retries cannot duplicate model jobs.

## Verification and limits

- Authenticated upload, workbook preview, project creation, planning, approval and keyframe
  generation were exercised through the real application as `uitest@example.com`.
- All six spoken lines were generated and saved as private audio assets for `PRJ-02502`.
- The first H3 take completed against the real server, and the real MMAudio music bed was
  rendered and saved as `ASTV-03820`. The full seven-scene native-size render is `RUN-00539`.
- Browser tests verify account identity, 7-scene/30-second/portrait intake, studio rendering,
  and HTTP access to actual private generated keyframes.
- Backend tests cover graph conversion/schema checks, native H3 dimensions, routing,
  orchestration/retries, independent still prompts, audio planning, source-art compositing
  and the exact final hold. These tests do not assert that an image model obeyed the script.
- Initial visual review found extra glass geometry in the first frame and implausible spill
  details in the second, despite an automated consistency pass. The first, second and fifth
  frames were corrected and reviewed before the full render. A reference-image or schema check
  is insufficient evidence of physical continuity, exact packaging throughout moving shots,
  or the quality of an illustration. The explicit four-layer diagram is composited as a
  distinct insert; its timing and four visible sheets are tested separately from captions.

### Completed export evidence

The first complete export was downloaded through the owner's authenticated session to
`../videos/Shera_TVC_30s_JoyMedia_verified.mp4`: exactly 720 frames, 24 fps, 720×1280,
30.000 seconds, with an audio stream. `../videos/shera_verification_manifest.json` records
its checksum, selected timeline, source run, audio assets and full FFprobe output.
All three Playwright account tests passed, including the private MP4 download, seven selected
takes, six narration cues at frames 96/168/264/384/504/600 and an enabled BGM track.
204 targeted backend checks passed across the modules exercised during this work;
this is not a claim that the entire repository test suite ran.

Visual inspection of the export confirmed the separate four-layer insert and the original
pack/heart-mascot source art in the closing hold. It also caught human-looking fingers in
the absorption take despite an automated Passed result. A further targeted correction uses
a medium shot with the bear's face and rounded paws visible (`RUN-00543` keyframe), rather
than trusting the automated pass. The reviewed bear-visible frame from `RUN-00544` was
selected for the replacement take `RUN-00546`. Moving-shot pack lettering and physical
tissue continuity still need human review before publication.

The draw prompt's reference ordinal now includes product images before naming the room
reference. With mascot + product + room, the environment is image 3, not image 2; a dedicated
regression test covers the actual order passed to ComfyUI.

### Brand integrity is a separate acceptance requirement

An automatic scene-action/count pass is **not** certification of mascot identity or logo
typography. The local vision model previously failed these comparisons; adding more identity
questions to that same judge would create misleading confidence. The studio now says
“Scene action checks passed” and separately shows “Product, logo & mascot review required”.
Human brand approval is bound to the exact selected take and all of its immutable reference
versions, with reviewer and time recorded. A new take or reference invalidates that approval.
Stale browser approvals are rejected. Final-video API metadata reports pending brand reviews;
a technically completed review export is not automatically brand-approved.

The final packshot now preserves the approved source-art composition for its entire duration,
including the five-second Shera closing scene. `keyframes.brand_card.preserve_closing_art`
creates a new immutable composed take without regenerating the source pack or mascot. Future
run snapshots request this full-duration source hold. Captions remain deterministic overlays.

For moving scenes, the reliable production strategy is an approved canonical single-view
mascot/model sheet and a source pack/logo matte composited with tracked placement and explicit
occlusion handling. Prompt conditioning alone cannot preserve typography. Existing transparent
product inputs already use the source-pixel placement/lock path; these supplied JPEGs do not
contain a foreground matte. The installed Comfy background-removal loader has **no model
options**, so claiming automatic, validated source-product matting would be false. Opaque JPEG
photographs are preserved as intentional source-art panels in the closing card. Other generated
pack print and mascot geometry remain unapproved until visually matched; the new brand review
state makes that limitation explicit instead of silently treating an action pass as brand approval.

### Final account result

- Account: `uitest@example.com`; project: `PRJ-02502`.
- Revised final export: `ASTV-03961`; replacement absorption take: `ASTV-03900`;
  full-duration source-art closing take: `ASTV-03937`.
- Actual output: 30.000 seconds, 720 frames, 24 fps, H.264 720×1280,
  AAC stereo 48 kHz, measured audio peak −3.0 dBFS.
- All three final Playwright tests passed against this revised export, including
  the brand-review metadata and authenticated private MP4 download.
- The source-art closing take was visually compared and approved through the public
  owner API. Six moving scenes remain without brand approval. Concrete comments are
  attached to takes in scenes 2–6; scene 2 visibly changes the mascot's eye design,
  and moving pack geometry/print are not certified against the original photograph.
- `../videos/Shera_brand_review.png` compares source references with two sampled
  frames from every selected take. It is a review aid, not evidence that unsampled
  frames are correct. `../videos/shera_verification_manifest.json` records the
  selected take IDs and separate brand-review state alongside the technical evidence.

**Release status: review render, not approved for marketing publication.** The pipeline
works end to end; generated moving-shot identity and packaging still require corrective
compositing or approved replacement takes. Generating more random takes without that
asset-preservation work does not provide a reliable brand-consistency guarantee.

Audio export also now converts every input to 48 kHz stereo before mixing, preventing a mono
narration source from collapsing stereo music. A final limiter with 3 dB of headroom prevents
summed sources from clipping. An actual FFmpeg test mixes mono voice and an asymmetric stereo
bed, then checks decoded channel energy and AAC peaks, alongside the existing composer tests.

## Reproduce

From `frappe-bench/` (use a fresh live `/object_info` snapshot when server nodes change):

```sh
env/bin/python -m joymedia.services.workflows.audit \
  --object-info /tmp/shera_object_info.json --output-dir ../workflows/api \
  ../workflows/1.json ../workflows/2.json ../workflows/3.json ../workflows/4.json
bench --site joymedia.localhost execute joymedia.install.setup
bench --site joymedia.localhost migrate
env/bin/python -m unittest joymedia.tests.workflows.test_schema joymedia.tests.audio.test_speech
bench --site joymedia.localhost run-tests --module joymedia.tests.generation.test_preparation_retry
bench --site joymedia.localhost run-tests --module joymedia.tests.keyframes.test_brand_card
```

From `joymedia/frontend/`, supply the test login through environment variables:

```sh
SHERA_TEST_PROJECT=PRJ-02502 npx playwright test tests/shera-pipeline.spec.js --workers=1
```

`JOYMEDIA_TEST_USER` and `JOYMEDIA_TEST_PASSWORD` must also be set. The browser tests do
not enqueue expensive model jobs on reruns. The screenshot is written to
`joymedia/frontend/test-results/shera-studio.png`.

Set `SHERA_EXPECT_EXPORT=1` to include the final owner-authenticated video download test.
It checks all seven takes, the six voice-over start frames, a BGM track, 720 video frames,
24 fps and portrait aspect ratio using FFprobe. Narration is optional at deployment:
install the `narration` package extra to enable the generation button's backend.

Upstream references: [MMAudio node implementation](https://github.com/kijai/ComfyUI-MMAudio/blob/main/nodes.py),
[Microsoft Vietnamese neural voices](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support),
[edge-tts](https://github.com/rany2/edge-tts).
