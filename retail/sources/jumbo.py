from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_jumbo_target = parse_vtex_target

JumboStore = make_vtex_store(
    store_id="jumbo",
    title="Jumbo",
    site="www.jumbo.cl",
    base="https://www.jumbo.cl",
    default_brand='Jumbo',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="supermercados",
)
