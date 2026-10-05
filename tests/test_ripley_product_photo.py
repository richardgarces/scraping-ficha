import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import retail.offer_screenshot as shots


def test_ripley_photo_downloaded_as_jpeg_and_cached(monkeypatch, tmp_path):
    import curl_cffi.requests

    content = io.BytesIO()
    Image.new("RGB", (120, 120), "purple").save(content, format="WEBP")
    calls = []

    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append(url)
            return SimpleNamespace(
                content=content.getvalue(), raise_for_status=lambda: None
            )

    monkeypatch.setattr(curl_cffi.requests, "Session", Session)
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    monkeypatch.setattr(shots, "capture_offer_screenshot", lambda payload: None)
    payload = {
        "store": "ripley",
        "url": "https://simple.ripley.cl/p",
        "image_url": "https://rimage.ripley.cl/product",
    }
    result = shots.resolve_alert_image(payload)
    assert result != payload["image_url"]
    with Image.open(result) as image:
        assert image.format == "JPEG"
        assert image.size == (120, 120)
    assert shots.resolve_alert_image(payload) == result
    assert len(calls) == 1


def test_ripley_non_image_response_keeps_original_photo(monkeypatch, tmp_path):
    import curl_cffi.requests

    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return SimpleNamespace(
                content=b"<html>Blocked</html>", raise_for_status=lambda: None
            )

    monkeypatch.setattr(curl_cffi.requests, "Session", Session)
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    monkeypatch.setattr(shots, "capture_offer_screenshot", lambda payload: None)
    photo = "https://rimage.ripley.cl/product"
    assert shots.resolve_alert_image({"store": "ripley", "image_url": photo}) == photo
    assert not list(tmp_path.glob("*.jpg"))
