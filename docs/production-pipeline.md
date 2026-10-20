# Storyboard → approved references → configured video pipeline

The production architecture is provider-neutral. FLUX/H3 names below describe the
shipped deployment, not application-wide model requirements. For source artwork,
runtime capabilities, tracked repair and release acceptance, see
[identity-preservation.md](identity-preservation.md). Model conditioning is not an
exact-label guarantee. Partial static product locks now fail rather than falling
back to the generated clip; approved source planes can be restored using the
studio's model-independent compositor.

One promoted, immutable pipeline renders every project. It does not choose a workflow from the number or kind of
references in a scene. Nothing here is specific to one product: the Shera film is only the first project run through it.

```
 sheet (.xlsx) + pictures (PDF or files)
      │  intake            Client intake dialog / joymedia.services.intake.project
      ▼
 project + scenes + references           Media Project, Shot, Project Reference
      │  planning          "Follow the sheet" (default for a workbook) or "Creative" (brief only)
      ▼
 approved storyboard                      Storyboard Approval workflow
      │  keyframes         one FLUX picture per scene that opens a scene, reviewed and approved
      ▼
 approved keyframes                       "Storyboard frames" panel
      │  video             H3 image-to-video from each approved frame (one scene = one run)
      ▼
 scene takes                              scene strip, takes 1/2/3, per-scene review
      │  edit + sound      timeline, captions from the sheet, sound-effect screen
      ▼
 exported film                            Export button → final video
```

## Install on a new site

```bash
bench --site <site> migrate
bench --site <site> execute joymedia.install.setup                      # registers workflows + pipeline, reports gaps
bench --site <site> execute joymedia.install.setup --kwargs '{"promote": 1}'   # after a smoke render passes
```

`setup` is idempotent and only creates a version when the shipped graph differs from the site's. Promotion is
deliberate: it writes `joymedia_active_generation_pipeline` to `site_config.json`. A project re-pins itself to the active workflow
and pipeline when its videos are generated, so nothing needs re-saving after a promotion.
Rollback = promote the previous pipeline name; existing runs keep their snapshot.

Also set `scheduler_tick_interval` to 60 in `common_site_config.json`, otherwise finished renders are noticed only every
four minutes and the GPU idles (the readiness list warns about it).

Every tunable number (layout fractions and audio screen thresholds) is in `services/project/tuning.py`.
A site overrides any of them in `site_config.json` under `joymedia_tuning`, for example
`{"character_height": 0.45, "effects_flatness_min": 0.35}`.

## What the client provides

Required: **a story**, either an `.xlsx` storyboard sheet (pick one sheet in it) or a written brief. The studio's
*New video* dialog offers a **downloadable template** (Vietnamese or English, `download_storyboard_template`) in the
same layout as the clients' own sheets: the brief in A1:B9 (labels in column A, USPs one per row in B3:B5), then the
scene table from row 13 with the columns *Phân cảnh, Thời lượng, Hình ảnh & Góc máy (Visual / Camera), Hành động &
Diễn xuất (Action), Lời thoại / Voice-over (VO), Âm thanh (SFX & BGM), Chữ hiển thị (On-screen Text), Minh hoạ khung
hình* as an Excel table named "Storyboard". Must-have label cells are amber, every label has a note saying what to
write, and a guide sheet explains it. The sheet is read by header, not by position, so a client's own layout works too:
labels are matched accent-insensitively against synonyms (`planning/workbook.py`), and a label nothing matches is placed
by the AI planner (checked against the schema). The dialog shows "what we understood" (✓ found, ✗ missing must-have,
– optional) before anything is created, and the brief becomes the project's *Ý tưởng video* in the sheet's own words.

| Brief field (sheet label) | Must-have | Used for |
|---|---|---|
| Product name | yes | project name, prompts |
| Objective | yes | the video idea given to the planner |
| Main USPs (one per line) | yes | one drafted scene each when there is no scene table |
| Duration | yes | total length (timings are shared out when scenes have none) |
| Format | yes | 9:16 / 16:9 / 1:1 |
| Tone & Mood | yes | the video idea / mood |
| Characters (one per line, "main character" marks the lead) | yes | cast names; the readiness list warns when no character/person picture is added |
| Assets ("Tài nguyên") | not in the template | still read from older sheets; the pictures themselves are named on the References sheet and uploaded |

