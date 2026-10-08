from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_umbrale_target = parse_vtex_target

UmbraleStore = make_vtex_store(
    store_id="umbrale",
    title="Umbrale",
    site="www.umbrale.cl",
    base="https://www.umbrale.cl",
    default_brand='Umbrale',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="moda",
)
