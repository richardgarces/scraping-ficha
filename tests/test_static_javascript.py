from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("script", ["app.js", "analisis-producto.js", "catalogo.js", "comparar.js", "cron.js", "producto.js", "prices.js"])
def test_product_page_javascript_has_valid_syntax(script: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js no está instalado")
    path = Path("retail/web/static") / script
    subprocess.run([node, "--check", str(path)], check=True, capture_output=True, text=True)


def test_cron_manual_start_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js no está instalado")
    result = subprocess.run([node, "--test", "tests/cron_start.test.js"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_offer_filter_requires_a_measurable_saving() -> None:
    script = Path("retail/web/static/app.js").read_text(encoding="utf-8")
    start = script.index("function isRealOffer(row)")
    end = script.index("function matchesFilters", start)
    rule = script[start:end]
    assert "publishedBefore > price" in rule
    assert "median > price" in rule
    assert "previous > price" in rule
    assert "Boolean(stats.is_lowest_ever)" not in rule
    assert "row.cheaper_elsewhere" not in rule


def test_product_page_has_contextual_back_link() -> None:
    page = Path("retail/web/static/producto.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    assert 'id="back-results"' in page
    assert "document.referrer" in script
    assert "history.back()" in script


def test_product_other_store_panel_cannot_overlap_the_main_card():
    styles = Path("retail/web/static/styles.css").read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);" in styles
    assert ".product-main-column { overflow: hidden; }" in styles
    assert "#others-panel { min-width: 0; max-width: 100%; overflow: hidden;" in styles
    assert "@media (min-width: 901px) and (max-width: 1180px)" in styles
    assert ".product-side-column { position: static; width: 100%; max-width: none; }" in styles


def test_product_page_has_simple_community_reviews():
    page = Path("retail/web/static/producto.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    styles = Path("retail/web/static/styles.css").read_text(encoding="utf-8")
    assert 'id="reviews-panel"' in page
    assert page.count("data-review-rating=") == 5
    assert 'maxlength="600"' in page
    assert "Últimos comentarios" in page
    assert 'fetch("/api/product-reviews"' in script
    assert "Ver todos" in script
    assert ".product-reviews-layout" in styles
    assert ".review-stars-input" in styles


def test_product_price_charts_show_every_calendar_day():
    page = Path("retail/web/static/producto.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    styles = Path("retail/web/static/styles.css").read_text(encoding="utf-8")
    assert "return Array.from({ length: count }" in script
    assert "chartWidthForDays" in script
    assert "chartSidePads" in script
    assert "basePad + 24" in script
    assert "chartAxisAnchor" in script
    assert "showLatestChartDay" in script
    assert 'class="chart-point"' in script
    assert "día a día" in script
    assert page.count('class="price-chart-scroll"') == 3
    assert ".price-chart-scroll .chart" in styles
    assert "max-width: none" in styles
    assert "overflow-x: auto" in styles
    assert 'producto.js?v=36' in page
    assert 'styles.css?v=80' in page


def test_product_other_stores_panel_is_collapsible_and_open_by_default() -> None:
    page = Path("retail/web/static/producto.html").read_text(encoding="utf-8")
    styles = Path("retail/web/static/styles.css").read_text(encoding="utf-8")
    assert '<details class="panel others-panel" id="others-panel" open hidden>' in page
    assert 'class="others-toggle"' in page
    assert 'class="others-toggle-label"' in page
    assert 'class="others-toggle-chevron"' in page
    assert "Precios en otras tiendas" in page
    assert '.others-toggle-label::before { content: "Mostrar"; }' in styles
    assert '.others-panel[open] > summary .others-toggle-label::before { content: "Ocultar"; }' in styles
    assert ".others-toggle {" in styles
    assert ".product-side-column > .panel:not([hidden])" in styles


def test_product_price_chart_keeps_last_date_label_inside_viewbox():
    """La última fecha del eje X (p. ej. «30 sep») no debe quedar pegada al borde."""
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    styles = Path("retail/web/static/styles.css").read_text(encoding="utf-8")
    start = script.index("function chartSidePads")
    end = script.index("function chartAxisAnchor", start)
    helper = script[start:end]
    assert "right: basePad + 24" in helper
    assert "padLeft + (index / (prices.length - 1)) * (width - padLeft - padRight)" in script
    assert "padLeft + (index / Math.max(days.length - 1, 1)) * (width - padLeft - padRight)" in script
    assert "width - padRight" in script
    assert ".price-chart-scroll .chart { width: var(--chart-min-width, 100%); max-width: none;" in styles


def test_product_comparison_modal_uses_hidden_state_and_theme_colors() -> None:
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    styles = Path("retail/web/static/styles.css").read_text(encoding="utf-8")
    assert 'id="compare-modal" class="modal"' in script
    assert 'aria-labelledby="compare-title" hidden' in script
    assert '$("compare-modal").hidden = false' in script
    assert ".modal[hidden] { display: none !important; }" in styles
    assert "background: var(--panel); color: var(--text);" in styles
    assert "loadSimilarProducts()" in script
    assert 'event.key === "Escape"' in script


def test_comparison_opens_as_full_page_and_includes_price_rows() -> None:
    product_script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    page = Path("retail/web/static/comparar.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/comparar.js").read_text(encoding="utf-8")
    assert "/comparar?store=" in product_script
    assert "Comparar productos" in page
    assert 'row("Precio actual"' in script
    assert 'row("Precio normal"' in script
    assert 'row("Ahorro"' in script
    assert 'only_comparable: "true"' in script
    assert "comparison_fields" in script


def test_product_comparison_is_only_shown_to_logged_in_users() -> None:
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    assert 'id="compare-link"' in script
    assert "data-auth hidden" in script
    assert "mountCompareAccess()" in script
    assert 'link.hidden = !user' in script


def test_product_forecast_panel_is_admin_only_and_collapsed_by_default() -> None:
    page = Path("retail/web/static/producto.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    assert 'id="forecast-panel" data-admin hidden' in page
    assert '<details class="panel forecast-panel"' in page
    assert 'user?.role !== "admin"' in script
    assert "panel.open = false" in script
    assert "panel.open = true" not in script


def test_timesfm_offer_summary_is_admin_only() -> None:
    for page_name, script_name in (("reales.html", "reales.js"), ("super.html", "super.js")):
        page = Path(f"retail/web/static/{page_name}").read_text(encoding="utf-8")
        script = Path(f"retail/web/static/{script_name}").read_text(encoding="utf-8")
        assert 'id="timesfm-summary" class="timesfm-summary muted" data-admin hidden' in page
        assert 'window.retailUser && window.retailUser.role === "admin"' in script
        assert "TimesFM aún no se muestra en ofertas:" in script
        assert "typeof ensureUser === \"function\") await ensureUser()" in script
