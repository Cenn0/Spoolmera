"""Read-only usage and purchase-price material cost estimates.

Currency groups are deliberately not summed together. Estimates are based on
recorded consumption and purchase price; no electricity, labor or depreciation.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from fastapi import FastAPI
from app.database import session


def register_analytics_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/analytics/material-usage")
    def material_usage():
        with session(db_path) as db:
            records = db.execute(
                """SELECT m.delta_g,m.kind,m.source,s.initial_g,s.purchase_price_cents,
                          s.purchase_currency,p.material
                   FROM movements m JOIN spools s ON s.id=m.spool_id
                   JOIN products p ON p.id=s.product_id
                   WHERE m.kind='consume' AND m.delta_g<0"""
            ).fetchall()
        buckets = defaultdict(lambda: {"consumed_g":0,"known_cost_cents":0,"unpriced_g":0})
        by_material = defaultdict(int)
        for row in records:
            grams = -row["delta_g"]
            by_material[row["material"]] += grams
            currency = row["purchase_currency"] or "EUR"
            target = buckets[currency]
            target["consumed_g"] += grams
            if row["purchase_price_cents"] is None:
                target["unpriced_g"] += grams
            else:
                cents = (Decimal(row["purchase_price_cents"])*Decimal(grams)
                         / Decimal(row["initial_g"])).quantize(
                    Decimal("1"),rounding=ROUND_HALF_UP)
                target["known_cost_cents"] += int(cents)
        return {"consumed_g":sum(by_material.values()),
                "currency_groups":[{"currency":c,**v} for c,v in sorted(buckets.items())],
                "materials":[{"material":k,"consumed_g":v}
                             for k,v in sorted(by_material.items())],
                "estimated":True,"cost_basis":"purchase_price_per_initial_gram"}