Scene table columns: **Scene name** and **Action** are required for each scene; Timing, Visual & camera, Voice-over,
Audio cues, On-screen text and Illustration reference are optional. Four optional columns follow them (I–L):

| Column | What the client writes | What happens with it |
|---|---|---|
| Nhân vật trong cảnh / Characters in the scene | names from the References sheet, comma-separated (a dropdown helps) | exactly these characters are in the scene; nothing is inferred from the action text. A name with no picture is drawn from the text and flagged in the scene's notes |
| Sản phẩm trong cảnh / Products in the scene | the exact product (pack, size) by its name | exactly this product is pasted; blank means no product |
| Bối cảnh / Place | a place by its name | every scene with the same place gets the same setting text, so the same place picture (one room) |
| Logic / Liên tục / Logic / Continuity | what must hold ("the cup does not break") | translated and added to the scene's image and video prompts as rules |

Left blank (an older sheet), the scene is read from its action text as before.

Two optional sheets complete the workbook (shared by all its storyboard sheets):

- **Tham chiếu / References** (LTX-style "Elements"): one row per picture, place or prop, by **name**: Type (Character,
  Real person, Product, Logo, Place, Prop), the picture file to upload or a PDF and its page (`catalogue.pdf trang 8`),
  description, family role, relative height, and what must stay as is. When the pictures are uploaded they are matched
  to the rows by file name (accents, case and extension ignored) or PDF page (the largest picture on the page), and
  take the row's name, role, size and rule (`intake/references.py`). Only the PDF pages the sheet names are imported.
  The New video dialog lists the files to upload; the readiness list names any picture the sheet asks for that is
  missing. A place with no file is drawn by the AI from its description, and its rule joins the rules of every scene set
  there. A **prop** (a cup, a plate) is described once and that description joins the rules of every scene whose text
  names it, so it looks the same throughout. A description in the sheet's language is translated into the prompts; a
  rule ("a pull-out sheet, never a roll") goes into every scene that shows the picture.
- **Thương hiệu / Brand** (creative-brief practice): logline, the one-sentence key message, audience, visual style,
  approved claims, what must not be said or shown, and mandatories. The visual style and "must not show" go into every
  image and video prompt; the story helps translation; message, audience, claims, must-not and mandatories go to the AI
  planner (Creative mode, and the scenes drafted for a sheet without a scene table); the mandatories are listed on the
  readiness checklist for whoever finishes the film.

