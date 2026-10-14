# Sheet → storyboard → keyframes → H3 video

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
deliberate: it writes `joymedia_active_generation_pipeline` to `site_config.json`. A project pins the workflow version it
was saved with, so after promoting a new pipeline open the project's video settings and save them again.
Rollback = promote the previous pipeline name; existing runs keep their snapshot.

Also set `scheduler_tick_interval` to 60 in `common_site_config.json`, otherwise finished renders are noticed only every
four minutes and the GPU idles (the readiness list warns about it).

Every tunable number (layout fractions, audio screen thresholds, keyframe anchoring) is in `services/project/tuning.py`.
A site overrides any of them in `site_config.json` under `joymedia_tuning`, for example
`{"character_height": 0.45, "anchor_continuation_to_keyframe": false}`.

## What the client provides

Required: **a story**, either an `.xlsx` storyboard workbook (pick one demo/sheet in it) or a written brief.
Everything else is read or defaulted:

| Input | Required | What happens with it |
|---|---|---|
| Storyboard `.xlsx` | one of workbook / brief | Scenes, timings, camera, action, voice-over, sounds, on-screen text; format and length from the sheet's own metadata |
| Written brief | one of workbook / brief | The planner writes the scenes (Creative mode) |
| Pictures: characters (mascots), a real person's photo, products, logo, places | optional but strongly advised | Each picture gets a role (guessed from its name or page text, editable): Character, Person, Product, Logo, Environment. A PDF can be uploaded whole: its usable pictures are extracted (`add_pdf_images_to_project`) |
| Relative size per character/product | optional (default 1) | 0.4 = a child beside a parent |
| Format (9:16 / 16:9 / 1:1), length | optional | Taken from the sheet; editable in project settings |
| Planning: Follow the sheet / Creative | default follows the input | Follow the sheet keeps the advertiser's scenes, characters and sounds and only translates |
| Characters: Draw in scene / Paste exact art | default Draw | Draw: characters act naturally like people. Paste: the real mascot picture is placed unchanged |
| Sound: Full / Sound effects only / Separate effects layer | default Full | See Sound |

Transparent pictures (PNG with an alpha channel) can be pasted exactly; opaque photos can only guide the image model.
A real person's face goes in as **Person** (identity-locked, not a style reference); a mascot or cartoon goes in as
**Character**. With no pictures at all, FLUX draws everything from the text.

## Stages and where to see them (Frappe UI, `/joymedia/projects/<name>`)

1. **Intake** — "New project" dialog: upload workbook and pictures, choose the demo. The readiness checklist
   ("Before you generate") lists what is still missing, in the studio's language.
2. **Storyboard** — scene strip under the preview: every scene with its timing, copy, status, takes and review badge.
   *Plan scenes with AI* writes the prompts (progress streams live). *Approve storyboard* locks the plan; any
   edit to a scene returns it to review.
3. **Storyboard frames** — "Draw all frames" renders the first frame of each scene (about a minute each). Approve,
   Redraw or Undo per scene. A frame drawn for different inputs than the scene now has is marked *Out of date*.
4. **Videos** — *Generate*/*Regenerate this scene*: each scene renders from its approved frame. Long scenes
   (more than 5.16 s, the H3 limit of 124 frames) are chained segments; each later segment ends on the approved frame
   so the characters do not drift away from it. Takes 1/2/3 of a scene can be stepped through.
5. **Review** — per scene: Approve / Request changes with notes (QA panel in the inspector).
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
- **Prompts**: every video segment carries the cast (named by role, with each character's colours read from the
  picture), "the first frame is the truth for the place, light and objects", no printed words or quantities, no
  appearance similes, and the scene's own sound line. Quantities, placements, zooms and box nouns are removed
  from the movement text where they would make the video model invent or enlarge things.
- **Pasted art**: logos and products are placed at their exact aspect ratio on a floor corner the prompt keeps clear
  (drawn-character scenes) or as a hero (no cast). Mascots are pasted only in *Paste exact art* mode.

## Sound

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
- The video model redraws small print: label text on a pack becomes soft texture and may be wrong while it moves.
- Drawn characters approximate the mascot picture; *Paste exact art* is exact but in a fixed pose.
- The mother's PDF artwork itself holds a toilet roll; it appears in her scenes.
- Video drift varies by seed. A take that drifts can be regenerated (the strip's take picker keeps every take).
- Voice-over is recorded separately and is not generated.
