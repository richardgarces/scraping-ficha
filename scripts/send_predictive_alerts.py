#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retail.predictive_alerts import dispatch_predictive_alerts
from retail.mongo import ProductRepository


def main() -> None:
    repo = ProductRepository()
    try:
        if not repo.ping():
            raise SystemExit("MongoDB no está disponible.")
        print(json.dumps(dispatch_predictive_alerts(repo), ensure_ascii=False, default=str))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
