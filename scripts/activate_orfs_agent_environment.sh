#!/usr/bin/env bash
# Source this file before an ORFS-Agent Runtime attempt.  It intentionally
# selects admitted, pinned sources and prevents a caller's unrelated ORFS
# checkout from becoming FLOW_HOME.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source scripts/activate_orfs_agent_environment.sh" >&2
  exit 2
fi

orfs_platform_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ORFS_AGENT_MANAGED_RUN_ROOT="$orfs_platform_root/runs/orfs-agent-managed"
export ORFS_AGENT_SOURCE="/tmp/openroad-p5-orfs-agent.skG6MP"
export ORFS_AGENT_PAPER_ORFS_ROOT="/tmp/orfs-agent-paper-orfs-clean"
export OPENROAD_BIN="/share/home/yuanwenjie/bin/openroad"
export YOSYS_BIN="/share/home/yuanwenjie/bin/yosys"
export ORFS_AGENT_PYTHON="$orfs_platform_root/.tools/venvs/orfs-agent/bin/python"
unset FLOW_HOME WORK_HOME LOG_DIR RESULTS_DIR OBJECTS_DIR REPORTS_DIR FLOW_VARIANT

for orfs_required_path in "$ORFS_AGENT_SOURCE" "$ORFS_AGENT_PAPER_ORFS_ROOT" "$OPENROAD_BIN" "$YOSYS_BIN" "$ORFS_AGENT_PYTHON"; do
  if [[ ! -e "$orfs_required_path" ]]; then
    echo "Missing required ORFS-Agent environment path: $orfs_required_path" >&2
    return 2
  fi
done

mkdir -p "$ORFS_AGENT_MANAGED_RUN_ROOT"
echo "ORFS_AGENT_MANAGED_RUN_ROOT=$ORFS_AGENT_MANAGED_RUN_ROOT"
echo "ORFS_AGENT_SOURCE=$ORFS_AGENT_SOURCE"
echo "ORFS_AGENT_PAPER_ORFS_ROOT=$ORFS_AGENT_PAPER_ORFS_ROOT"
"$OPENROAD_BIN" -version
"$YOSYS_BIN" -V
