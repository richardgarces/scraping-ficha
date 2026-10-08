from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_blanik_target = parse_vtex_target

BlanikStore = make_vtex_store(
    store_id="blanik",
    title="Blanik",
    site="www.blanik.cl",
    base="https://www.blanik.cl",
    default_brand='Blanik',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="hogar",
)
