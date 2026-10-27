# Automatic pose preparation and bridge pipeline

JoyMedia plans every shot before sending any image task. After the Director
returns its complete scene list, `pose_assets.prepare_script_pose_views` asks the
existing planner for one opening body state per character per scene. This finite
list comes from the whole script, including scene-to-scene continuity, rather
than a fixed set of standing/seated keywords. In normal production, the Director
must select a qualified Character view as each shot's opening-pose contract: a
stand-up starts from a qualified seated view, while an already-upright action
starts from a qualified standing or side view. The service reuses that exact
asset before it considers generating anything new. The supplied image anchors
identity, but an unqualified source photo is not treated as proof of a new pose.
Where the qualified library lacks a required state, it uses
the already installed MiniMax H3 image-to-video workflow as a short character-only
pose bridge and samples its held final frames. An explicitly configured
`joymedia_pose_workflow` still selects the separate image pose workflow. Each
generated view is a separate Asset Version linked to its source identity.

Qualification provenance (`source_asset_version`, reviewed pose/support and
view) is stored separately from the ordinary intake caption. Re-analysis can
refresh its caption without erasing the fact that the asset passed the pose,
support, prop and identity checks. New variants copy these qualified views of
the selected identity into Media → Character before the Director writes its
story, so a later project can use the existing standing, raised-paw or side
view instead of attempting to redraw it.

A prop held in a reference image is not character anatomy. The pose service
checks the chosen source for held objects and prefers a clean view of the same
identity. It first describes a candidate's pose without showing the requested
pose to the vision model, then compares that observation with the requirement.
This prevents a requested kneeling pose from being accepted merely because the
model repeated the prompt over a seated image. It checks each generated pose's physical support, held-object
count, and identity against the clean source separately. Uncertain or unavailable vision evidence does not promote
a generated pose to a persistent reference. The original uploaded art is never
overwritten. A failed pose preparation is recorded as deferred. The batch saves
the text storyboard but holds first-frame submission if any required character
view remains unqualified; a seated reference is not silently used as evidence
for a different action pose.

When creating a variant from selected original references, the batch also
copies already qualified Character views from the source project if their
recorded source asset and identity match the selected character. This lets a
new Shera video reuse previously accepted prop-free views even if the client
selects only the original mascot photo. It does not make an unsupported new
pose reliable; an unresolved state still holds the image stage for review.

The H3 bridge starts from a clean image of the same identity. When a qualified
view already exists, the planner selects the closest body pose as its starting
frame. An admitted still is saved in Media → Character as a generated Asset
Version, with its source and pose in analysis metadata, and linked to the
project. The short bridge clip is not used as a finished shot.

Pose recovery is bounded and automatic. H3 tries two seeded bridge clips and
checks several late frames in each clip. If a required view still fails, the
service prepares the remaining script states first. When one of those states
adds a qualified view, it makes one more pass for the deferred states, now
allowing H3 to start from that accepted view. Only frames that pass pose,
support, prop, silhouette, and identity checks are added to Media → Character.
Unresolved states remain deferred for shot-level review; the service does not
silently relabel a wrong pose or retry without a bound. This is a recovery
strategy, not a measured guarantee of success for arbitrary characters.
Within each H3 request, the second seeded attempt now uses another already
qualified starting view when available. A live Shera side-profile/raised-paw
combination failed the earlier fixed-start route and produced a candidate with
the alternate start. Visual inspection found its lower body fused into one
stump despite the broad reviewer accepting it. A separate lower-body observation
now rejects that candidate; the three earlier qualified Shera views still pass
the revised review in a live comparison. The candidate stayed in `/tmp` and was
not added to Character media. This test exposed a false acceptance in the old
reviewer and does not establish a general success rate. The vision result also
changed with question wording, so unresolved or contradictory cases must stay
deferred rather than being described as verified.

## Shera six-pose stress test (25 October 2026)

Using the same clean Shera identity from PRJ-02673, the H3 bridge attempted six
new pose descriptions. Each target could use two clips and three late-frame
samples per clip. The test saved candidates only under
`/tmp/joymedia-pose-matrix-20261025/`; it created no new Media → Character
assets. The local vision endpoint briefly disconnected midway through the
first batch. After it responded again, the three interrupted targets were
rerun, so all six targets received a generation attempt.

| Target | Automatic result | Visual inspection |
| --- | --- | --- |
| Standing rear view | Deferred, 6/6 candidates rejected | At least one frame retained Shera's broad body, flower and two grounded feet; a brown or enlarged tail appeared in another. A plausible frame was rejected because the reviewer called its stylized lower body fused. |
| Side reach | Deferred, 6/6 rejected; one review request hit the temporary endpoint outage | Rounded identity largely retained; the paw stayed close to the chest instead of extending forward, and feet were weak or merged. |
| High front wave | Deferred, 6/6 rejected | At least one frame showed a clear raised paw and recognizable Shera face, flower and body. This is a likely false rejection. |
| Walking step | Deferred, 6/6 rejected | Side profile persisted, but a distinct weight-bearing step and separate feet did not. |
| Low crouch on both feet | **Qualified** at first candidate | **False acceptance:** the bear sat back on its rump with torso pitched forward, contrary to the requested upright, foot-supported crouch. The independent vision description also said “sitting on its rump”; a target-worded question answered true and overrode it. |
| Kneeling on both knees | Deferred, 6/6 rejected | Shera remained a rounded standing/squat shape; knees and shin support were not visible. |

