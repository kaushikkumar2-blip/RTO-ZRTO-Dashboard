"""
RTO / ZRTO Streamlit Dashboard — table-only, seller-centric
Run:  python -m streamlit run app.py
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="RTO / ZRTO Dashboard",
    page_icon="\U0001F4E6",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CSV_PATH = "601168f592cc35c1ef35fc3672be19d9.csv"


@st.cache_data(show_spinner="Loading data \u2026")
def load_data() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, dtype={"reporting_date": str})
    df["rto_count"] = df["rto_count"].fillna(0).astype("int64")
    df["date"] = pd.to_datetime(df["reporting_date"], format="%Y%m%d")
    df["is_zrto"] = df["rto_type"] == "ZRTO"
    df["total_shipment_count"] = df["total_shipment_count"].fillna(0).astype("int64")
    df["payment_type"] = df["payment_type"].fillna("unknown")
    df["last_undelivery_status"] = df["last_undelivery_status"].fillna("(blank)")
    df["LPD_Bucket"] = df["LPD_Bucket"].fillna("(blank)")
    df["rto_reason"] = df["rto_reason"].fillna("(blank)")
    return df


def get_total_shipments(frame: pd.DataFrame) -> int:
    deduped = frame.drop_duplicates(
        subset=["reporting_date", "seller_type", "payment_type"]
    )
    return int(deduped["total_shipment_count"].sum())


df_all = load_data()

# ── Header ───────────────────────────────────────────────────────
st.markdown("# \U0001F4E6 RTO / ZRTO Dashboard")

# ── Filters (main page) ─────────────────────────────────────────
date_min = df_all["date"].min().date()
date_max = df_all["date"].max().date()

seller_types_list = sorted(df_all["seller_type"].dropna().unique().tolist())
payment_options = sorted(df_all["payment_type"].dropna().unique().tolist())
lpd_options = sorted(df_all["LPD_Bucket"].dropna().unique().tolist())

fc1, fc2, fc3, fc4 = st.columns([2, 1, 2, 2])

with fc1:
    date_range = st.date_input(
        "Date range",
        value=(date_min, date_max),
        min_value=date_min,
        max_value=date_max,
    )
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    d_start, d_end = date_range
else:
    d_start, d_end = date_min, date_max

with fc2:
    picked_seller = st.selectbox(
        "Seller type",
        options=["(All sellers)"] + seller_types_list,
        key="seller_pick",
    )

with fc3:
    selected_payments = st.multiselect(
        "Payment type",
        options=payment_options,
        default=[],
        placeholder="All payment types",
    )

with fc4:
    selected_lpd = st.multiselect(
        "LPD Bucket",
        options=lpd_options,
        default=[],
        placeholder="All LPD buckets",
    )

# ── Apply global filters (date, payment, lpd) ───────────────────
mask = (df_all["date"].dt.date >= d_start) & (df_all["date"].dt.date <= d_end)
if selected_payments:
    mask &= df_all["payment_type"].isin(selected_payments)
if selected_lpd:
    mask &= df_all["LPD_Bucket"].isin(selected_lpd)

df = df_all[mask]

st.caption(
    f"**{d_start:%b %d, %Y}** \u2192 **{d_end:%b %d, %Y}** \u00b7 "
    f"**{df['reporting_date'].nunique()}** days \u00b7 "
    f"**{df['rto_count'].sum():,}** total RTO units"
)

if df.empty:
    st.warning("No data matches the current filters.")
    st.stop()

# ── Apply seller filter ──────────────────────────────────────────
if picked_seller == "(All sellers)":
    seller_df = df
    seller_label = "All Sellers"
else:
    seller_df = df[df["seller_type"] == picked_seller]
    seller_label = picked_seller

if seller_df.empty:
    st.warning(f"No data for seller type **{seller_label}** in selected filters.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — RTO Deep Dive
# ═══════════════════════════════════════════════════════════════════
st.divider()
st.markdown(f"## RTO Deep Dive \u2014 {seller_label}")

total_shipments = get_total_shipments(seller_df)
total_rto = int(seller_df["rto_count"].sum())
zrto_total = int(seller_df.loc[seller_df["is_zrto"], "rto_count"].sum())
non_zrto_total = total_rto - zrto_total
overall_rto_pct = round(100 * total_rto / total_shipments, 2) if total_shipments else 0.0
zrto_pct_of_shipments = round(100 * zrto_total / total_shipments, 2) if total_shipments else 0.0

non_zrto_pct_of_shipments = round(100 * non_zrto_total / total_shipments, 2) if total_shipments else 0.0
delivered = total_shipments - total_rto
delivered_pct = round(100 * delivered / total_shipments, 2) if total_shipments else 0.0

overview_data = pd.DataFrame({
    "Category": ["Delivered", "RTO (Non-ZRTO + ZRTO)", "ZRTO", "Non-ZRTO"],
    "Shipments": [delivered, total_rto, zrto_total, non_zrto_total],
    "% of Total Shipments": [delivered_pct, overall_rto_pct, zrto_pct_of_shipments, non_zrto_pct_of_shipments],
})
st.dataframe(
    overview_data.style.format({
        "Shipments": "{:,}",
        "% of Total Shipments": "{:.2f}%",
    }),
    use_container_width=True, hide_index=True,
)

st.markdown("### Non-ZRTO Reason Breakdown (% of Total Shipments)")
non_zrto_df = seller_df[~seller_df["is_zrto"]]
if non_zrto_df.empty:
    st.info("No Non-ZRTO records for this selection.")
else:
    non_zrto_reasons = (
        non_zrto_df.groupby("rto_reason")["rto_count"]
        .sum()
        .reset_index()
        .rename(columns={"rto_reason": "Reason", "rto_count": "Count"})
        .sort_values("Count", ascending=False)
    )
    non_zrto_reasons["% of Total Shipments"] = (
        100 * non_zrto_reasons["Count"] / total_shipments
    ).round(2) if total_shipments else 0.0
    st.dataframe(
        non_zrto_reasons.style.format({
            "Count": "{:,}",
            "% of Total Shipments": "{:.2f}%",
        }),
        use_container_width=True, hide_index=True,
    )

st.markdown("### ZRTO Reason Breakdown (% of Total Shipments)")
zrto_df = seller_df[seller_df["is_zrto"]]
if zrto_df.empty:
    st.info("No ZRTO records for this selection.")
else:
    zrto_reasons = (
        zrto_df.groupby("rto_reason")["rto_count"]
        .sum()
        .reset_index()
        .rename(columns={"rto_reason": "Reason", "rto_count": "Count"})
        .sort_values("Count", ascending=False)
    )
    zrto_reasons["% of Total Shipments"] = (
        100 * zrto_reasons["Count"] / total_shipments
    ).round(2) if total_shipments else 0.0
    st.dataframe(
        zrto_reasons.style.format({
            "Count": "{:,}",
            "% of Total Shipments": "{:.2f}%",
        }),
        use_container_width=True, hide_index=True,
    )

# ═══════════════════════════════════════════════════════════════════
# SECTION 5 — LPD Bucket breakdown
# ═══════════════════════════════════════════════════════════════════
st.divider()
st.markdown(f"## LPD Bucket Breakdown \u2014 {seller_label}")

lpd_pivot = (
    seller_df.groupby(["LPD_Bucket", "rto_type"])["rto_count"]
    .sum()
    .reset_index()
    .pivot_table(
        index="LPD_Bucket", columns="rto_type",
        values="rto_count", fill_value=0,
    )
)
if "ZRTO" not in lpd_pivot.columns:
    lpd_pivot["ZRTO"] = 0
if "Non_ZRTO" not in lpd_pivot.columns:
    lpd_pivot["Non_ZRTO"] = 0
lpd_pivot["Total"] = lpd_pivot.sum(axis=1)
lpd_pivot["ZRTO %"] = (100 * lpd_pivot["ZRTO"] / lpd_pivot["Total"]).round(2)
lpd_pivot["% of Total Shipments"] = (
    100 * lpd_pivot["Total"] / total_shipments
).round(2) if total_shipments else 0.0
lpd_pivot = lpd_pivot.sort_values("Total", ascending=False)
lpd_pivot = lpd_pivot.rename(
    columns={"Non_ZRTO": "Non-ZRTO"},
).rename_axis("LPD Bucket")

st.dataframe(
    lpd_pivot.style.format({
        "Non-ZRTO": "{:,}", "ZRTO": "{:,}", "Total": "{:,}",
        "ZRTO %": "{:.2f}%", "% of Total Shipments": "{:.2f}%",
    }),
    use_container_width=True, hide_index=False,
)

# ═══════════════════════════════════════════════════════════════════
# SECTION 6 — Trend table for selected seller (Daily / Weekly / Monthly)
# ═══════════════════════════════════════════════════════════════════
st.divider()

trend_view = st.radio(
    "Trend view",
    options=["Weekly", "Monthly"],
    horizontal=True,
    key="trend_view",
)

st.markdown(f"## {trend_view} Trend \u2014 {seller_label}")

deduped_shipments = seller_df.drop_duplicates(
    subset=["reporting_date", "seller_type", "payment_type"]
)

if trend_view == "Weekly":
    seller_wk = seller_df.copy()
    seller_wk["week"] = seller_wk["date"].dt.to_period("W")
    grp_total = seller_wk.groupby("week")["rto_count"].sum().rename("Total RTO")
    grp_zrto = (
        seller_wk.loc[seller_wk["is_zrto"]]
        .groupby("week")["rto_count"].sum().rename("ZRTO")
    )
    deduped_wk = deduped_shipments.copy()
    deduped_wk["week"] = deduped_wk["date"].dt.to_period("W")
    grp_shipments = (
        deduped_wk.groupby("week")["total_shipment_count"].sum().rename("Total Shipments")
    )
    trend_tbl = pd.concat([grp_shipments, grp_total, grp_zrto], axis=1).fillna(0)
    trend_tbl = trend_tbl.reset_index()
    trend_tbl["Period"] = trend_tbl["week"].apply(
        lambda p: f"Week {p.start_time.isocalendar()[1]} ({p.start_time.strftime('%b %Y')})"
    )
    trend_tbl = trend_tbl.drop(columns=["week"])
    change_label = "WoW Change"

else:
    seller_mo = seller_df.copy()
    seller_mo["month"] = seller_mo["date"].dt.to_period("M")
    grp_total = seller_mo.groupby("month")["rto_count"].sum().rename("Total RTO")
    grp_zrto = (
        seller_mo.loc[seller_mo["is_zrto"]]
        .groupby("month")["rto_count"].sum().rename("ZRTO")
    )
    deduped_mo = deduped_shipments.copy()
    deduped_mo["month"] = deduped_mo["date"].dt.to_period("M")
    grp_shipments = (
        deduped_mo.groupby("month")["total_shipment_count"].sum().rename("Total Shipments")
    )
    trend_tbl = pd.concat([grp_shipments, grp_total, grp_zrto], axis=1).fillna(0)
    trend_tbl = trend_tbl.reset_index()
    trend_tbl["month"] = trend_tbl["month"].astype(str)
    trend_tbl = trend_tbl.rename(columns={"month": "Period"})
    change_label = "MoM Change"

trend_tbl["Total Shipments"] = trend_tbl["Total Shipments"].astype(int)
trend_tbl["ZRTO"] = trend_tbl["ZRTO"].astype(int)
trend_tbl["Total RTO"] = trend_tbl["Total RTO"].astype(int)
trend_tbl["Non-ZRTO"] = trend_tbl["Total RTO"] - trend_tbl["ZRTO"]
trend_tbl["Overall RTO%"] = (
    100 * trend_tbl["Total RTO"] / trend_tbl["Total Shipments"]
).round(2)
trend_tbl["ZRTO%"] = (
    100 * trend_tbl["ZRTO"] / trend_tbl["Total Shipments"]
).round(2)
trend_tbl["ZRTO % of RTO"] = (
    100 * trend_tbl["ZRTO"] / trend_tbl["Total RTO"].replace(0, pd.NA)
).round(2).fillna(0)
trend_tbl[change_label] = trend_tbl["Total RTO"].diff().fillna(0).astype(int)

trend_tbl = trend_tbl[
    ["Period", "Total Shipments", "Total RTO", "Overall RTO%", "ZRTO", "ZRTO%",
     "Non-ZRTO", "ZRTO % of RTO", change_label]
].sort_values("Period", ascending=False)

st.dataframe(
    trend_tbl.style.format({
        "Total Shipments": "{:,}", "Total RTO": "{:,}", "Overall RTO%": "{:.2f}%",
        "ZRTO": "{:,}", "ZRTO%": "{:.2f}%", "Non-ZRTO": "{:,}",
        "ZRTO % of RTO": "{:.2f}%", change_label: "{:+,}",
    }),
    use_container_width=True, hide_index=True, height=500,
)

st.download_button(
    f"Download {trend_view.lower()} trend CSV",
    trend_tbl.to_csv(index=False).encode("utf-8"),
    file_name=f"{trend_view.lower()}_trend_{seller_label}.csv",
    mime="text/csv",
    key="dl_trend",
)

# ── Footer ────────────────────────────────────────────────────────
st.divider()
st.caption("RTO / ZRTO Dashboard")
