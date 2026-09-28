from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_fensa_target = parse_vtex_target

FensaStore = make_vtex_store(
    store_id="fensa",
    title="Fensa",
    site="www.tiendafensa.cl",
    base="https://www.tiendafensa.cl",
    default_brand="Fensa",
    category_help="Slug VTEX, por ejemplo cocina/hornos",
    group="hogar",
)
