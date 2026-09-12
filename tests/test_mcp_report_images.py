import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = Path("/tmp/openroad-mcp-review")


def _call(tool, arguments):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/query_openroad_mcp.py"),
         "--repo", str(REPO), "--tool", tool, "--command", "report_image",
         "--arguments", json.dumps(arguments), "--timeout", "10"],
        text=True, capture_output=True, timeout=20, check=True,
    )
    return json.loads(completed.stdout)


def test_report_image_list_is_read_only_and_grouped():
    result = _call("list_report_images", {
        "platform": "sky130hd", "design": "ibex", "run_slug": "base",
    })
    assert result["status"] == "ok"
    assert result["result"]["total_images"] > 0
    assert result["result"]["images_by_stage"]


def test_report_image_returns_inline_data():
    result = _call("read_report_image", {
        "platform": "sky130hd", "design": "ibex", "run_slug": "base",
        "image_name": "final_all.webp", "max_size_kb": 100,
    })
    assert result["status"] == "ok"
    assert result["images"]
    assert result["images"][0]["data"]
