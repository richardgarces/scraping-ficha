from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_mifotopro_target = parse_woocommerce_target

MifotoproStore = make_woocommerce_store(
    store_id="mifotopro",
    title="MiFotoPro",
    site="www.mifotopro.cl",
    base="https://www.mifotopro.cl",
    category_help="Slug WooCommerce, por ejemplo fotografia",
)
