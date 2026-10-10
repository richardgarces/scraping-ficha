import re
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from retail.web.app import app


STATIC = Path("retail/web/static")
BRAND = STATIC / "brand"


def test_brand_icon_suite_has_expected_sizes_and_transparency():
    expected = {
        "precios-logo.png": (256, 256),
        "favicon-32.png": (32, 32),
        "apple-touch-icon.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
    }
    for filename, size in expected.items():
        with Image.open(BRAND / filename) as image:
            assert image.size == size
            assert image.mode == "RGBA"
            assert image.getchannel("A").getextrema() == (0, 255)


def test_favicon_and_touch_icon_routes_are_available():
    client = TestClient(app)
    favicon = client.get("/favicon.ico")
    touch = client.get("/apple-touch-icon.png")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/x-icon")
    assert touch.status_code == 200
    assert touch.headers["content-type"].startswith("image/png")


def test_home_declares_complete_brand_metadata():
    html = (STATIC / "index.html").read_text()
    manifest = (BRAND / "site.webmanifest").read_text()
    styles = (STATIC / "styles.css").read_text()
    assert 'rel="icon" href="/favicon.ico"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'rel="manifest"' in html
    assert "icon-192.png" in manifest
    assert "icon-512.png" in manifest
    assert 'url("/static/brand/precios-logo.png")' in styles
    for page in STATIC.glob("*.html"):
        assert "styles.css?v=" in page.read_text(), page.name


def test_mobile_ui_keeps_navigation_and_touch_layout():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "env(safe-area-inset-bottom)" in styles
    assert ".nav-menu-list" in styles
    assert "#others-panel .results" in styles
    assert "prefers-reduced-motion" in styles


def test_mobile_account_submenu_is_available_on_every_page():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".nav:has(.nav-menu[open]) { overflow: visible; }" in styles
    assert "bottom: calc(78px + env(safe-area-inset-bottom));" in styles
    for page in STATIC.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert 'class="nav-menu" data-login' in html, page.name
        assert 'data-login-mode="entrar"' in html, page.name
        assert 'data-login-mode="inscribir"' in html, page.name
        assert 'class="nav-menu" data-auth hidden' in html, page.name
        assert 'href="/super"' not in html, page.name
        for href in ("/cron", "/analisis-producto", "/estadisticas", "/usuarios", "/ofertas"):
            link = re.search(rf'<a href="{href}"[^>]*>', html)
            assert link and "data-admin" in link.group() and "hidden" in link.group(), (page.name, href)


def test_home_has_icons_for_all_catalog_category_families():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "renderCategoryShortcuts" in app_js
    for kind in (
        "calzado", "sports", "fashion", "appliance", "tech", "audio",
        "beauty", "food", "market", "tools", "kitchen", "toys", "auto",
        "garden", "home", "baby", "books", "pets", "other",
    ):
        assert f'return "{kind}"' in app_js
        assert f".category-shortcut.{kind} .category-icon" in styles


def test_home_categories_wrap_down_instead_of_scrolling_sideways():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    category_rules = styles[styles.index(".category-rail {"):styles.index(".category-shortcut.tech")]
    assert "display: grid" in category_rules
    assert "grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))" in category_rules
    assert "overflow-x: auto" not in category_rules
    assert ".category-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in styles


def test_home_category_cards_open_the_complete_filtered_catalog():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="catalog-categories"' in html
    assert 'aria-busy="true" hidden' in html
    assert '<div id="category-rail" class="category-rail" role="list" aria-label="Categorías del catálogo"></div>' in html
    assert 'class="category-shortcut' not in html
    assert 'href="/catalogo?category=${encodeURIComponent(value)}"' in script
    assert 'section.hidden = Boolean(currentQuery)' in script
    assert 'hideCategoryShortcuts();' in script
    assert "data-quick-query" not in html
    assert '$("category-rail").addEventListener("click"' not in script


