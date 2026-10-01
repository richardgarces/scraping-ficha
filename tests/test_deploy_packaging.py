import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import pytest


SCRIPT = Path("scripts/remote/00-pack-and-push-app.sh")
SYNC = Path("scripts/sync-to-precios.sh")
CONFIGS = ("retail/batch/programacion.json", "retail/batch/reglas_ofertas.json")


def write_fixture(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_deploy_archive_excludes_secrets_and_runtime_data(tmp_path):
    if not shutil.which("zip"):
        pytest.skip("zip no está instalado")
    script = SCRIPT.read_text()
    block = script[script.index('  zip -r'):script.index('  # Forzar')]
    patterns = re.findall(r'-x "([^"]+)"', block)
    excluded = (
        ".git/config", ".env", ".env.prod", ".mongo_creds", ".push-defaults",
        ".build/old.zip", ".venv/bin/python", "logs/app.log", "storage/data",
        "output/data", "backups/data", ".DS_Store", "retail/.DS_Store",
        "retail/__pycache__/app.pyc", "node_modules/test/index.js",
        "nested/node_modules/test/index.js",
    )
    for name in (*excluded, "retail/app.py", *CONFIGS):
        write_fixture(tmp_path, name, "fixture")
    archive = tmp_path / ".build/test.zip"
    command = ["zip", "-rq", str(archive), "."]
    for pattern in patterns:
        command.extend(["-x", pattern])
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    with zipfile.ZipFile(archive) as packed:
        files = {name for name in packed.namelist() if not name.endswith("/")}
    assert files == {"retail/app.py", *CONFIGS}


@pytest.mark.parametrize("existing_configs", [(), CONFIGS[:1], CONFIGS])
def test_deploy_initializes_missing_config_and_preserves_remote_data(tmp_path, existing_configs):
    if not shutil.which("rsync"):
        pytest.skip("rsync no está instalado")
    stage, remote = tmp_path / "stage", tmp_path / "remote"
    protected = (
        ".env", ".env.prod", ".mongo_creds", ".push-defaults", ".git/config",
        ".venv/bin/python", ".build/archive.zip", "backups/data",
        "storage/data", "logs/app.log", "output/data",
    )
    for name in ("retail/app.py", *CONFIGS):
        write_fixture(stage, name, "new default")
    for name in ("retail/app.py", "obsolete.py", *protected, *existing_configs):
        write_fixture(remote, name, "remote")
    # Un secreto accidentalmente presente en el paquete tampoco debe reemplazarlo.
    for name in protected:
        write_fixture(stage, name, "local fixture")
    script = SCRIPT.read_text()
    start = script.index("rsync -a --delete")
    end = script.index('if [[ -f', start)
    sync_script = script[start:end].replace("\\$", "$")
    subprocess.run(
        ["bash", "-euc", sync_script], check=True, capture_output=True,
        env={**os.environ, "STAGE_DIR": str(stage), "REMOTE_DIR": str(remote)},
    )
    assert (remote / "retail/app.py").read_text() == "new default"
    assert not (remote / "obsolete.py").exists()
    for name in protected:
        assert (remote / name).read_text() == "remote", name
    for name in CONFIGS:
        expected = "remote" if name in existing_configs else "new default"
        assert (remote / name).read_text() == expected, name


def test_ci_sync_preserves_remote_secrets_and_schedule(tmp_path):
    if not shutil.which("rsync"):
        pytest.skip("rsync no está instalado")
    source, dest = tmp_path / "source", tmp_path / "dest"
    for name in ("retail/app.py", "scripts/deploy-prod.sh", *CONFIGS):
        write_fixture(source, name, "new")
    for name in ("retail/app.py", "obsolete.py", ".env", "logs/app.log", *CONFIGS):
        write_fixture(dest, name, "remote")
    subprocess.run(
        ["bash", str(SYNC)],
        check=True,
        capture_output=True,
        env={**os.environ, "SRC_DIR": str(source), "DEPLOY_DIR": str(dest)},
    )
    assert (dest / "retail/app.py").read_text() == "new"
    assert not (dest / "obsolete.py").exists()
    assert (dest / ".env").read_text() == "remote"
    assert (dest / "logs/app.log").read_text() == "remote"
    for name in CONFIGS:
        assert (dest / name).read_text() == "remote"
