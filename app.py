"""
RTO / ZRTO Streamlit Dashboard — table-only, seller-centric
Run:  python -m streamlit run app.py
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
import hmac
import hashlib
import json
import re
import time
import base64
from pathlib import Path
import streamlit.components.v1 as _components

st.set_page_config(
    page_title="RTO / ZRTO Dashboard",
    page_icon="\U0001F4E6",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT_DIR = Path(__file__).resolve().parent
CSV_PATH = ROOT_DIR / "601168f592cc35c1ef35fc3672be19d9.csv"
CLIENT_LIST_CSV = ROOT_DIR / "client list.csv"
ADMIN_EMAILS_JSON = ROOT_DIR / "admin_emails.json"

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# ─────────────────────────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────────────────────────
def _safe_secret_compare(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except ValueError:
        return False


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _dashboard_auth_cfg() -> dict:
    try:
        x = st.secrets.get("dashboard_auth")
        if x is None:
            return {}
        return dict(x)
    except Exception:
        return {}


def _load_admin_emails_from_disk() -> list[str]:
    if not ADMIN_EMAILS_JSON.is_file():
        return []
    try:
        data = json.loads(ADMIN_EMAILS_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return sorted({_norm_email(e) for e in data if isinstance(e, str) and _norm_email(e)})


def _save_admin_emails_to_disk(emails: list[str]) -> None:
    norm = sorted({_norm_email(e) for e in emails if _norm_email(e)})
    ADMIN_EMAILS_JSON.write_text(json.dumps(norm, indent=2), encoding="utf-8")


def _ensure_admin_file_seeded() -> None:
    cfg = _dashboard_auth_cfg()
    boot = cfg.get("bootstrap_admin_emails") or []
    if not isinstance(boot, list):
        boot = []
    boot_norm = [_norm_email(e) for e in boot if _norm_email(e)]
    if not ADMIN_EMAILS_JSON.is_file() and boot_norm:
        _save_admin_emails_to_disk(boot_norm)


def _viewer_accounts() -> list[dict]:
    cfg = _dashboard_auth_cfg()
    v = cfg.get("viewers")
    if not v:
        return []
    if isinstance(v, list):
        return [dict(x) for x in v if isinstance(x, dict)]
    return []


def _attempt_login(email: str, password: str) -> tuple[bool, str, str, str | None]:
    em = _norm_email(email)
    pwd = password or ""
    cfg = _dashboard_auth_cfg()
    admin_pwd = str(cfg.get("admin_password", "") or "")
    _ensure_admin_file_seeded()
    admins = _load_admin_emails_from_disk()
    if em and em in admins and admin_pwd and _safe_secret_compare(pwd, admin_pwd):
        return True, "admin", "", None
    for row in _viewer_accounts():
        ve = _norm_email(str(row.get("email", "")))
        vp = str(row.get("password", "") or "")
        zone = str(row.get("zone", "") or "").strip()
        if ve == em and vp and _safe_secret_compare(pwd, vp):
            if not zone:
                return False, "", "Viewer account missing zone in secrets.", None
            return True, "viewer", "", zone
    if not cfg and not _viewer_accounts():
        return False, "", "Missing dashboard_auth in .streamlit/secrets.toml.", None
    return False, "", "Invalid email or password.", None


# ─────────────────────────────────────────────────────────────────
# COOKIE-BASED SESSION PERSISTENCE
# ─────────────────────────────────────────────────────────────────
_COOKIE_NAME = "rto_dash_session"
_COOKIE_MAX_AGE = 86400 * 7


def _get_cookie_secret() -> str:
    cfg = _dashboard_auth_cfg()
    admin_pwd = str(cfg.get("admin_password", "") or "fallback-key")
    return hashlib.sha256(f"rto-dash-{admin_pwd}".encode()).hexdigest()


def _sign_session(email: str, role: str, zone: str | None) -> str:
    secret = _get_cookie_secret()
    expiry = int(time.time()) + _COOKIE_MAX_AGE
    payload = json.dumps({"email": email, "role": role, "zone": zone, "exp": expiry})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_session(token: str) -> dict | None:
    try:
        secret = _get_cookie_secret()
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _read_session_cookie() -> dict | None:
    try:
        token = st.context.cookies.get(_COOKIE_NAME)
        if not token:
            return None
        return _verify_session(token)
    except Exception:
        return None


def _set_session_cookie(email: str, role: str, zone: str | None) -> None:
    token = _sign_session(email, role, zone)
    _components.html(
        f"<script>document.cookie='{_COOKIE_NAME}={token};path=/;max-age={_COOKIE_MAX_AGE};SameSite=Lax';</script>",
        height=0,
    )


def _clear_session_cookie() -> None:
    _components.html(
        f"<script>document.cookie='{_COOKIE_NAME}=;path=/;max-age=0;SameSite=Lax';</script>",
        height=0,
    )


# ─────────────────────────────────────────────────────────────────
# CLIENT LIST → seller code to region mapping
# ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_code_to_region(path: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return mapping
    try:
        df = pd.read_csv(p)
    except Exception:
        return mapping
    cols_lower = {str(c).strip().lower(): c for c in df.columns}

    def _pick(*subs: str) -> str | None:
        for key, orig in cols_lower.items():
            if all(s in key for s in subs):
                return orig
        return None

    code_key = _pick("customer", "code") or _pick("seller", "code")
    region_key = _pick("region")
    if not code_key or not region_key:
        return mapping
    for _, row in df.iterrows():
        codes_cell = row[code_key]
        if pd.isna(codes_cell):
            continue
        region = row[region_key]
        if pd.isna(region):
            continue
        region = str(region).strip()
        for code in str(codes_cell).strip().split("/"):
            code = code.strip().upper()
            if code and region:
                mapping[code] = region
    return mapping


CODE_TO_REGION = _load_code_to_region(str(CLIENT_LIST_CSV))


def _seller_types_in_zone(seller_types: list, zone: str) -> list[str]:
    z = (zone or "").strip()
    if not z:
        return []
    out: list[str] = []
    for stype in seller_types:
        if not isinstance(stype, str):
            continue
        for part in stype.split("/"):
            if CODE_TO_REGION.get(part.strip().upper()) == z:
                out.append(stype)
                break
    return sorted(set(out))


# ─────────────────────────────────────────────────────────────────
# SESSION INITIALIZATION
# ─────────────────────────────────────────────────────────────────
if "_session_initialized" not in st.session_state:
    st.session_state._session_initialized = True
    session = _read_session_cookie()
    if session:
        st.session_state.authenticated = True
        st.session_state.auth_email = session.get("email", "")
        st.session_state.auth_role = session.get("role", "")
        st.session_state.auth_zone = session.get("zone")
    else:
        st.session_state.authenticated = False
        st.session_state.auth_email = ""
        st.session_state.auth_role = ""
        st.session_state.auth_zone = None
else:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "auth_email" not in st.session_state:
        st.session_state.auth_email = ""
    if "auth_role" not in st.session_state:
        st.session_state.auth_role = ""
    if "auth_zone" not in st.session_state:
        st.session_state.auth_zone = None

# ─────────────────────────────────────────────────────────────────
# LOGIN GATE
# ─────────────────────────────────────────────────────────────────
if not st.session_state.authenticated:
    if st.session_state.pop("_needs_cookie_clear", False):
        _clear_session_cookie()
    st.title("RTO / ZRTO Dashboard \u2014 Sign in")
    cfg = _dashboard_auth_cfg()
    if not cfg.get("admin_password") and not _viewer_accounts():
        st.error(
            "Configure **[dashboard_auth]** in `.streamlit/secrets.toml`."
        )
    with st.form("login_form"):
        le = st.text_input("Email")
        lp = st.text_input("Password", type="password")
        sub = st.form_submit_button("Sign in")
    if sub:
        ok, role, msg, zone = _attempt_login(le, lp)
        if ok:
            st.session_state.authenticated = True
            st.session_state.auth_email = _norm_email(le)
            st.session_state.auth_role = role
            st.session_state.auth_zone = zone
            st.session_state._needs_cookie_set = True
            st.rerun()
        elif msg:
            st.error(msg)
    st.stop()

IS_ADMIN = st.session_state.auth_role == "admin"

if st.session_state.pop("_needs_cookie_set", False):
    _set_session_cookie(
        st.session_state.auth_email,
        st.session_state.auth_role,
        st.session_state.auth_zone,
    )

if st.session_state.pop("_needs_cookie_clear", False):
    _clear_session_cookie()


# ─────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────
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

# ── Zone-based filtering for viewers ─────────────────────────────
if st.session_state.auth_role == "viewer":
    vz = st.session_state.auth_zone or ""
    all_types = list(df_all["seller_type"].unique())
    allowed_types = _seller_types_in_zone(all_types, vz)
    df_all = df_all[df_all["seller_type"].isin(allowed_types)]
    if df_all.empty:
        st.warning(
            f"No rows match your zone **{vz}** for the seller codes in this data. "
            "Check that seller codes exist in the client list with that Region."
        )
        st.stop()

# ── Sidebar: user info, logout, admin panel ──────────────────────
with st.sidebar:
    role_label = "Admin" if IS_ADMIN else f"Viewer ({st.session_state.auth_zone or '\u2014'})"
    st.caption(f"**{st.session_state.auth_email}** \u00b7 {role_label}")
    if st.button("Log out", use_container_width=True, key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.auth_email = ""
        st.session_state.auth_role = ""
        st.session_state.auth_zone = None
        st.session_state._needs_cookie_clear = True
        st.rerun()

    if IS_ADMIN:
        st.divider()
        with st.expander("Admin users", expanded=False):
            cur_admins = _load_admin_emails_from_disk()
            if cur_admins:
                st.markdown("**Admin emails**")
                for _e in cur_admins:
                    st.text(_e)
            else:
                st.caption("No admin emails on file.")
            new_ad = st.text_input("Add admin email", key="new_admin_email_input")
            if st.button("Add email", key="add_admin_email_btn"):
                ne = _norm_email(new_ad)
                if not ne or not _EMAIL_RE.match(ne):
                    st.error("Enter a valid email address.")
                elif ne in cur_admins:
                    st.warning("That email is already an admin.")
                else:
                    _save_admin_emails_to_disk(cur_admins + [ne])
                    st.success(f"Added {ne}")
                    st.rerun()
            rm_opts = ["\u2014"] + cur_admins
            rm_pick = st.selectbox("Remove admin", options=rm_opts, key="remove_admin_select")
            if st.button("Remove selected", key="remove_admin_btn") and rm_pick != "\u2014":
                _save_admin_emails_to_disk([e for e in cur_admins if e != rm_pick])
                st.success(f"Removed {rm_pick}")
                st.rerun()

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
    "Category": ["Delivered", "Overall RTO (Non-ZRTO + ZRTO)"],
    "Shipments": [delivered, total_rto],
    "% of Total Shipments": [delivered_pct, overall_rto_pct],
})
st.dataframe(
    overview_data.style.format({
        "Shipments": "{:,}",
        "% of Total Shipments": "{:.2f}%",
    }),
    use_container_width=True, hide_index=True,
)

st.markdown("### Overall RTO Breakup")

zrto_pct_of_rto = round(100 * zrto_total / total_rto, 2) if total_rto else 0.0
non_zrto_pct_of_rto = round(100 * non_zrto_total / total_rto, 2) if total_rto else 0.0

rto_breakup_data = pd.DataFrame({
    "Category": ["Non-ZRTO", "ZRTO"],
    "Shipments": [non_zrto_total, zrto_total],
    "% of Total Shipments": [non_zrto_pct_of_shipments, zrto_pct_of_shipments],
    "% of Total RTO": [non_zrto_pct_of_rto, zrto_pct_of_rto],
})
st.dataframe(
    rto_breakup_data.style.format({
        "Shipments": "{:,}",
        "% of Total Shipments": "{:.2f}%",
        "% of Total RTO": "{:.2f}%",
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