The blank template and filled examples are in `SAN PHAM AI/kich_ban/`: `JoyMedia_Mau_Kich_Ban_Trong.xlsx` (blank),
`Shera_Demo1_JoyMedia.xlsx` and `Shera_Demo2_JoyMedia.xlsx` (the client's two demo sheets) and
`Shera_TVC_30s_JoyMedia.xlsx` (the 30-second script). A picture the source does not identify is written in the
References sheet as "Cần ảnh: …", so the readiness list asks for it instead of the system guessing. A sheet with only the brief and no scene table is
valid: the scenes are drafted as one Hook, one per USP and one Outro, the length shared out of the total; the language
model writes their text from the brief alone, and an answer that is the wrong size or never mentions the product or
the selling point is dropped for plain text built from the brief. A sheet missing a must-have field cannot be created.

Everything else is read or defaulted:

| Input | Required | What happens with it |
|---|---|---|
| Storyboard `.xlsx` | one of sheet / brief | Scenes, timings, camera, action, voice-over, sounds, on-screen text; format and length from the sheet's own brief |
| Written brief | one of sheet / brief | The planner writes the scenes (Creative mode) |
| Pictures: characters (mascots), a real person's photo, products, logo, places | optional but strongly advised | Each picture gets a role (guessed from its name or page text, editable): Character, Person, Product, Logo, Environment. A PDF can be uploaded whole: its usable pictures are extracted (`add_pdf_images_to_project`; the New video dialog accepts a PDF next to the images) |
| Relative size per character/product | optional (default read from the name) | A new character named as a child ("gấu con", "bé …", kid, cub, baby) starts at 0.55 of the tallest; edit it in the inspector |
| Format (9:16 / 16:9 / 1:1), length | optional | Taken from the sheet; editable in project settings |
| Planning: Follow the sheet / Creative | default follows the input | Follow the sheet keeps the advertiser's scenes, characters and sounds and only translates |
| Characters: Draw in scene / Paste exact art | default Draw | Draw: characters act naturally like people. Paste: the real mascot picture is placed unchanged |
| Sound: Full / Sound effects only / Separate effects layer | default Sound effects only | See Sound |

Transparent pictures (PNG with an alpha channel) can be pasted exactly; opaque photos can only guide the image model.
A real person's face goes in as **Person** (identity-locked, not a style reference); a mascot or cartoon goes in as
**Character**. With no pictures at all, FLUX draws everything from the text.

## Stages and where to see them (Frappe UI, `/joymedia/projects/<name>`)

1. **Intake** — "New project" dialog: upload workbook and pictures, choose the demo. The readiness checklist
   ("Before you generate") lists what is still missing, in the studio's language.
2. **Storyboard** — a grid of panels, one per scene, like a drawn storyboard: the scene's first frame large (click it to
   play the scene's video in place), and under it what happens and how it is filmed in plain words: the sheet's own
   words in the Vietnamese studio, the English direction given to the video model otherwise. Each panel also holds the
   frame's status (Approve / Undo / Redraw), takes, timing, on-screen text and open comments. *Plan scenes with AI*
   writes the prompts (progress streams live). *Approve storyboard* locks the plan; any edit to a scene returns it to
   review. A project imported from a sheet follows the sheet: the video idea is the sheet's brief (read-only, replaced on
   every import), and *Improve idea* and *Ask the AI to change the storyboard* are hidden and refused by the server. To
   change it, edit the sheet and import it again, or switch the planning mode to *Creative*.
3. **First frames** — *Draw all first frames* in the grid's header first draws each place the scenes are set in, once
   and empty, then each scene's opening picture (about a minute each); approve each one on its panel. A frame drawn for
   different inputs than the scene now has is *Out of date*.