def test_home_category_counts_are_not_rendered_for_public():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    # El HTML público de Explora rápido no incluye <small>/0; admin carga counts async.
    assert "Number(item.count) || 0" not in script
    assert "<small data-category-count data-admin hidden>${count" not in script
    assert "loadAdminCategoryCounts" in script
    assert 'json("/api/explore-categories?include_counts=1")' in script
    assert 'json("/api/explore-categories")' in script
    assert 'json("/api/catalog?size=1&only_offers=false")' not in script
    assert "renderCategoryShortcuts(explore.categories || [])" in script
    assert "item.icon || categoryIconKind(title)" in script
    assert "data-category-value=" in script


def test_home_loads_explore_categories_endpoint():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'json("/api/explore-categories").catch(() => ({}))' in app
    assert "loadAdminCategoryCounts(rail)" in app


def test_catalog_uses_one_main_search_and_collapsible_filters():
    html = (STATIC / "catalogo.html").read_text(encoding="utf-8")
    script = (STATIC / "catalogo.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert html.count('name="q" type="search"') == 1
    assert 'id="q"' not in html
    assert 'id="catalog-filters"' in html
    assert html.count('id="only_offers"') == 1
    assert 'class="toolbar catalog-filter-grid"' in html
    assert "catalogSearchInput" in script
    assert ".catalog-filter-grid" in styles
    assert '.filter-toggle-label::before { content: "Mostrar"; }' in styles


def test_every_page_has_one_global_product_search():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    pages = list(STATIC.glob("*.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert html.count('class="desktop-quick-search"') == 1, page.name
        assert 'name="q" type="search"' in html, page.name
        assert html.count('name="quick" type="checkbox" value="1" checked') == 1, page.name
        assert "Búsqueda rápida" in html, page.name
        assert '<a href="/">Buscar</a>' not in html, page.name
        assert '<a href="/">Explorar</a>' in html or '<a href="/" class="current">Explorar</a>' in html, page.name
    assert "body:has(.top .desktop-quick-search) #search-form .search-hero" in styles
    assert "html:not(.is-admin) body:has(.top .desktop-quick-search) #search-form" in styles


def test_header_search_input_uses_the_full_available_width():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert '.desktop-search-field { width: 100%; min-width: 0; }' in styles
    assert '.desktop-search-field input[type="search"] { display: block; width: 100%; min-width: 0; }' in styles


def test_quick_search_checkbox_forces_database_search():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'if (quickSearchEnabled()) return "db";' in script
    assert 'quick: quick ? "true" : "false"' in script
    assert 'fresh: $("fresh").checked ? "true" : "false"' in script
    assert ".quick-search-toggle" in styles
    assert ".quick-search-short" in styles


def test_unchecked_quick_search_from_other_pages_opens_store_search():
    script = (STATIC / "prices.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'form.matches(".desktop-quick-search")' in script
    assert 'location.href = `/?q=${encodeURIComponent(query)}&quick=0`' in script
    assert 'if (checkbox) checkbox.checked = start.get("quick") !== "0";' in app
    assert "runSearch(query);" in app


def test_first_search_waits_for_stores_before_elige_tienda_error():
    """Header submit must not show 'Elige al menos una tienda' before fillStores."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "let storesReady = false;" in app
    assert "let pendingSearchQuery = null;" in app
    assert "let storeSelectionTouched = false;" in app
    assert "if (!storesReady)" in app
    assert "pendingSearchQuery = query;" in app
    assert 'textContent = "Cargando tiendas…";' in app
    assert "storesReady = true;" in app
    assert "storeSelectionTouched = false;" in app
    assert "if (queued) runSearch(queued);" in app
    # Vacío / casillas ocultas = todas; error solo si el admin desmarcó a mano.
    assert "function hasExplicitEmptyStoreSelection()" in app
    assert "storeSelectionTouched" in app
    assert "searchIsAdmin()" in app
    assert "if (hasExplicitEmptyStoreSelection())" in app
    assert "Elige al menos una tienda." in app
    assert "if (stores.length && !allStoresSelected())" in app
    # Ocultar filtros de resultado antes de validar tiendas (evita «Sin filtros» bajo el error).
    early = app.split("function runSearch(query)")[1].split("pendingSearchQuery = null;")[0]
    assert "setResultFiltersVisible(false);" in early
    assert "app.js?v=59" in page


def test_refresh_meta_still_fills_stores_if_explore_fails():
    """Health/history/explore must not block fillStores when /api/stores works."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'json("/api/health").catch(() => ({}))' in app
    assert 'json("/api/history").catch(() => [])' in app
    assert 'json("/api/explore-categories").catch(() => ({}))' in app
    assert 'json("/api/stores")' in app
    assert "fillStores(stores);" in app


def test_empty_quick_search_offers_an_expanded_store_search():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "¿Ampliamos la búsqueda?" in script
    assert "Buscar en tiendas" in script
    assert "data-expand-quick-search" in script
    assert "if (checkbox) checkbox.checked = false;" in script
    assert "if (both) both.checked = true;" in script
    assert "offerExpandedSearch();" in script
    assert ".quick-search-empty" in styles


def test_search_spinner_stays_until_store_progress_is_complete():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    ready = script[script.index('if (payload.type === "ready")'):script.index('if (payload.type === "end")')]
    assert 'setSearching(false, { live: true })' not in ready
    assert 'if (hasActiveStores(payload.result)) return;' in ready
    assert 'setSearching(false);' in ready


def test_search_status_always_says_buscando():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Consultando" not in page
    assert "Consultando" not in script
    assert '"Buscando en productos"' in script
    assert '"Buscando..."' in script
    assert '$("summary").textContent = "Buscando…";' in script


def test_search_spinner_talks_to_the_user_as_offers_arrive():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'id="search-loading-detail"' in page
    assert 'aria-live="polite"' in page
    assert "renderSearchConversation" in script
    assert "¡Encontramos ${searchOfferLabel(offers)}!" in script
    assert "" in script
    assert "Todavía no encontramos coincidencias, pero seguimos buscando." in script
    assert ".search-loading-detail" in styles


def test_search_result_counts_are_visible_only_to_admins():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'data-result-focus="${focus}" data-admin-result hidden' in script
    assert 'document.querySelectorAll("[data-admin-result]")' in script
    assert 'element.hidden = !admin' in script
    assert 'revealAdminResultStats();' in script
    assert '$("summary").dataset.technicalSummary = "";' in script
    assert 'delete $("summary").dataset.technicalSummary;' in script
    assert 'html:not(.is-admin) #summary[data-technical-summary] { display: none !important; }' in styles


def test_mobile_deal_store_and_product_link_are_stacked():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    mobile = styles[styles.index("@media (max-width: 620px)"):]
    assert ".deal-meta { flex-direction: column; align-items: stretch; }" in mobile
    assert ".deal-meta > .deal-cta { justify-content: center; }" in mobile


def test_all_result_filters_use_the_collapsible_compact_pattern():
    pages = {
        "catalogo.html": "catalog-filter-count",
        "hoy.html": "today-filter-count",
        "reales.html": "real-filter-count",
        "index.html": "search-filter-count",
    }
    for filename, counter in pages.items():
        html = (STATIC / filename).read_text(encoding="utf-8")
        assert 'class="collapsible-filters' in html or 'class="collapsible-filters ' in html
        assert f'id="{counter}"' in html
        assert 'class="filter-toggle-label"' in html
    for filename in ("hoy.html", "reales.html"):
        html = (STATIC / filename).read_text(encoding="utf-8")
        assert 'id="q"' not in html
        assert html.count('name="q" type="search"') == 1
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".collapsible-filters > summary" in styles
    assert ".catalog-filter-grid .compact-filter-check" in styles


def test_explore_has_collapsible_search_and_result_filters():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="explore-filters" class="collapsible-filters"' in html
    assert 'id="explore-filter-count" class="filter-count"' in html
    assert 'id="toolbar" class="collapsible-filters search-result-filters"' in html
    assert "updateExploreFilterBadge" in script
    assert '$("toolbar").hidden = !visible;' in script
