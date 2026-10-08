from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_sony_target = parse_vtex_target

SonyStore = make_vtex_store(
    store_id="sony",
    title="Sony",
    site="store.sony.cl",
    base="https://store.sony.cl",
    default_brand='Sony',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="tecnologia",
)