4. **Videos** — *Generate*/*Regenerate this scene*: each scene renders from its approved frame. Long scenes
   (more than 5.16 s, the H3 limit of 124 frames) are chained segments; each later segment starts from the preceding
   segment's generated last frame. An H3 last frame is supplied only when an approved destination composition is
   explicitly selected for that continuous action. Takes 1/2/3 of a scene can be stepped through.
5. **Review** — two places, one list. In the storyboard, a scene's panel takes comments on the *whole scene*. In the
   timeline (edit) view, the comment bar under the timeline comments on the frame under the playhead, or on a range
   between *Mark start* and *Mark end*; markers show every comment on the timeline and clicking one jumps there. *Apply comments* writes the open comments, with their times,
   into the scene's video prompt as reviewer corrections and renders a new take from the same approved first frame
   (so the mascot cannot change); the comments then show as *Sent to a new take*. Comments can be marked done or
   deleted, never block export, and are kept per take (`services/review/comments.py`).
6. **Edit and export** — timeline of the scene clips in storyboard order with the sheet's timings, captions drawn from
   the sheet's on-screen text, then *Export*. The finished film is the "final video" card of the studio.

Project settings (gear icon) hold format, length, captions, planning mode, characters mode and sound mode; the
inspector holds each picture's role and relative size.

## How consistency with the sheet is kept

- **Follow the sheet planning** (`production_planner.follow_the_sheet`): characters in a scene are exactly those the
  beat names by the name the sheet uses ("Gấu mẹ"), one product pack when the beat is about the product (all when it
  says "products"), the logo bookends the film, sounds are the sheet's own cues, and movement is the beat's action
  translated. A rewrite that invents content is rejected for the sheet's own words. A beat with no place stays where
  the film already is. A split screen becomes one full-frame view (the sheet's request is noted as "needs editing").
- **Timing**: scene lengths and positions come from the sheet; the export is exactly the sum (Demo 1: 35.000 s).
- **Translation**: the small planning model often echoes the Vietnamese around its English ("<VI>: <EN>",
  "<VI> translates to …"); only the English is kept (`english_part`), and a translation that is much shorter or longer
  than its source, or names someone or something the source never mentions, is rejected and retried sentence by
  sentence. Sound cues are translated with their scene's action as context ("tiếng cốc đổ" is a glass falling over).
- **Camera**: the sheet's *Visual / Camera* column goes to the video model as a `Camera:` line. Its Vietnamese camera
  terms are read from a fixed glossary (cận cảnh → close-up, toàn cảnh → wide shot, "->" → "to" …); a translation
  missing one of them is replaced by the glossary. When the camera moves, the prompt follows it and the product lock
  stands down for the frames where the pack moved. Voice-over is never sent (the film carries sound effects only).
- **Rewrites**: a rewrite of the action for the video model is kept only if it keeps 80% of the beat's content words,
  adds almost nothing new and does not grow; otherwise the faithful translation is used as it is.
- **The product in a scene**: only when the beat names the brand (a proper noun of the product name) or its packaging
  (pack, box, bịch, hộp, gói, sản phẩm). "Giấy ăn thường" (an ordinary napkin) in a problem scene is a prop, never the
  advertised pack.
- **Prompts**: every video segment carries the cast (named by role, with each character's colours read from the
  picture), "the first frame is the truth for the place, light and objects", no printed words or quantities, no
  appearance similes, and the scene's own sound line. Quantities, placements, zooms and box nouns are removed
  from the movement text where they would make the video model invent or enlarge things.
- **The real product pack**: the pack is always pasted from its cutout (never drawn), so its label and logo are exact.
  With drawn characters it stands on the floor in the lower middle, in front of them, where the prompt keeps the floor
  clear; with no cast it is the large hero. The positions are rules (`keyframes.overlay.layout`), so the same inputs
  give the same frame. A separate logo picture is not pasted on its own: the brand shows on the pack.
- **The pack through the video**: the video model redraws the pack in every frame and warps its print, so the
  keyframe records where the pack was pasted and its exact pixels (`product_lock_json` on the keyframe artifact), the
  prompt keeps the pack still and the camera locked, and the scene's video gets the same pixels laid back over every
  frame (`keyframes.overlay.lock_products_in_video`, applied when a scene's video is assembled).
- **The end card**: the film's last scene, when it shows the product, is laid out by rules instead of drawn: the image
  model draws only the room, the first product stands large in the centre and in front, the others beside and behind
  it, and the characters stand at the sides at their relative sizes.
- **One room per place** (`keyframes/locations.py`): scenes with the same setting text share one picture of that place,
  drawn once, empty, by the keyframe workflow from the text alone. It is added to the project as *Location N* (role
  Environment) and to every scene set there as its Environment reference, so the workflow's Redux environment branch
  draws them all in that room. Redux carries the picture's layout as well as its look (at strengths 0.5, 0.25 and 0.12
  a close-up still came out as the wide room), so a close-up or top-down scene gets *Location N close-up*, a close view
  cut from the same picture (the middle of the room around the table and floor). The first frame also follows the start
  of the sheet's camera direction ("Wide shot to close-up" opens wide).
- **One style**: the first frames drawn together in one run share one seed, so they start from the same noise; a frame
  redrawn on its own gets a new one (a new take).
- **The product as it is** (`prompts.product_identity`): the product name is translated once (brand and quantities
  removed, so nothing is printed) and a scene showing the product says what it is ("The advertised product is luxurious
  tissue paper"); for a paper product, any sheet a character uses is one of its sheets pulled out of the pack, never a
  roll. Scenes that do not show the product (an ordinary napkin in a problem scene) are only told paper is a flat sheet.
- **Who is in a scene**: the characters the beat names by their sheet name; a word for the whole family ("gia đình",
  "cả nhà", "bố mẹ", "family", "everyone") brings in every character named as a family member. A lone role word does
  not ("sợ mẹ mắng", afraid mum will scold, names a mother who is not there).
- **Colours in the video**: a light mascot is described to the video model as "pale and light, never brown or tan", as
  in its first frame's prompt; "beige" alone let H3 drift it to tan fur within a clip. A scene with an Environment picture of its own (a client's photo) keeps it; replacing
  *Location N* in the references changes the room for all its scenes. This is the shared-anchor idea of Story2Board
  and ConsiStory, done with inputs the workflow already has.
- **Family roles** (`planning/roles.py`): a character named as a family member (mẹ/má, bố/ba/cha, ông, bà, anh trai /
  chị gái, con/bé/cháu/nhí, and English mother, dad, grandma, big sister, kid, cub …) is drawn with that role's build and
  posture (a child is about half an adult's height with a rounder body and bigger head; a grandparent slightly stooped
  …), with the instruction to keep exactly the mascot's own face, colours, fur, markings and accessories. The role
  also names the character in prompts ("the mother mascot") and gives a new picture its default relative size.
  Vietnamese "con" counts only after a noun ("gấu con"), not in "con gấu" or "ba con gấu"; "ba" means father only after
  "gấu" or "mascot".
- **Sizes**: the character board and the prompt state how much taller the largest character is; a character's default
  size comes from its role. Mascots are pasted only in *Paste exact art* mode (and on the end card).

## Automatic consistency check

Every new first frame and every new take is checked in the background by the site's vision-language model
(`qwen_vl_base_url` / `qwen_vl_model`, Qwen2.5-VL-7B on port 8002; `services/review/consistency.py`), the
judge-and-redo loop of StoryAgent / MovieAgent-style pipelines. Only questions this model was measured to answer
correctly are asked (Demo 1: 15 of 15 on frames), one picture and one question at a time:

- **First frame:** exactly the scene's number of characters; the scene's described opening action is visible
  (description against shot); a split screen is split into its views; no paper roll for a paper product.
- **Take** (four frames sampled through the clip): no frame shows more characters than the scene has (a close-up of an
  object rightly shows none); the frames together show the scene's described action; no paper roll.

A failing frame is redrawn with a new seed up to twice, a failing take redone once; one still failing shows *Needs
your review* with the reasons on its panel. A person's Draw / Redraw / Redo, or approving the frame, starts the count
again. When the model cannot be reached the scene shows *Not checked automatically* and nothing is blocked.

Not checked automatically, because this model cannot judge it: fine identity (a shade of fur, claws) and comparisons
between two pictures. It called the reference mother "light brown", flipped on claws between identical frames, and
passed the take whose mother turned tan. Identity is held by the prompts (every character keeps its face, colours,
fur, markings, accessories and hands, paws and feet); a stronger judge can be added to the same loop. Colour
statistics were measured too and cannot tell a recoloured mascot (0.36) from a camera move (0.78, 1.33).

## Sound

New projects default to *Sound effects only*. Finishing (queued automatically once every scene has its take) closes
the gaps between scenes so they cut straight into each other, then, in *Sound effects only*, screens every scene's audio
and replaces music or speech with a generated effect layer; in *Separate effects layer* every scene gets one. Only
*Full soundtrack* adds generated music.

H3 makes sound together with the picture from the prompt's `Audio:` line and cannot be told to leave music or voice
out. *Sound effects only* asks for timed, concrete effects ("a soft paper rustle at 0.8 s … silence between the
sounds") with speech and music ruled out. `check_scene_audio` screens each scene's own audio (spectral flatness: noise-like
effects vs tonal music/voice) and, for scenes that fail, generates an effect layer with the server's MMAudio model
(retrying other seeds), mutes the scene's own audio and keeps one layer per scene; scenes whose layer scores
in the borderline band are flagged. The screen is a screen, not proof: listen to the export.

## Regression cases

`bench --site <site> execute joymedia.tests.support.regression_cases.run_all` renders keyframes on the real ComfyUI for a
boxed product in 16:9 with a logo, a real person (face generated on the spot) in 9:16, and a text-only brief, and
checks shape, pasted references, colours and movement text. Run it after any change to the pipeline.

## Known limits

- One clip cannot show a split screen; the scene shows its first view.
- The pack is locked only while it stands still: a scene that has a character pick up or carry the pack would show the
  locked pack in two places, so the prompt forbids it, and the video model may still occasionally move it.
- Comment-driven takes keep the approved first frame, so a comment about the opening look (brightness, layout) needs
  *Redraw* in the frames panel instead.
- Drawn characters approximate the mascot picture; *Paste exact art* is exact but in a fixed pose.
- The mother's PDF artwork itself holds a toilet roll; the prompts make paper a flat sheet, but traces of the roll can
  still show. A character picture without it fixes this at the source.
- H3 can still drift a character within a clip; a drifted take is redone with *Redo* (a new seed). Ending every first
  segment on its approved frame (H3's last-frame input, used for later segments) would lock identity but also undo the
  scene's action at its end, so it is not done.
- Submitting a long scene's later segment over a slow link sometimes fails with a "modified after you have opened it"
  conflict on its attempt; the run retries it, and *Redo* recovers a scene whose retries ran out.
- Video drift varies by seed. A take that drifts can be regenerated (the strip's take picker keeps every take).
- Voice-over is recorded separately and is not generated.

### Automatic visual admission

New runs can freeze `joymedia_generation_quality: {"enabled": true}` into their
snapshot. `services/review/admission.py` reuses the existing scene-contract,
frame-sampling and visual-evidence evaluator. Policy and judge configuration are
immutable run inputs; older runs and selected videos are not retroactively changed.

1. Provider completion starts an asynchronous visual check. Its task stays Running,
   so a rejected still cannot become an image-to-video dependency.
2. Compare observed cast counts with the frozen reference identities. Observe human
   parts positively, then enforce the absence rule in code when no Person role is
   declared. Product-only shots receive the same check as character shots. Printed
   characters do not count. Intended humans require an explicit Person reference.
3. Compare visible reference actors with approved source images for broad identity,
   topology and proportions. Inspect authored support, count, material-source and
   event-order claims using uniform and event-boundary samples. Hidden or malformed
   evidence is uncertain, never a pass. This does not certify logos or fine identity.
4. Save the exact-media/snapshot hashes, observations, model configuration and result
   as a private JSON Generation Artifact. Cancellation and stale attempts are checked
   again after model I/O. Media and report tampering block admission.
5. A witnessed rejection permits at most the existing one automatic retry. QA retries
   use a fresh recorded seed and append only failed authored constraints; they retain
   action, references, duration and workflow. Unavailable or wholly uncertain checks
   stop. Source-frame-hold workflows never retry a deterministic failure by seed.
6. Check the final composition after source replacement and graphics, before output
   selection. A source overlay with implausible placement is a finalization failure;
   it must not trigger a blind provider reroll. Preserve the prior selected video.

Exact source-art coverage, workflow capability validation and human brand/release
approval remain independent gates. A sampled machine pass cannot guarantee every
frame, reconstruct missing 3D support, or automatically solve every physical action.
A failed retry stays held for administrator review; never silently substitute a
static shot for a requested interaction. No new client controls are required.

Upstream research references and inspected commits are pinned in
`deploy/visual-admission-references.lock.json`. Clones are on the large GPU volume.
VBench/VideoPhy checkpoint scores are not claimed: the production path reuses the
existing vision runtime and evidence code. The live counterexample matrix and real
ComfyUI job audit are under `verification/automatic-admission-20261018` in the shared
workspace. These are regression examples, not a calibrated population accuracy rate.

Edit copies also carry project-owned first frames, other control versions and
source-lock patch versions into the new edit, sharing file bytes and retaining
`derived_from`. Cyclic, altered or unrelated-family controls are rejected. Library
references stay shared. Access checks are unchanged; read access to a sibling edit
is not a blanket grant to reuse its project-owned controls.

Calibration boundary: live regression images showed false passes for an unsupported
product and elongated limbs. They must not be advertised as detected physics.
The gate therefore explicitly marks interacting/deforming geometry as unqualified
unless it uses the controlled source-presentation route. Such frames are held before
animation; only witnessed failures get a bounded retry. This conservative routing is
a general safety boundary, not automatic 3D reconstruction or proof that every
candidate has an error. Enabling a stronger judge alone does not qualify geometry.

Qualification does not require a new client workflow: a visually screened but
unqualified frame remains pending in the existing Review Scenes step. Such a
frame cannot be automatically animated by a full pipeline; animation requires
its explicitly approved keyframe task or selected first-frame version. Unqualified
video geometry stays a candidate in scene history, never an automatic replacement.
Legacy advisory checks cannot clear the qualification warning. Source-controlled,
stationary presentations with an explicit source frame can progress automatically
after admission and source-coverage checks. Human brand/release approval is unchanged.

Storyboard actions are stored independently from provider prompts in `Shot.storyboard_action`.
An empty value retains the imported script action, or the generation direction for
an unscripted scene. Explicit changes go through `update_project_shot` and invalidate
the plan approval. Run snapshots freeze the effective `authored_action`; video
admission checks it alongside the execution prompt, including after composition.
A product reveal cannot satisfy an actor interaction merely because its provider
prompt was simplified. These are sampled checks: missing or uncertain action evidence
holds the candidate for review rather than certifying it.

Storyboard source-image approval is labeled as an image choice. A selected moving
take is shown for video review; footage from earlier direction is marked as needing
an update. Explicit action revisions cannot inherit approval from legacy takes that
never froze that action. Model prompts and import text remain available for audit.

For reproducible diagnostic rerenders, `regenerate_scene` accepts an optional
integer `seed`, frozen as `execution_scope_json.video_seed`. Workflow, prompts,
references and runtime must also remain fixed; a seed alone is not a guarantee
of byte-identical GPU output. Ordinary client generation still chooses a fresh
seed. Temporal review removes only windows strictly contained in another window
for the same claim; it retains every sampled frame and contextual window. Failed
reports remain immutable when a new policy/run is tested.

Fixed product locks now fall back to the existing reference-anchored OpenCV tracker
only when fixed coverage fails and immutable patch versions are available. Each
tracked plane must protect every frame, with the tracker's inlier, span, scale and
reprojection checks. A missing or ambiguous track still stops the output. This is
planar artwork preservation, not reconstruction of deforming anatomy or arbitrary
3D surfaces; post-composition visual review remains independent.

`queue_candidate_artwork_repair` reuses completed, action-qualified native inference
without changing the failed run, provider artifact or selected take. The repair
has its own frozen policy, checksummed inputs and private review evidence. It may
retain uncertain geometry as an **unselected** review candidate when every action
and cast claim is supported and no violation was witnessed. Uncertain/missing action
or cast evidence, a witnessed violation, changed direction, stale selection or
cancellation blocks publication. Selection uses the existing explicit take-review
operation; this never grants release or brand approval. This distinction preserves
machine uncertainty rather than rewriting a held report as a pass.

Moving closing shots preserve their authored performance. A two-second readable
hold freezes the accepted, source-protected generated pose after the action;
it must not replace the entire shot or return to the opening pose. Only an
explicit static presentation uses source artwork for the whole closing shot.
Candidate artwork repairs apply the same closing hold before their visual check.
Exports have no implicit fade; `ending_fade_seconds` explicitly requests one.

Protected artwork declares its coordinate space. Physical product planes remain
in world space and require complete source coverage. Authored typography may be
screen space and stays fixed across all frames; it cannot satisfy physical product
coverage. Both use immutable patch versions. Sampling uses actual stream frame
counts when available, avoiding nonexistent EOF samples caused by rounded MP4
durations. Semantic action/cast checks, source coverage and geometry qualification
remain separate; none of these changes grants automatic brand approval.

The task identity lookup has a composite index on run, shot, segment and pipeline
step. Its locking read must use that index rather than scanning and locking other
projects' live generation tasks. The idempotent migration is
`index_generation_task_identity`.
