from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_sallybeauty_target = parse_vtex_target

SallybeautyStore = make_vtex_store(
    store_id="sallybeauty",
    title="Sally Beauty",
    site="www.sallybeauty.cl",
    base="https://www.sallybeauty.cl",
    category_help="Slug VTEX, por ejemplo maquillaje",
)
