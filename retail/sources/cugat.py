from retail.platforms.woocommerce import listing_item_to_product as wc_product
from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_cugat_target = parse_woocommerce_target


def listing_item_to_product(item, *, source: str | None = None):
    return wc_product(item, store_id="cugat", seller="Cugat", source=source)


CugatStore = make_woocommerce_store(
    store_id="cugat",
    title="Cugat",
    site="www.cugat.cl",
    base="https://www.cugat.cl",
    category_help="Slug WooCommerce, por ejemplo lacteos",
)
