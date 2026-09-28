from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_florsheim_target = parse_vtex_target

FlorsheimStore = make_vtex_store(
    store_id="florsheim",
    title="Florsheim",
    site="www.florsheim.cl",
    base="https://www.florsheim.cl",
    category_help="Slug VTEX, por ejemplo zapatos",
    group="calzado",
)
