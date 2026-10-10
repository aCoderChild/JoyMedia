# Generic ComfyUI workflow contract

Use `adapter_key: "comfyui_generic"` on a Generation Workflow for ordinary
ComfyUI API-format graphs. The graph and this specification are immutable parts
of a workflow revision. New model families should normally need a new workflow
record (and the appropriate installed ComfyUI nodes/models), not a Python
adapter or backend deployment.

JoyMedia inputs such as the prompt, first frame, product/person/environment
references, and other files are mapped separately through the workflow's
`bindings` child table. Use the exact ComfyUI node key and input name for each
binding. This permits distinct reference roles and optional inputs without
model-specific backend code.

`execution_spec` declares runtime values and output semantics. For example:

```json
{
  "parameters": [
    {"semantic": "seed", "node_key": "12", "input_name": "seed"},
    {"semantic": "width", "node_key": "18", "input_name": "width"},
    {"semantic": "height", "node_key": "18", "input_name": "height"},
    {"semantic": "frame_count", "node_key": "24", "input_name": "length"},
    {"semantic": "output_prefix", "node_key": "31", "input_name": "filename_prefix"}
  ],
  "metadata": {
    "frame_count": 121,
    "output_fps": 24,
    "produces_video": 1,
    "produces_audio": 0
  },
  "outputs": {
    "primary": {"node_key": "31", "media_type": "Video"}
  }
}
```

Supported parameter semantics are `seed`, `width`, `height`, `aspect_ratio`,
`frame_count`, `fps`, `output_prefix`, `last_frame_prefix`, and
`last_frame_index`. Mappings use `identity` by default; `frames_to_seconds`
converts requested frame count to seconds (optionally set a fixed `fps` and
`minimum`); `aspect_ratio_option` chooses the closest declared dropdown option,
where `options` maps ComfyUI option labels to numeric width/height ratios.
`nearest_size_dimension` selects a width or height from a declared list of
dimension pairs, choosing the pair closest to the requested delivery ratio.
Each mapping is checked against the actual node input in the stored graph.

For workflows that accept several images in one semantic role,
`input_preprocessing.compose_image_roles` requests deterministic image-board
composition before upload. `scalarize_single_path_roles` tells the adapter that
a one-file list for that role should be supplied to its ComfyUI node as a single
path. For a declared `File Paths` binding with `allow_multiple` disabled,
scalarization is automatic; workflow authors should use this legacy option only
for older records that do not declare binding cardinality. Optional graph branches can be expressed with `conditional_inputs`, for
example selecting a reference-encoded latent when a role has inputs and an empty
latent otherwise:

```json
{
  "input_preprocessing": {
    "compose_image_roles": ["keyframe_reference"],
    "scalarize_single_path_roles": ["keyframe_reference"]
  },
  "conditional_inputs": [{
    "role": "keyframe_reference",
    "target": {"node_key": "sampler", "input_name": "latent_image"},
    "when_present": ["reference_latent", 0],
    "when_absent": ["empty_latent", 0]
  }]
}
```

`prompt_transforms` can apply declared regular-expression removals and append
fixed or staged guidance to a bound text input. These are workflow-record
configuration, not provider-specific branches in orchestration code.

`outputs.primary` is required and identifies the output node and media type
(`Image`, `Video`, or `Audio`). For video, JoyMedia extracts
and stores a last frame for continuation unless `outputs.last_frame.node_key`
declares a dedicated image output. Output declarations and parameter mappings
are validated when a workflow record is saved and again before execution.

The workflow graph and execution specification have separate SHA-256 hashes;
each attempt also stores the resolved graph hash after JoyMedia injects its
runtime inputs. This keeps the model-specific node wiring explicit and
reproducible while leaving orchestration and artifact handling model-agnostic.

The generic adapter does not make arbitrary ComfyUI graphs interchangeable:
the graph still must be valid in the target ComfyUI installation, and its
custom nodes, weights, and any authentication must be installed/configured
there. The record describes how JoyMedia talks to that graph; ComfyUI executes
the actual model.
