# JoyMedia live system verification — 27 October 2026

## Scope and result

I tested the installed Frappe site and its configured ComfyUI server, using the existing Shera references. The result is **not an accepted end-to-end video**. The mascot-inclusive UI batch stopped because three requested poses lacked qualified references. I then submitted a separate product-only project through the UI. Its first planning attempt revealed a reference-role key mismatch, which I fixed and covered with a regression test. A correctly configured 9:16 project reached ComfyUI through the UI, but its preview run failed product-reference preparation. The output from its other task placed the package on the floor despite the brief requiring a table. Separate direct workflow probes also found product-identity drift.

| Stage | Live evidence | Assessment |
| --- | --- | --- |
| Frappe UI and API | Authenticated project page loaded. Clicking **Tạo video mới từ ảnh tham chiếu** on `PRJ-02709` returned `CRB-00094`. | Pass for request submission. |
| Queue and script planning | `CRB-00094` created `PRJ-02710`; the creative preparation job ran and produced a five-scene script. | Pass for dispatch and planning execution. |
| Script-to-reference binding | Scenes 3–5 requested standing poses without qualified matching references. The batch became **Needs Attention** with the pose verification error. | Blocked. Automatic recovery has not delivered usable pose assets. |
| Storyboard and first frames in that batch | `PRJ-02710` has zero `Shot` and zero `Generation Run` records. | Not reached. |
| Product-only planning | The first attempt, `PRJ-02711`, exposed `KeyError: 'usage_role'` in routed reference validation. The code now reads the routed record's `reference_role`. Rerunning the same project through the UI produced five shots. Its render run was cancelled because the test brief had omitted explicit 9:16 dimensions. | General planning defect fixed; dimensions setup error isolated. |
| Contiguous UI → ComfyUI render | The 9:16 project `PRJ-02712` was planned, approved and submitted from the UI. `RUN-01307` reached ComfyUI (`ATT-02366` and `ATT-02367` have external prompt IDs). Its two tasks finished one failed, one completed; the overall run is **Failed**, with no selected shot output. | Real transport pass; no accepted preview. |
| Live visual output | The reference-preparation task rejected a product view incompatible with the supplied photo. The other returned a Shera package in a room, visibly on the floor rather than on the requested table. | Product geometry/support requirement fail. |
| Registered ComfyUI first-frame workflow | `WF-02656` accepted the Shera product reference and returned a 512×768 PNG. The visible output is an unrelated package with invented text. | Transport pass; product fidelity fail. |
| Registered ComfyUI video workflow | `WF-02681` accepted that PNG and returned a decodable H.264/AAC MP4. The wrong product persists. A request for 25 frames yielded a 39-frame, 1.625-second file at 24 fps. | Transport pass; fidelity fail; frame count needs investigation. |
| Narration, SFX/BGM, stitching, export | No new-batch output from these stages. The current active pipeline contains keyframe and video workflow entries; narration code has an Edge fallback when no narration workflow is configured. | Not verified by this run. |

The ComfyUI server reported an **NVIDIA RTX PRO 6000 Blackwell Server Edition** with approximately 102 GB decimal VRAM. This identifies the connected GPU; it does not validate the screenshot's per-stage timing estimates. I did not benchmark throughput, model switching, concurrent jobs, 2K output, or final 5.2-second delivery.

## Evidence

- Batch: `CRB-00094`; source: `PRJ-02709`; child: `PRJ-02710`; final batch state: `Needs Attention`.
- UI screenshot: [frappe-ui-blocked.png](../../verification/system-live-20261027/frappe-ui-blocked.png).
- Product-only storyboard: [frappe-ui-product-only-storyboard.png](../../verification/system-live-20261027/frappe-ui-product-only-storyboard.png). The contiguous render's candidate image is [ui-rendered-candidate.png](../../verification/system-live-20261027/ui-rendered-candidate.png); it is an intermediate artifact, not an approved first frame.
- First-frame GPU probe: [comfy-first-frame-smoke.png](../../verification/system-live-20261027/comfy-first-frame-smoke.png). The image is technically returned but is not the referenced Shera pack.
- Video GPU probe: [comfy-h3-smoke.mp4](../../verification/system-live-20261027/comfy-h3-smoke.mp4); [last frame](../../verification/system-live-20261027/comfy-h3-end.png).
- Targeted Frappe tests passed: 17 physical audit, 6 workflow resolver, 19 ComfyUI client/route, 26 product-view, and 1 new routed-reference regression test (69 total). These are contract tests; the live visual failures above take precedence for acceptance.

## Implications for the supplied architecture and task board

The screenshots describe a target architecture and mark several tasks complete. The installed site does have a working UI/API/queue connection and registered FLUX2 Klein and MiniMax H3 workflows. The current real test does **not** establish a fully integrated automatic flow from references through storyboard, qualified multi-pose and multi-angle assets, video, audio, and export. The planner also asked for a "right panel bear" in the product-only storyboard, although the supplied right end panel does not show that artwork. A completed infrastructure or engine task must be evaluated separately from whether the generated commercial content is usable.

The next acceptance run should require: (1) an automatically recovered or suitably revised script whose requested character states have qualified visual inputs, (2) each first frame matching mascot anatomy and the real product print, angle, scale, and support surface, (3) video preserving those identities and delivering the requested frame count/duration, and (4) audio plus final export. A failed visual gate should remain visible as a failed output, not be counted as a successful render.
