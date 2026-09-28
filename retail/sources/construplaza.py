from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_construplaza_target = parse_vtex_target

ConstruplazaStore = make_vtex_store(
    store_id="construplaza",
    title="Construplaza",
    site="www.construplaza.cl",
    base="https://www.construplaza.cl",
    category_help="Slug VTEX, por ejemplo herramientas",
)
