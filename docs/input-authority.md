# Input authority and delivery geometry

Creative inputs belong to the brief/workbook and selected references. Runtime
code must not replace their format, subject, product, setting, cast, chronology
or music with a case recipe. Sampling, model selection and node parameters belong
to immutable workflow JSON records. UI preset buttons are explicit choices.

Delivery precedence is an explicit format override, the selected workbook's
Format field, then an explicit ratio in a text brief. An explicit time unit in a brief supplies duration; missing duration is left unset instead of becoming a 15-second input. Missing format remains
unset and blocks generation readiness. Platform names alone do not choose a
shape. Existing projects retain their stored geometry. A preset is an orientation
label, not a replacement for an authored 4:5 or 21:9 ratio.

`services/project/formats.py` parses ratios and derives even delivery dimensions.
Changing quality preserves that ratio. Planning receives the exact reduced
ratio. Reference boards, location generation, audio and finishing consume project
or frozen-run dimensions; missing geometry fails with an actionable error.
The studio preview and storyboard tiles use those dimensions, including squares.

Providers may align native inference dimensions to their declared latent grid.
The opt-in H3 base profile uses the existing `round_to_multiple` transform instead
of snapping every request to one of three shapes. Model grid alignment is not
permission to change the final delivery ratio. The delivery transform derives
both axes from project geometry and a declared short-edge quality target. Legacy
fixed width/height profiles also preserve the project's aspect at runtime.

Camera policy consumes semantic shot structure, identity/setting references,
actual opening coverage and authored continuity. It never cycles crops by scene
number. Both workbook and creative planning receive the preceding coverage,
matching-action/axis rules and motivated size progression. Authored contact
coverage remains readable and static where a move would obscure contact. A
repeated size can be deliberate; variation is not an absolute alternating rule.
No planner default forces a different location, an extra actor or a hidden-cut
move merely because another take follows. An unrequested piano/string score is
not substituted for missing music instructions.

Camera references: `Quy tac sap xep hinh trong dung phim.docx`, the supplied
`videos/TVC_HOODIE_GYM_NYC_25S_2K_QHD_MASTER.mp4`, and
[Brands Vietnam's shot/angle guide](https://www.brandsvietnam.com/congdong/topic/338390-16-goc-quay-pho-bien-de-xay-dung-mot-storyboard-hap-dan).
The DOCX distinguishes step-size progression, deliberate jumps, pacing,
180-degree continuity and cuts matched to action. These guide decisions; a prompt
alone does not verify generated movement or packaging accuracy.

The Studio upscaling/interpolation graph is declared in
`workflow_adapters/graphs/studio_finish.json`; its model names, multiplier,
selection stride, timing and encoding settings are no longer a Python graph.
Register it with `bench --site SITE execute joymedia.patches.register_studio_finishing.execute`
and explicitly configure `joymedia_workflows.finishing` to that immutable version.
This graph's declared source-frame-rate contract is validated before execution.
It uses existing installed nodes/models and the generic workflow binder.

The audit covered intake/settings, workbook and creative planning, shared camera
and H3 serialization, reference/keyframe preparation, native execution bindings,
audio timing, finishing/export and browser framing. Historical recipes and
migration records remain historical data, rather than active input overrides.
Schema enums, validation limits, transport retry budgets and explicitly selected
quality tiers remain ordinary application rules; they are not creative inputs.

Optional workbook columns **Shot framing**, **Shot angle** and **Narrative stage**
accept the shared shot-grammar enums. Blank keeps normal inference. An authored
value is validated and takes priority over inferred coverage; movement is still
derived by shared policy. Schema-repair retries retain the original visual,
reference, timing and continuity context, avoiding an example becoming the shot.
