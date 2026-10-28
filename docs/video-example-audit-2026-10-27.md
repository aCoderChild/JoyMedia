# Video example audit — 27 October 2026

## Scope and evidence

Frappe contains 213 projects, 421 video assets (679 immutable versions) across 63 projects, and 34 projects with a selected final output. All 679 referenced video files exist. Of the 421 assets, 418 have a saved version; three have no version yet. Three temporal samples from each of those 418 versions decoded successfully, with no blank samples. The 34 selected finals were screened visually at five evenly spaced points; contact sheets and the full inventory are under `/workspace/development/verification/video_audit_2026_10_27/`. This is a screening pass, not frame-by-frame certification of 421 videos.

Selection considered support/contact, identity and packaging consistency, readable action, composition, and a distinct marketing progression. The two selected cuts were screened again at 16 evenly spaced points each (`detail_PRJ-02566.jpg` and `detail_PRJ-02563.jpg`). A `Completed` status alone was not treated as quality approval; the sampled finals have no release review evidence in their `Asset Version` records.

| Candidate | Decision | Evidence from sampled frames and saved script |
| --- | --- | --- |
| `PRJ-02566` / `ASTV-04894` — Shera | Use abstract pacing and shot structure | A supported tabletop pack, distinct spill, extraction, material proof, payoff, and pack finish. Some transitions and exact physical contact remain unverified between samples. |
| `PRJ-02563` / `ASTV-04667` — AUNTIE shirt | Use abstract pacing and shot structure | Brisk model opening and closing, interleaved unpacking and garment details; printed front remains comparatively stable in samples. Hand and fabric behavior between sampled frames still need continuous review. |
| `PRJ-02643` / `ASTV-05559` — Shera | Exclude from examples | Attractive first-frame style, but the saved script repeats pressing and handling the same tissue across multiple beats. |
| `PRJ-02668` / `ASTV-05850` — Shera | Exclude from examples | The pack appears below the table in sampled middle frames, so product support is unclear. |
| `PRJ-02559` / `ASTV-04590` — AUNTIE | Exclude from examples | The project is `Needs Attention`; the short sampled cut does not supply a strong multi-shot marketing structure. |

## Integration

`approved_examples.json` stores only relative scene durations, shot sizes, line lengths, tone and abstract marketing roles from the two selected cuts. `script_exemplars()` loads this library when no client workbook is supplied. The AI Director receives no other project's product name, dialogue, action text, claims, or visual asset from the library. A client's own workbook remains the source when supplied.

The selected project JSON is preserved in each source project's `storyboard_source_json`; the exact final versions above identify the reviewed cuts. Their imagery is evidence for curation, not a substitute for the new project's product, actor, pose or packaging references.

## Verification

All 160 planning tests passed with a connected Frappe site, including the two focused script-example tests. A live Frappe API batch, `CRB-00100` / `PRJ-02719`, was submitted with the selected AUNTIE source references and the new fallback library. Its first planning attempt reached the planning worker but timed out while waiting for the local planner model (`127.0.0.1:8001/v1`, 300-second read timeout). The batch returned to `Queued`, with no saved script, storyboard, generation run or ComfyUI prompt. The planner's `/v1/models` endpoint still responds, so the observed failure is at inference rather than HTTP reachability. This is a failed end-to-end test, not evidence that the library produced a usable video. A separate older rewrite job is running on the planning worker. Recheck the automatic retry and record a ComfyUI prompt and output before claiming an end-to-end pass.
