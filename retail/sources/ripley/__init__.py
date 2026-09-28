from retail.base import StoreClient
from retail.models import Target
from retail.registry import StoreSpec, register
from retail.sources.ripley.client import SORT_MAP, RipleyClient
from retail.sources.ripley.urls import parse_target

__all__ = ["RipleyClient", "RipleyStore", "SORT_MAP"]


@register(
    StoreSpec(
        id="ripley",
        title="Ripley Chile",
        site="simple.ripley.cl",
        sort_map=SORT_MAP,
        category_help="Slug de categoría, por ejemplo tecno/computacion/notebooks",
    )
)
class RipleyStore(RipleyClient, StoreClient):
    def parse_target(self, value: str) -> Target:
        return parse_target(value)

    def category_target(self, args) -> Target:
        slug = args.category_id
        return Target(kind="category", category_id=slug, category_name=slug)
