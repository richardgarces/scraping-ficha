import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_shared_pager_states_cover_first_middle_last_single_and_empty():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js no está instalado")
    helper = Path("retail/web/static/pagination.js").resolve()
    script = f"""
      const pager = require({json.dumps(str(helper))});
      const result = {{
        first: pager.state(1, 13),
        middle: pager.state(7, 13),
        last: pager.state(13, 13),
        single: pager.state(1, 1),
        empty: pager.state(8, 0),
        below: pager.state(-4, 13),
        above: pager.state(99, 13),
      }};
      process.stdout.write(JSON.stringify(result));
    """
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    states = json.loads(result.stdout)

    assert states["first"]["showPrevious"] is False
    assert states["first"]["showNext"] is True
    assert states["middle"]["showPrevious"] is True
    assert states["middle"]["showNext"] is True
    assert states["last"]["showPrevious"] is True
    assert states["last"]["showNext"] is False
    assert states["single"]["showPrevious"] is False
    assert states["single"]["showNext"] is False
    assert states["empty"] == {
        "page": 1,
        "totalPages": 1,
        "label": "Página 1 de 1",
        "showPrevious": False,
        "showNext": False,
    }
    assert states["below"]["page"] == 1
    assert states["above"]["page"] == 13


def test_list_pages_use_the_shared_accessible_pager():
    for name in ("catalogo", "hoy", "reales", "super"):
        page = Path(f"retail/web/static/{name}.html").read_text(encoding="utf-8")
        script = Path(f"retail/web/static/{name}.js").read_text(encoding="utf-8")
        assert 'class="panel pager simple-pager"' in page
        assert "/static/pagination.js?v=1" in page
        assert "Ir a la página anterior" in page
        assert "Ir a la página siguiente" in page
        assert "RetailPager.render(" in script


def test_explore_pager_omits_boundary_buttons_instead_of_disabling_them():
    script = Path("retail/web/static/app.js").read_text(encoding="utf-8")
    start = script.index("function renderPager(total)")
    end = script.index("function setView", start)
    pager = script[start:end]
    assert "currentPage > 1" in pager
    assert "currentPage < pages" in pager
    assert 'data-page="prev"' in pager
    assert 'data-page="next"' in pager
    assert "disabled" not in pager
