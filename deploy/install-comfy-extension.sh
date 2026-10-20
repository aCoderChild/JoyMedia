#!/usr/bin/env bash
# Install one revision-pinned ComfyUI custom-node repository reproducibly.
#
# This intentionally does not restart ComfyUI: the host operator chooses the
# service manager and can inspect the installed source before activating it.
set -euo pipefail

usage() {
	cat >&2 <<'EOF'
Usage (set JOYMEDIA_STORAGE_ROOT to a directory on the large mounted volume):
  install-comfy-extension.sh <comfyui-dir> <python-bin> <repository-url> <commit-sha> <directory-name>

Example (MV-Adapter):
  install-comfy-extension.sh /home/ubuntu/ComfyUI /home/ubuntu/comfy_env/bin/python \
    https://github.com/huanngzh/ComfyUI-MVAdapter.git \
    9d6d8afeff135d81a31f16dde5291d8b40dbb0a4 ComfyUI-MVAdapter
EOF
	exit 2
}

[ "$#" -eq 5 ] || usage

comfyui_dir="$1"
python_bin="$2"
repository_url="$3"
revision="$4"
directory_name="$5"

case "$directory_name" in
	""|.|..|*[!A-Za-z0-9._-]*)
		echo "directory-name may contain only letters, numbers, dot, underscore, and hyphen" >&2
		exit 2
		;;
esac

[ -d "$comfyui_dir/custom_nodes" ] || {
	echo "Not a ComfyUI directory (missing custom_nodes): $comfyui_dir" >&2
	exit 2
}
[ -x "$python_bin" ] || {
	echo "Python executable not found: $python_bin" >&2
	exit 2
}
command -v git >/dev/null || {
	echo "git is required" >&2
	exit 2
}

# Never let git, pip caches, or model dependencies fill the OS disk.
: "${JOYMEDIA_STORAGE_ROOT:?Set JOYMEDIA_STORAGE_ROOT to the application directory on the large mounted volume}"
"$python_bin" - "$JOYMEDIA_STORAGE_ROOT" <<'PY_STORAGE'
import pathlib, shutil, sys
root = pathlib.Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
if root.stat().st_dev == pathlib.Path('/').stat().st_dev:
    raise SystemExit('Repository storage must be on a separate mounted volume.')
if shutil.disk_usage(root).free < 64 * 1024**3:
    raise SystemExit('Repository storage needs at least 64 GiB free.')
PY_STORAGE
storage_root="$(cd -- "$JOYMEDIA_STORAGE_ROOT" && pwd -P)"
export TMPDIR="$storage_root/runtime/scratch"
export XDG_CACHE_HOME="$storage_root/runtime/cache"
export PIP_CACHE_DIR="$XDG_CACHE_HOME/pip"
export HF_HOME="$XDG_CACHE_HOME/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export TORCH_HOME="$XDG_CACHE_HOME/torch"
mkdir -p "$storage_root/runtime/repositories" "$TMPDIR" "$PIP_CACHE_DIR" "$HF_HUB_CACHE" "$TORCH_HOME"
target_dir="$storage_root/runtime/repositories/$directory_name"
node_link="$comfyui_dir/custom_nodes/$directory_name"
if [ -e "$node_link" ] || [ -L "$node_link" ]; then
    if [ ! -L "$node_link" ] || [ "$(readlink -f -- "$node_link")" != "$target_dir" ]; then
        echo "Refusing to replace existing custom node path: $node_link. Move it to mounted storage first." >&2
        exit 2
    fi
fi
if [ -e "$target_dir" ] && [ ! -d "$target_dir/.git" ]; then
	echo "Refusing to replace non-git path: $target_dir" >&2
	exit 2
fi

if [ ! -e "$target_dir" ]; then
	git clone --no-checkout "$repository_url" "$target_dir"
else
	configured_url="$(git -C "$target_dir" remote get-url origin)"
	if [ "$configured_url" != "$repository_url" ]; then
		echo "Refusing to reuse $target_dir: origin differs from the requested repository" >&2
		exit 2
	fi
fi

git -C "$target_dir" fetch --depth 1 origin "$revision"
git -C "$target_dir" checkout --detach --force FETCH_HEAD
installed_revision="$(git -C "$target_dir" rev-parse HEAD)"
if [ "$installed_revision" != "$revision" ]; then
	echo "Requested revision $revision but installed $installed_revision" >&2
	exit 1
fi

if [ -f "$target_dir/requirements.txt" ]; then
	"$python_bin" -m pip install --requirement "$target_dir/requirements.txt"
fi

if [ ! -L "$node_link" ]; then
    ln -s -- "$target_dir" "$node_link"
fi

echo "Installed $directory_name at $installed_revision on $storage_root"
echo "Restart ComfyUI, then use /object_info to verify the required node types before importing a workflow."
