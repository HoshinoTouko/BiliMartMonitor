import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class Decision:
    can_abstract_product: bool
    confidence: float
    reasons: List[str]


def _default_db_path() -> str:
    return os.getenv("BSM_SQLITE_PATH", "./data/scan.db")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _extract_detail_items(detail_json: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(detail_json)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for x in data:
        if not isinstance(x, dict):
            continue
        iid = x.get("itemsId")
        if iid is None:
            continue
        try:
            iid = int(iid)
        except Exception:
            continue
        out.append(
            {
                "items_id": iid,
                "name": (x.get("name") or "").strip(),
                "img_url": (x.get("img") or x.get("imgUrl") or "").strip(),
            }
        )
    return out


def _load_current_detail_rows(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    sql = """
    WITH ranked AS (
        SELECT
            d.*,
            FIRST_VALUE(snapshot_at) OVER (
                PARTITION BY c2c_items_id
                ORDER BY (snapshot_at IS NULL), snapshot_at DESC, id DESC
            ) AS latest_snapshot_at
        FROM c2c_items_details d
    )
    SELECT *
    FROM ranked
    WHERE
        (snapshot_at = latest_snapshot_at)
        OR (snapshot_at IS NULL AND latest_snapshot_at IS NULL)
    """
    return conn.execute(sql).fetchall()


def _top_n_name_stats(conn: sqlite3.Connection, n: int) -> List[Dict[str, Any]]:
    sql = """
    WITH per_item AS (
        SELECT
            items_id,
            COUNT(DISTINCT c2c_items_id) AS listing_count,
            COUNT(DISTINCT COALESCE(NULLIF(TRIM(name), ''), '__NULL__')) AS name_variants,
            COUNT(DISTINCT COALESCE(NULLIF(TRIM(img_url), ''), '__NULL__')) AS img_variants
        FROM c2c_items_details
        GROUP BY items_id
    )
    SELECT *
    FROM per_item
    ORDER BY listing_count DESC, items_id ASC
    LIMIT ?
    """
    rows = conn.execute(sql, (n,)).fetchall()
    return [dict(r) for r in rows]


def _compute_decision(metrics: Dict[str, Any], strict: bool) -> Decision:
    unique_items = metrics["unique_items_id"]
    if unique_items <= 0:
        return Decision(
            can_abstract_product=False,
            confidence=0.0,
            reasons=["No items_id data found in c2c_items_details."],
        )

    stable_name_ratio = metrics["stable_name_ratio"]
    stable_img_ratio = metrics["stable_img_ratio"]
    coverage_ratio = metrics["detail_json_parse_coverage_ratio"]
    items_id_set_match_ratio = metrics["items_id_set_match_ratio"]

    score = 0.0
    score += min(stable_name_ratio, 1.0) * 0.35
    score += min(stable_img_ratio, 1.0) * 0.20
    score += min(coverage_ratio, 1.0) * 0.20
    score += min(items_id_set_match_ratio, 1.0) * 0.25

    reasons = [
        f"stable_name_ratio={stable_name_ratio:.3f}",
        f"stable_img_ratio={stable_img_ratio:.3f}",
        f"detail_json_parse_coverage_ratio={coverage_ratio:.3f}",
        f"items_id_set_match_ratio={items_id_set_match_ratio:.3f}",
    ]

    if strict:
        can = (
            stable_name_ratio == 1.0
            and stable_img_ratio == 1.0
            and coverage_ratio == 1.0
            and items_id_set_match_ratio == 1.0
            and int(metrics["detail_json_invalid_or_unparseable_rows"]) == 0
            and int(metrics["json_vs_details_mismatch_count"]) == 0
        )
        reasons.append(
            "strict_mode requires all key metrics == 1.0 and zero invalid/mismatch rows"
        )
    else:
        can = score >= 0.70 and stable_name_ratio >= 0.80 and items_id_set_match_ratio >= 0.70
    return Decision(can_abstract_product=can, confidence=round(score, 3), reasons=reasons)


def analyze(db_path: str, top_n: int, strict: bool, sample_limit: int) -> Dict[str, Any]:
    conn = _connect(db_path)
    try:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('c2c_items', 'c2c_items_details')"
        ).fetchall()
        table_names = {r["name"] for r in table_rows}
        missing = [t for t in ("c2c_items", "c2c_items_details") if t not in table_names]
        if missing:
            raise RuntimeError(f"missing required tables: {missing}")

        c2c_count = int(conn.execute("SELECT COUNT(*) FROM c2c_items").fetchone()[0])
        detail_count = int(conn.execute("SELECT COUNT(*) FROM c2c_items_details").fetchone()[0])
        unique_items_id = int(conn.execute("SELECT COUNT(DISTINCT items_id) FROM c2c_items_details").fetchone()[0] or 0)

        json_rows = conn.execute(
            "SELECT c2c_items_id, detail_json FROM c2c_items WHERE detail_json IS NOT NULL AND TRIM(detail_json) <> ''"
        ).fetchall()
        json_by_c2c: Dict[int, List[Dict[str, Any]]] = {}
        invalid_json_rows = 0
        for row in json_rows:
            c2c_id = int(row["c2c_items_id"])
            parsed = _extract_detail_items(row["detail_json"])
            if row["detail_json"] and not parsed:
                invalid_json_rows += 1
            json_by_c2c[c2c_id] = parsed

        current_detail_rows = _load_current_detail_rows(conn)
        current_by_c2c: Dict[int, List[Dict[str, Any]]] = {}
        for row in current_detail_rows:
            c2c_id = int(row["c2c_items_id"])
            current_by_c2c.setdefault(c2c_id, []).append(
                {
                    "items_id": int(row["items_id"]),
                    "name": (row["name"] or "").strip(),
                    "img_url": (row["img_url"] or "").strip(),
                }
            )

        comparable_ids = sorted(set(json_by_c2c) & set(current_by_c2c))
        set_match = 0
        set_mismatch = 0
        mismatch_examples: List[Dict[str, Any]] = []
        for c2c_id in comparable_ids:
            js = {x["items_id"] for x in json_by_c2c.get(c2c_id, [])}
            ds = {x["items_id"] for x in current_by_c2c.get(c2c_id, [])}
            if js == ds:
                set_match += 1
            else:
                set_mismatch += 1
                if len(mismatch_examples) < sample_limit:
                    mismatch_examples.append(
                        {
                            "c2c_items_id": c2c_id,
                            "only_in_detail_json": sorted(js - ds),
                            "only_in_c2c_items_details": sorted(ds - js),
                        }
                    )

        per_item_rows = conn.execute(
            """
            SELECT
                items_id,
                COUNT(DISTINCT COALESCE(NULLIF(TRIM(name), ''), '__NULL__')) AS name_variants,
                COUNT(DISTINCT COALESCE(NULLIF(TRIM(img_url), ''), '__NULL__')) AS img_variants,
                COUNT(DISTINCT c2c_items_id) AS listing_count
            FROM c2c_items_details
            GROUP BY items_id
            """
        ).fetchall()

        stable_name_cnt = 0
        stable_img_cnt = 0
        one_to_many_cnt = 0
        name_variant_examples: List[Dict[str, Any]] = []
        img_variant_examples: List[Dict[str, Any]] = []
        for row in per_item_rows:
            if int(row["name_variants"]) <= 1:
                stable_name_cnt += 1
            elif len(name_variant_examples) < sample_limit:
                name_variant_examples.append(
                    {
                        "items_id": int(row["items_id"]),
                        "name_variants": int(row["name_variants"]),
                        "listing_count": int(row["listing_count"]),
                    }
                )
            if int(row["img_variants"]) <= 1:
                stable_img_cnt += 1
            elif len(img_variant_examples) < sample_limit:
                img_variant_examples.append(
                    {
                        "items_id": int(row["items_id"]),
                        "img_variants": int(row["img_variants"]),
                        "listing_count": int(row["listing_count"]),
                    }
                )
            if int(row["listing_count"]) > 1:
                one_to_many_cnt += 1

        bundle_rows = conn.execute(
            """
            WITH current_counts AS (
                SELECT c2c_items_id, COUNT(DISTINCT items_id) AS item_cnt
                FROM (
                    WITH ranked AS (
                        SELECT
                            d.*,
                            FIRST_VALUE(snapshot_at) OVER (
                                PARTITION BY c2c_items_id
                                ORDER BY (snapshot_at IS NULL), snapshot_at DESC, id DESC
                            ) AS latest_snapshot_at
                        FROM c2c_items_details d
                    )
                    SELECT *
                    FROM ranked
                    WHERE
                        (snapshot_at = latest_snapshot_at)
                        OR (snapshot_at IS NULL AND latest_snapshot_at IS NULL)
                ) cur
                GROUP BY c2c_items_id
            )
            SELECT
                COUNT(*) AS total_current_listings,
                SUM(CASE WHEN item_cnt > 1 THEN 1 ELSE 0 END) AS bundled_listings
            FROM current_counts
            """
        ).fetchone()

        total_current_listings = int(bundle_rows["total_current_listings"] or 0)
        bundled_listings = int(bundle_rows["bundled_listings"] or 0)

        metrics: Dict[str, Any] = {
            "db_path": db_path,
            "c2c_items_count": c2c_count,
            "c2c_items_details_count": detail_count,
            "unique_items_id": unique_items_id,
            "detail_json_row_count": len(json_rows),
            "detail_json_invalid_or_unparseable_rows": invalid_json_rows,
            "detail_json_parse_coverage_ratio": (len(json_rows) - invalid_json_rows) / len(json_rows) if json_rows else 0.0,
            "json_vs_details_comparable_count": len(comparable_ids),
            "json_vs_details_match_count": set_match,
            "json_vs_details_mismatch_count": set_mismatch,
            "items_id_set_match_ratio": set_match / len(comparable_ids) if comparable_ids else 0.0,
            "stable_name_ratio": stable_name_cnt / unique_items_id if unique_items_id else 0.0,
            "stable_img_ratio": stable_img_cnt / unique_items_id if unique_items_id else 0.0,
            "items_id_shared_by_multiple_c2c_ratio": one_to_many_cnt / unique_items_id if unique_items_id else 0.0,
            "current_bundled_listing_ratio": bundled_listings / total_current_listings if total_current_listings else 0.0,
            "sample_top_items": _top_n_name_stats(conn, top_n),
            "strict_fail_samples": {
                "json_vs_details_mismatch_examples": mismatch_examples,
                "name_variant_examples": name_variant_examples,
                "img_variant_examples": img_variant_examples,
            },
        }

        decision = _compute_decision(metrics, strict=strict)
        report: Dict[str, Any] = {
            "summary": {
                "can_abstract_product_table": decision.can_abstract_product,
                "confidence": decision.confidence,
                "strict_mode": strict,
                "reasons": decision.reasons,
            },
            "metrics": metrics,
            "proposal": {
                "product_table_sql": [
                    "CREATE TABLE product (",
                    "  items_id INTEGER PRIMARY KEY,",
                    "  canonical_name TEXT,",
                    "  canonical_img_url TEXT,",
                    "  first_seen_at TEXT,",
                    "  last_seen_at TEXT,",
                    "  name_variant_count INTEGER NOT NULL DEFAULT 0,",
                    "  img_variant_count INTEGER NOT NULL DEFAULT 0,",
                    "  listing_count INTEGER NOT NULL DEFAULT 0,",
                    "  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    ");",
                ],
                "mapping_table_sql": [
                    "CREATE TABLE c2c_item_product_map (",
                    "  c2c_items_id INTEGER NOT NULL,",
                    "  items_id INTEGER NOT NULL,",
                    "  role TEXT NOT NULL DEFAULT 'component',",
                    "  snapshot_at TEXT,",
                    "  PRIMARY KEY (c2c_items_id, items_id, snapshot_at)",
                    ");",
                    "CREATE INDEX idx_c2c_item_product_map_items_id ON c2c_item_product_map(items_id);",
                ],
                "migration_hint": "Backfill product from c2c_items_details grouped by items_id; keep c2c_items.detail_json as raw snapshot cache only.",
            },
        }
        return report
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="analyze-product-abstraction",
        description="Analyze whether product table can be abstracted from c2c_items.detail_json and c2c_items_details",
    )
    parser.add_argument("--db", default=_default_db_path(), help="SQLite db path (default: BSM_SQLITE_PATH or ./data/scan.db)")
    parser.add_argument("--top", type=int, default=20, help="Top N items_id stats to show")
    parser.add_argument("--strict", action="store_true", help="Require all key consistency ratios to be 100%")
    parser.add_argument("--sample-limit", type=int, default=20, help="Max mismatch/variant sample rows in report")
    parser.add_argument("--json", action="store_true", help="Output full JSON report")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"database file not found: {db_path}", file=sys.stderr)
        return 2

    try:
        report = analyze(db_path, args.top, args.strict, args.sample_limit)
    except Exception as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    s = report["summary"]
    m = report["metrics"]
    print(f"DB: {m['db_path']}")
    print(f"c2c_items={m['c2c_items_count']}, c2c_items_details={m['c2c_items_details_count']}, unique_items_id={m['unique_items_id']}")
    print(
        "detail_json coverage={:.2%}, json/details set match={:.2%}".format(
            m["detail_json_parse_coverage_ratio"], m["items_id_set_match_ratio"]
        )
    )
    print(
        "stable_name_ratio={:.2%}, stable_img_ratio={:.2%}, shared_items_ratio={:.2%}, bundled_listing_ratio={:.2%}".format(
            m["stable_name_ratio"],
            m["stable_img_ratio"],
            m["items_id_shared_by_multiple_c2c_ratio"],
            m["current_bundled_listing_ratio"],
        )
    )
    print(
        f"can_abstract_product_table={s['can_abstract_product_table']} "
        f"(confidence={s['confidence']:.3f}, strict_mode={s['strict_mode']})"
    )
    for reason in s["reasons"]:
        print(f"- {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
