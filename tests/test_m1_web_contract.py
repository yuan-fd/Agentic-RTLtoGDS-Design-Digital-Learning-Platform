from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).parents[1]
WEB = ROOT / "apps" / "m1_rtl_to_gds" / "web"


def test_m1_web_exposes_two_explicit_workspaces_and_real_data_states():
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert 'id="studioPanel"' in html
    assert 'id="workbenchPanel"' in html
    assert 'role="tabpanel"' in html
    assert 'id="pdkSelect"' in html
    assert 'id="selectedRtlVersion"' in html
    assert 'id="runStateDetail"' in html
    assert 'id="artifactList"' in html
    assert 'Unavailable' in html
    assert 'No area, timing, power or DRC values are available.' in html


def test_m1_web_visual_contract_rejects_template_styling_and_fake_measurements():
    css = (WEB / "app.css").read_text(encoding="utf-8").lower()
    html = (WEB / "index.html").read_text(encoding="utf-8").lower()

    assert "gradient" not in css
    assert "linear-gradient" not in css
    assert "qor: 0" not in html
    assert "area: 0" not in html
    assert "timing: 0" not in html


def test_m1_web_javascript_parses_without_node_errors():
    node = shutil.which("node")
    if node is None:
        return
    result = subprocess.run(
        [node, "--check", str(WEB / "app.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
