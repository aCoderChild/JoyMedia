# GPU storage

The GPU host has a nearly full 134 GB root filesystem and a 3.5 TB volume
mounted at `/var/lib/kubelet`. The volume is **not** extra capacity: root
(`persist-rootfs/<container>/fs`) and `/var/lib/kubelet`
(`persist-rootfs/<container>/sysbox-kubelet`) are sibling folders of one
per-container storage allowance on the provider's host. When that allowance is
used up, writes fail with `ENOSPC` on both paths even though `df` shows free
space on the volume, and ComfyUI uploads return HTTP 500. More capacity needs the
provider to raise the allowance or attach a volume outside `persist-rootfs`. Keep downloaded weights, repository clones,
model caches and generated media under the application-owned directory
`/var/lib/kubelet/joymedia-model-store`. Do not write to other kubelet directories.

Use these destinations on this host:

| Content | Destination |
| --- | --- |
| Model weights | `/var/lib/kubelet/joymedia-model-store/<ComfyUI model category>/` |
| Repository clones | `/var/lib/kubelet/joymedia-model-store/runtime/repositories/` |
| Downloads | `/var/lib/kubelet/joymedia-model-store/runtime/downloads/` |
| Model and compiler caches | `/var/lib/kubelet/joymedia-model-store/runtime/cache/` |
| Temporary files | `/var/lib/kubelet/joymedia-model-store/runtime/scratch/` |
| ComfyUI inputs, outputs, temporary media | `/var/lib/kubelet/joymedia-model-store/runtime/{input,output,temp}/` |

Before downloading, verify `findmnt -T <destination>` and `df -h <destination>`.
Use an explicit destination/cache directory; download a `.download` file on that
same volume, verify its pinned upstream checksum, then rename it atomically.
Link weights into ComfyUI's model directory rather than copying them to root.
Clone repositories directly into the repositories directory, pin the revision,
and inspect the license before enabling runtime code. A newly created directory
on the root filesystem is not a substitute for a mounted large volume.

To migrate existing media, stop admission and wait until `/queue` is empty, stop
ComfyUI, then run as its service account:

```sh
python3 deploy/gpu-storage.py \
  --comfy-root /home/ubuntu/ComfyUI \
  --storage-root /var/lib/kubelet/joymedia-model-store/runtime
```

The helper refuses the root filesystem, checks available space, verifies copied
file sizes and SHA-256 digests, and preserves existing paths with symlinks. It
refuses to overwrite a different existing destination. Restart ComfyUI only after
inspection. Do not run migration while jobs are active.

The current host uses a persistent systemd drop-in at
`/etc/systemd/system/joymedia-comfyui.service.d/storage.conf` to set `TMPDIR`,
`XDG_CACHE_HOME`, `HF_HOME`, `HF_HUB_CACHE`, `TORCH_HOME`,
`TORCHINDUCTOR_CACHE_DIR`, `TRITON_CACHE_DIR`, and `CUDA_CACHE_PATH` under the
large volume. Its service stdout/stderr also go to `runtime/comfyui.log`.
Service environment changes need a daemon reload and restart; changing an
interactive shell alone does not affect systemd. Other model services require
their own explicit cache settings before downloading new models.

On 2026-10-18 the missing FLUX.2 VAE was restored on the large volume with its
pinned SHA-256 verified. The media migration verified 1,478 input files and 432
output files, preserving URLs. This relocation does not clear unrelated files
from the full root filesystem.

`deploy/install-comfy-extension.sh` requires `JOYMEDIA_STORAGE_ROOT`. It refuses
root-disk storage before cloning, keeps repositories and installation caches on
the mounted volume, and links the node into `custom_nodes`. Example:

```sh
export JOYMEDIA_STORAGE_ROOT=/var/lib/kubelet/joymedia-model-store
bash deploy/install-comfy-extension.sh <comfy-root> <python> <repo-url> <commit> <name>
```

## Keeping the allowance free (22 October 2026)

The allowance filled on 2026-10-22 and stopped all renders. Recovery:

- Removed ComfyUI per-attempt copies older than two days (`input/joymedia_*`,
  top-level `output/TASK-*_ATT-*`). JoyMedia uploads fresh inputs for every
  attempt and stores results in Frappe. Hand-placed inputs and the output
  subfolders (places, references, music) are kept.
- `joymedia-runtime-retention.timer` (`deploy/runtime-retention.{sh,service,timer}`,
  installed by `install-gpu-services.sh`) repeats that hourly; set
  `JOYMEDIA_RETENTION_DAYS` to change the window. Log:
  `runtime/retention.log`.
- Identical CUDA/Python libraries in `comfy_env` and `venvs/joymedia-qwen` were
  replaced by hard links (2.5 GB). Reinstalling either environment simply
  writes new files.
- Retired `flux_pulid_keyframe`: its Flux1/T5/CLIP-L weights had already been
  moved off the host, and no active pipeline or project uses it. Its helper models
  (PuLID, SigCLIP, Redux, InsightFace, both EVA-CLIP cache copies) and the unused
  `OmniGen` and `tvc_shera_project` folders were moved to the application
  server under `model-backups/gpu-inactive-pulid-20261022` and
  `model-backups/gpu-leftovers-20261022`, checksum-verified. Copy them back to
  the same paths before re-enabling that workflow.

VBench under `runtime/repositories` is used by visual admission and
`~/.cache/vllm` by the running model server; keep both. Nearly all remaining
space is weights that active pipelines load (H3 Ref2VA and FL2VA, their text
encoder and VAE, Flux.2 Klein, the planner and vision models, MMAudio), so the
retention timer prevents growth but does not create room for new models.
