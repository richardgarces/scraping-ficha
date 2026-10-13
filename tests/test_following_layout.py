from pathlib import Path


def test_price_alerts_are_the_first_following_content_panel():
    page = (
        Path(__file__).resolve().parents[1]
        / "retail"
        / "web"
        / "static"
        / "siguiendo.html"
    ).read_text(encoding="utf-8")

    alerts = page.index('id="watch-list"')
    assert alerts < page.index('id="guest-box"')
    assert alerts < page.index('id="membership-panel"')
    assert alerts < page.index('id="watch-panel"')
    assert alerts < page.index('id="notification-panel"')
