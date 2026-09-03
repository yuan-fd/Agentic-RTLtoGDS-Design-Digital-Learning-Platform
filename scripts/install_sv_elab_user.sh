#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
orfs_root="${1:-$(cd "${repository_root}/.." && pwd)/OpenROAD-flow-scripts}"
source_root="${repository_root}/.external-src/yosys-slang"
build_root="${source_root}/build-gcc12"
tool_env="${repository_root}/.tools/venvs/sv-elab-build"
mamba_root="${repository_root}/.tools/mamba-root"
micromamba="${repository_root}/.tools/micromamba/bin/micromamba"
yosys_config="${repository_root}/.tools/sv-elab-yosys-config"
plugin_target="${orfs_root}/tools/install/yosys/share/yosys/plugins/slang.so"
readonly expected_commit="ce38835520fbdf422304a6f6a2f1c437c3ba98c2"

if [[ ! -x "${orfs_root}/tools/install/yosys/bin/yosys" ]]; then
  echo "Pinned ORFS Yosys is missing: ${orfs_root}" >&2
  exit 2
fi
if [[ ! -x "${micromamba}" ]]; then
  mkdir -p "$(dirname "${micromamba}")"
  curl -L --fail --retry 3 https://micro.mamba.pm/api/micromamba/linux-aarch64/latest \
    -o "${repository_root}/.tools/micromamba/micromamba.tar.bz2"
  tar -xjf "${repository_root}/.tools/micromamba/micromamba.tar.bz2" \
    -C "${repository_root}/.tools/micromamba"
fi
if [[ ! -d "${source_root}/.git" ]]; then
  git clone --recursive https://github.com/povik/yosys-slang.git "${source_root}"
fi
git -C "${source_root}" fetch --depth 1 origin "${expected_commit}"
git -C "${source_root}" checkout --detach "${expected_commit}"
git -C "${source_root}" submodule update --init --recursive
if [[ "$(git -C "${source_root}" rev-parse HEAD)" != "${expected_commit}" ]]; then
  echo "sv-elab source pin mismatch" >&2
  exit 3
fi

MAMBA_ROOT_PREFIX="${mamba_root}" "${micromamba}" create -y -p "${tool_env}" \
  -c conda-forge 'gxx_linux-aarch64=12' 'cmake>=3.25' ninja
chmod +x "${yosys_config}"
"${tool_env}/bin/cmake" --fresh -S "${source_root}" -B "${build_root}" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="${tool_env}/bin/ninja" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_COMPILER="${tool_env}/bin/aarch64-conda-linux-gnu-g++" \
  -DYOSYS_CONFIG="${yosys_config}"
"${tool_env}/bin/cmake" --build "${build_root}" --parallel "${SV_ELAB_BUILD_JOBS:-16}"
install -D -m 755 "${build_root}/slang.so" "${plugin_target}"
"${orfs_root}/tools/install/yosys/bin/yosys" -m slang -Q -p 'help read_slang' >/dev/null
sha256sum "${plugin_target}"