The recognizable mascot traits often persisted, but the requested support and
limb action did not reliably persist. The automatic qualification count (1/6)
overstates real success: the one accepted image was physically wrong. The test
also demonstrated a likely false rejection. This route is therefore **not
qualified as a robust arbitrary-pose generator or reviewer**. A scene requiring
an unsupported state must remain deferred, and the current target-worded
review fallback needs replacement or calibration before this step can certify
unattended production poses. The earlier three successful Shera poses remain a
narrow pilot result, not a general success rate.

The reusable view contains body pose and support only. Product contact, grip,
location, and background are composed and checked in each scene's storyboard
frame; preparing a body view does not prove those contacts will be correct.

After the individual production plans are written, `pose_coverage.annotate_shots` adds a
`pose_requirement` to each shot's existing motion plan. It derives the target
opening pose from the action and the planner's `subject_motion`, then compares
that target with `pose_and_support` from the selected character images.

An upright travel shot whose available view is seated is marked
`requires_bridge_keyframe`. The keyframe prompt then requires visible support,
feet and body clearance. The generated opening image is a bridge keyframe: it
is conditioned on the source identity but has its own immutable output and
review record. It does not overwrite or become a customer-uploaded reference.

The current `flux2_klein_h3_i2v` route creates one reference-conditioned
opening keyframe per shot and supplies that keyframe to MiniMax H3. This adds
the missing explicit pose contract to that route. A normal keyframe may satisfy
the contract, but a rejected image must redraw or lead the writer to choose a
reachable seated/product-only alternative; H3 must never be asked to create a
seated-to-standing transition from an unsupported opening frame.

The upstream [CharacterPose](https://github.com/Spit8/_ComfyUI_CharacterPose)
workflow informed the reference-to-pose-library stage. Its nodes target 2D
sprites, so this 3D mascot pipeline did not install those nodes on the GPU server.
Its reference-to-pose-library pattern remains useful. A live Shera smoke test
showed a generated side pose without the source image's pink heart. This test
does not establish that Klein can reliably compose the new pose into a room:
earlier combined-scene tests still intersected the bear with a table. The
scene-frame audit and bounded retry remain necessary.

On Shera PRJ-02673, a read-only live planner check distinguished a seated
stand-up opening from a subsequent standing side-view walk. A real Klein 4B
request for a kneeling pose rendered a seated figure; the independent observed
pose check rejected it for reuse. A raised-paw standing request also failed the
two-attempt pose and identity review. These results show that planning a pose
does not guarantee the current image model can draw it. Such a state remains
deferred for per-shot rendering and review rather than being mislabeled ready.

## Klein 4B RefControl pose pilot (24 October 2026)

The upstream [4B pose LoRA](https://huggingface.co/xocialize/refcontrol-FLUX.2-klein-4B-pose-lora)
is installed in the GPU model store as `refcontrol-pose-klein-4b.safetensors`.
`register_refcontrol_pose_pipeline.register_image()` registered workflow
`flux2_klein_4b_refcontrol_pose_keyframe` as an opt-in image workflow. Its first
reference is a COCO-18 pose guide, and its second is the clean character
identity. The guide is planned from the required shot pose and rendered by the
vendored MIT-licensed [CharacterPose](https://github.com/Spit8/_ComfyUI_CharacterPose)
OpenPose drawing code. Production uses it only if the operator explicitly sets
`joymedia_pose_workflow` to the registered workflow name; registering and
installing the checkpoint do not change the active Klein-to-H3 pipeline.

The real Shera standing, raised-paw and kneeling pilot generated three images.
All three humanized Shera's originally round silhouette into a long-limbed,
narrow-bodied bear. The raised-paw image also left both paws down, and the
kneeling image remained standing. The pose workflow is therefore **not enabled**
for automatic jobs. The independent pose review rejects the incorrect actions.
The identity review now includes an OpenCV foreground-aspect guard for studio
pose views, because the VLM alone falsely accepted the distorted standing
silhouette. The guard rejects all three pilot images while preserving a
separate comparison of face, color and accessories. A correct pose for this
mascot still needs a better identity-preserving control method or a qualified
source rig; the failed pilot must not be presented as a solved bridge.

## H3 pose-bridge pilot (24 October 2026)

The installed MiniMax H3 image-to-video workflow was tested on the clean Shera
reference without adding a model. Its held final frames produced squat standing,
side-profile and raised-paw views with the recognizable face, flower, cream
material, broad rounded torso and short feet. The pose service now uses this
workflow by default for missing reusable views. The failed Klein human-skeleton
LoRA remains disabled. In a Shera stage test, qualified standing and raised-paw
views were automatically added to Media → Character. A side attempt from the
seated source was deferred; after the service chose the accepted standing view
as its next starting frame, a rerun produced the side view too. The three
qualified assets in PRJ-02673 are ASTV-06034 (standing), ASTV-06035 (raised
paw) and ASTV-06036 (side).

The local vision reviewer can contradict itself about a squat mascot's floor
contact. A narrow target-pose question supplements independent observation;
silhouette, identity, prop and support checks still apply. The service does not
promote an unqualified frame. This improves the tested Shera states but does
not certify every possible pose or action. The alternative
[ComfyUI Qwen Image Edit workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2509.json)
was downloaded and inspected. It would add roughly 30 GB of models; the model
download hit the guest container's writable limit despite host free space, so
trial model files were removed. The H3 route reuses the installed ComfyUI
workflow and model files; no extra production model was installed.
