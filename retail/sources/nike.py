from retail.platforms.vtex import listing_item_to_product as vtex_item_to_product
from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_nike_target = parse_vtex_target


def listing_item_to_product(item, *, source: str | None = None):
    return vtex_item_to_product(
        item,
        store_id="nike",
        base="https://www.nike.cl",
        default_brand="Nike",
        source=source,
    )


NikeStore = make_vtex_store(
    store_id="nike",
    title="Nike Chile",
    site="www.nike.cl",
    base="https://www.nike.cl",
    default_brand="Nike",
    category_help="Slug VTEX, por ejemplo ropa/polerones",
)
