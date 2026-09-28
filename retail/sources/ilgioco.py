from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_ilgioco_target = parse_vtex_target

IlgiocoStore = make_vtex_store(
    store_id="ilgioco",
    title="Il Gioco",
    site="www.ilgioco.cl",
    base="https://www.ilgioco.cl",
    category_help="Slug VTEX, por ejemplo poleras",
    intelligent_search=True,
    group="moda",
)
