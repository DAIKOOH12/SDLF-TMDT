"""Local alternative to the QuickSight dashboard (dashboard/README.md).

QuickSight needs a verified payment method on the AWS account before it lets
you subscribe (confirmed error: "Account <id> is not eligible to subscribe to
AmazonQuickSight"), which blocks it for a free-tier account with no card on
file. This script produces the same four visuals QuickSight would, as static
PNGs, by querying the Analytics Iceberg table directly through Athena
(awswrangler) and plotting with matplotlib — no AWS service beyond Athena is
needed, and nothing here costs anything beyond the Athena bytes-scanned.

Usage:
    python local_dashboard.py --database product_analytics --table products
"""

import argparse
import logging
import os

import awswrangler as wr
import matplotlib.pyplot as plt
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("local_dashboard")

# dataviz skill palette (references/palette.md) — light-mode categorical
# slots 1-3, which are the ones validated for all-pairs comparison (scatter).
# This project only has 3 crawled categories (crawler/config.py), so slots
# 1-3 cover every category without folding into "Other".
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
CATEGORY_COLORS = [BLUE, ORANGE, AQUA]

INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_SECONDARY,
        "text.color": INK,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "axes.titlecolor": INK,
    }
)


def load_data(database: str, table: str, athena_output: str | None) -> pd.DataFrame:
    query = f"""
        SELECT product_id, name, category, price, rating_average, discount_pct,
               sold_growth_rate, review_growth, potential_score, crawl_date
        FROM {table}
    """
    logger.info("Querying Athena: database=%s table=%s", database, table)
    df = wr.athena.read_sql_query(sql=query, database=database, s3_output=athena_output)
    logger.info("Loaded %d rows", len(df))
    return df


def _style_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def chart_top_potential(df: pd.DataFrame, outdir: str, top_n: int = 15):
    ranked = df.dropna(subset=["potential_score"]).sort_values("potential_score", ascending=False).head(top_n)
    if ranked.empty:
        logger.warning("No rows with potential_score — skipping top_potential chart")
        return

    labels = [n[:40] + ("…" if len(n) > 40 else "") for n in ranked["name"].fillna("(no name)")]

    fig, ax = plt.subplots(figsize=(9, max(3, 0.4 * len(ranked))))
    y_pos = range(len(ranked))
    ax.barh(y_pos, ranked["potential_score"], color=BLUE, height=0.65, zorder=3)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    _style_axes(ax)
    ax.set_xlabel("potential_score")
    ax.set_title(f"Top {len(ranked)} sản phẩm tiềm năng", fontsize=13, fontweight="bold", loc="left")

    for y, v in zip(y_pos, ranked["potential_score"]):
        ax.text(v, y, f" {v:.1f}", va="center", fontsize=8.5, color=INK)

    fig.tight_layout()
    path = os.path.join(outdir, "top_potential.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Wrote %s", path)


def chart_avg_score_by_category(df: pd.DataFrame, outdir: str):
    scored = df.dropna(subset=["potential_score"])
    if scored.empty:
        logger.warning("No rows with potential_score — skipping avg_score_by_category chart")
        return

    agg = scored.groupby("category")["potential_score"].mean().sort_values(ascending=False)
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i in range(len(agg))]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(agg.index, agg.values, color=colors, width=0.55, zorder=3)
    _style_axes(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_ylabel("potential_score trung bình")
    ax.set_title("Điểm tiềm năng trung bình theo ngành hàng", fontsize=13, fontweight="bold", loc="left")
    for i, v in enumerate(agg.values):
        ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9, color=INK)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")

    fig.tight_layout()
    path = os.path.join(outdir, "avg_score_by_category.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Wrote %s", path)


def chart_price_vs_rating(df: pd.DataFrame, outdir: str):
    plot_df = df.dropna(subset=["price", "rating_average", "category"])
    if plot_df.empty:
        logger.warning("No rows with price/rating — skipping price_vs_rating chart")
        return

    categories = sorted(plot_df["category"].unique())[: len(CATEGORY_COLORS)]
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for cat, color in zip(categories, CATEGORY_COLORS):
        subset = plot_df[plot_df["category"] == cat]
        ax.scatter(subset["price"], subset["rating_average"], s=28, color=color, alpha=0.75, label=cat, zorder=3)

    _style_axes(ax)
    ax.set_xlabel("Giá bán (VND)")
    ax.set_ylabel("Điểm đánh giá trung bình")
    ax.set_title("Giá vs. đánh giá, theo ngành hàng", fontsize=13, fontweight="bold", loc="left")
    ax.legend(frameon=False, loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=9)

    fig.tight_layout()
    path = os.path.join(outdir, "price_vs_rating.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Wrote %s", path)


def chart_growth_distribution(df: pd.DataFrame, outdir: str):
    values = df["sold_growth_rate"].dropna()
    if values.empty:
        logger.warning("No non-null sold_growth_rate yet — skipping growth_distribution chart")
        return

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(values, bins=20, color=BLUE, zorder=3)
    _style_axes(ax)
    ax.set_xlabel("sold_growth_rate")
    ax.set_ylabel("Số sản phẩm")
    ax.set_title("Phân phối tốc độ tăng trưởng số lượng bán", fontsize=13, fontweight="bold", loc="left")

    fig.tight_layout()
    path = os.path.join(outdir, "growth_distribution.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Wrote %s", path)


def main():
    parser = argparse.ArgumentParser(description="Render a local PNG dashboard from the Analytics table")
    parser.add_argument("--database", default="product_analytics")
    parser.add_argument("--table", default="products")
    parser.add_argument("--athena-output", default=None, help="s3:// path for Athena query results")
    parser.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "output"))
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    df = load_data(args.database, args.table, args.athena_output)
    if df.empty:
        logger.warning("Analytics table returned no rows — run the pipeline first")
        return

    chart_top_potential(df, args.outdir)
    chart_avg_score_by_category(df, args.outdir)
    chart_price_vs_rating(df, args.outdir)
    chart_growth_distribution(df, args.outdir)

    scored = df.dropna(subset=["potential_score"]).sort_values("potential_score", ascending=False)
    print("\nTop 10 sản phẩm tiềm năng:")
    print(
        scored[["name", "category", "sold_growth_rate", "review_growth", "potential_score"]]
        .head(10)
        .to_string(index=False)
    )
    print(f"\nCharts written to {args.outdir}")


if __name__ == "__main__":
    main()
