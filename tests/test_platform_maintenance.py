from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CADDY_EDGE = ROOT / "deploy/caddy/Caddyfile.platform-edge"
MAINT_HTML = ROOT / "deploy/caddy/maintenance.html"
MAINT_SCRIPT = ROOT / "scripts/precios-maintenance.sh"
DEPLOY_SCRIPT = ROOT / "scripts/deploy-prod.sh"


def test_caddyfile_has_proactive_maintenance_flag():
    text = CADDY_EDGE.read_text()
    assert "@maint file /srv/errors/precios-maintenance.enabled" in text
    assert 'error "precios maintenance" 503' in text
    assert "handle_errors" in text
    assert "precios-maintenance.html" in text


def test_maintenance_html_spanish_copy():
    html = MAINT_HTML.read_text()
    assert "Estamos actualizando la página" in html
    assert "Precios" in html


def test_deploy_script_toggles_maintenance():
    text = DEPLOY_SCRIPT.read_text()
    assert "precios-maintenance.sh" in text
    assert "wait_precios_health" in text
    assert "restore_precios_routing" in text


def test_bash_scripts_syntax():
    for path in (
        MAINT_SCRIPT,
        ROOT / "scripts/lib-platform-caddy.sh",
        ROOT / "scripts/link-platform-caddy.sh",
    ):
        subprocess.run(["bash", "-n", str(path)], check=True)
