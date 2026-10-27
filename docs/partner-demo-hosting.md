# Partner demo hosting: always-available portal, queued GPU work

## Decision

Keep the Frappe website, MariaDB, Redis, scheduler, and lightweight workers on an always-on VM. Keep the planner, vision model, and ComfyUI on the existing GPU machine. Partners may log in and create projects at any time. After the release gate below is implemented, generation requests can wait until the GPU is online. Publish the portal through a stable HTTPS `ts.net` address using Tailscale Funnel, so a purchased domain is optional.

An Oracle Cloud Always Free Ampere A1 VM (2 OCPU, 12 GiB RAM, within the 200 GiB block-volume allowance) is a possible no-recurring-fee portal host, subject to account eligibility, regional capacity, and idle-instance reclamation. It has no suitable GPU for the JoyMedia models. Verify the ARM build and runtime dependencies on a fresh VM before migrating data. The current development site stores multiple GiB of private media, so measure actual database and asset size before choosing a volume and keep a tested off-VM backup.

## Existing access control

Create a separate Frappe Website User for each partner, then grant `Partner Access` as an administrator at `/app/partner-access`. Enable **Allow End-to-End Testing** and set small limits for **Maximum Test Projects**, **Maximum Render Attempts**, **Maximum Video Duration**, and **Maximum Pixels per Frame**. The `JoyMedia Reviewer` role gives the partner their own creation workspace without access to other projects or workflow administration. The server enforces project count and dimensions on `Media Project` validation and charges each `Generation Attempt`, including retries, under a database lock. Do not share an administrator login.

## Deployment prerequisites

1. An Oracle Cloud account with an available A1 instance, or another persistent VM. No cloud account or VM is configured in this repository.
2. A Tailscale account for a stable `ts.net` Funnel address. Funnel is public; Frappe login and per-user grants remain mandatory.
3. Persistent MariaDB, Redis, site files and private media on the VM, with off-VM backups and HTTPS-only public access. Do not expose MariaDB, Redis, ComfyUI, or the planner to the public internet.
4. A secure VM-to-GPU connection for the existing planner, vision, and ComfyUI endpoints. The current development `Procfile` expects local SSH-forwarded GPU ports; moving the site requires replacing that host-specific tunnel configuration.

## Readiness check (25 October 2026)

- The development portal returned HTTP 200 at `/joymedia`; ComfyUI's local health endpoint also returned HTTP 200.
- `bench doctor` found four workers online. The 11 partner-access and quota tests passed.
- The site currently holds approximately 6.3 GiB of private files. A migration needs persistent storage and a verified backup/restore, not just a frontend upload.
- No Oracle Cloud account, always-on VM, or Tailscale installation is available in this workspace. The only configured SSH route is to the GPU host, which is not an always-on portal host.
- The disconnected-GPU acceptance test below has not passed. Partner generation must remain disabled on any public deployment until it does.
- Initial partner-batch admission now checks planner, vision, and ComfyUI health. Three targeted tests pass and the live configured endpoints returned healthy JSON. A full creative-suite run still has unrelated existing screenplay and review-state failures, so this is not a complete release signal.

## Release gate

Partner batch admission now probes the configured planner, vision model, and ComfyUI before enqueueing initial work. When any is offline, a new partner batch remains queued, and the scheduler skips it until the services return. This covers an offline GPU **at submission time**. It does not yet prove that every long-running script, pose/product-view, first-frame, video, audio, and retry job survives the GPU disappearing mid-run; an interrupted job can still end in `Needs Attention`. Test and repair that full cycle **before** opening partner generation on the public portal. During the first deployment, leave `allow_generation` off until this gate passes. The portal may still serve published videos and accept feedback.

Acceptance test: with the GPU disconnected, a partner creates a project and requests one short video. The project and request persist, show a waiting state, consume no model attempts, and create no failed variant. After reconnecting the GPU, the scheduler resumes the same request exactly once; a completed output is visible only to its owner and the recorded attempt count stays inside the grant. Reboot the web VM during the waiting state and repeat. Test revocation and quota exhaustion while a request is waiting.

## Limits

This design makes the **website** reachable while the VM is running. It does not make generation immediate or free: the GPU must be online, and transfer/storage/compute costs may apply outside free allowances. Oracle Free capacity and reclamation mean it cannot be promised as a production-grade 24/7 SLA. A paid VM and on-demand GPU are the upgrade path if partners later require predictable availability and start times.
