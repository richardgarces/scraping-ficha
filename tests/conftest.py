from types import SimpleNamespace
import shutil
import socket
import subprocess
import time

import pytest
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

import retail.offer_screenshot as offer_screenshot

_REAL_LOAD_STORED_SCREENSHOTS = offer_screenshot.load_stored_screenshots_enabled


@pytest.fixture(autouse=True)
def _offer_screenshots_follow_env_unless_overridden(monkeypatch):
    """Sin repo inyectado, las pruebas no consultan el Mongo del desarrollador.

    `screenshots_enabled()` sigue `OFFER_SCREENSHOTS` salvo que la prueba pase
    un repo o guarde el ajuste. Así el cron y el admin comparten la misma
    decisión, y la suite no depende de un documento real.
    """

    def _load(repo=None):
        if repo is None:
            return None
        return _REAL_LOAD_STORED_SCREENSHOTS(repo)

    offer_screenshot.clear_screenshots_setting_cache()
    monkeypatch.setattr(offer_screenshot, "load_stored_screenshots_enabled", _load)
    yield
    offer_screenshot.clear_screenshots_setting_cache()


@pytest.fixture
def anonymous_repo(monkeypatch):
    """Una conexión disponible, sin sesión, para probar permisos sin Mongo local."""
    repo = SimpleNamespace(close=lambda: None)
    for module in ("deps", "app", "settings_api"):
        monkeypatch.setattr(f"retail.web.{module}.connect_repo", lambda: repo)
    return repo


@pytest.fixture(scope="module")
def mongo_uri(tmp_path_factory):
    """Mongo temporal para verificar reservas entre clientes independientes."""
    mongod = shutil.which("mongod")
    if not mongod:
        pytest.skip("Estas pruebas requieren mongod para verificar reservas atómicas")
    directory = tmp_path_factory.mktemp("retail-test-mongo")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    uri = f"mongodb://127.0.0.1:{port}"
    process = subprocess.Popen([
        mongod, "--dbpath", str(directory), "--port", str(port),
        "--bind_ip", "127.0.0.1", "--nounixsocket", "--logpath", str(directory / "mongo.log"),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = MongoClient(uri, serverSelectionTimeoutMS=200)
    try:
        for _ in range(50):
            if process.poll() is not None:
                pytest.fail((directory / "mongo.log").read_text())
            try:
                client.admin.command("ping")
                break
            except ConnectionFailure:
                time.sleep(0.1)
        else:
            pytest.fail("Mongo temporal no inició")
        yield uri
    finally:
        client.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
