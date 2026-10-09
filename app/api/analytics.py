"""Read-only usage and material purchase cost estimates, grouped per spool.

Never aggregate different currencies; calculations exclude electricity and labor.
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
            records=db.execute(
                """SELECT s.id,s.initial_g,s.purchase_price_cents,s.purchase_currency,
                          p.material, SUM(-m.delta_g) AS consumed_g
                   FROM movements m JOIN spools s ON s.id=m.spool_id
                   JOIN products p ON p.id=s.product_id
                   WHERE m.kind='consume' AND m.delta_g<0
                   GROUP BY s.id"""
            ).fetchall()
        buckets=defaultdict(lambda: {"consumed_g":0,"known_cost_cents":0,"unpriced_g":0})
        by_material=defaultdict(int)
        for row in records:
            used=row["consumed_g"]
            by_material[row["material"]]+=used
            target=buckets[row["purchase_currency"] or "EUR"]
            target["consumed_g"]+=used
            if row["purchase_price_cents"] is None:
                target["unpriced_g"]+=used
            else:
                cents=(Decimal(row["purchase_price_cents"])*Decimal(used)
                       /Decimal(row["initial_g"])).quantize(
                           Decimal("1"),rounding=ROUND_HALF_UP)
                target["known_cost_cents"]+=int(cents)
        return {"consumed_g":sum(by_material.values()),
                "currency_groups":[{"currency":c,**v} for c,v in sorted(buckets.items())],
                "materials":[{"material":k,"consumed_g":v}
                             for k,v in sorted(by_material.items())],
                "estimated":True,"cost_basis":"purchase_price_per_initial_gram"}
