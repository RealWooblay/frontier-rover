#!/usr/bin/env bash
set -euo pipefail

cusparselt_dir="${HOME}/.local/cusparselt-0.6.2.3/lib"
if [[ ! -f "${cusparselt_dir}/libcusparseLt.so.0" ]]; then
    echo "Missing ${cusparselt_dir}/libcusparseLt.so.0" >&2
    exit 1
fi

export LD_LIBRARY_PATH="${cusparselt_dir}:/usr/local/cuda-12.6/lib64:${LD_LIBRARY_PATH:-}"
exec "$@"
