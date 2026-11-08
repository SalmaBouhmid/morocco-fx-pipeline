"""Morocco FX dashboard: Bank Al-Maghrib exchange rates, updated every day by GitHub Actions.

Run on your PC:
    streamlit run dashboard/app.py                          (reads the `data` branch on GitHub)
    FX_DATA_DIR=data/export streamlit run dashboard/app.py  (reads a local folder)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import fx_data
import pandas as pd
import plotly.express as px
import streamlit as st

BASKET_SOURCE = (
    "https://www.bkam.ma/fr/Trouvez-l-information-concernant/"
    "Reforme-du-regime-de-change/Historique-du-regime-de-change"
)
REPO_URL = "https://github.com/SalmaBouhmid/morocco-fx-pipeline"
MAIN_CURRENCIES = ["EUR", "USD", "GBP", "CHF", "CAD", "SAR", "AED", "CNY"]
STATUS_ICON = {"ok": "🟢", "info": "🔵", "warn": "🟠", "error": "🔴"}

st.set_page_config(page_title="Dirham marocain — cours BAM", page_icon="💱", layout="wide")
# clearly different colours for each line (the default ones are two close blues)
px.defaults.color_discrete_sequence = px.colors.qualitative.D3


@st.cache_data(ttl=3600, show_spinner="Chargement des données…")
def load_all(source: str) -> dict[str, pd.DataFrame]:
    """All tables, kept in cache for 1 hour (the data changes once a day)."""
    with ThreadPoolExecutor(max_workers=len(fx_data.TABLES)) as pool:  # download in parallel
        loaded = pool.map(lambda name: fx_data.load_table(name, source), fx_data.TABLES)
        return dict(zip(fx_data.TABLES, loaded, strict=True))


try:
    tables = load_all(fx_data.data_source())
except Exception as exc:  # show any loading problem to the visitor
    st.error(f"Impossible de charger les données : {exc}")
    st.stop()

daily = tables["fct_daily_rates"]
monthly = tables["fct_monthly_rates"]
volatility = tables["fct_volatility"]
basket = tables["mad_basket_index"]
report = tables["data_quality_report"]
large_moves = tables["dq_large_moves"]
gaps = tables["dq_calendar_gaps"]
coverage = tables["dq_currency_coverage"]

last_day = daily["rate_date"].max()
currencies = sorted(daily["currency"].unique())

# ---------------------------------------------------------------- header
st.title("💱 Le dirham marocain face aux devises")
st.markdown(
    f"Cours de référence de **Bank Al-Maghrib**, du {daily['rate_date'].min():%d/%m/%Y} "
    f"au **{last_day:%d/%m/%Y}** (dernier jour publié). Mis à jour automatiquement chaque jour "
    "à 18 h (heure du Maroc) par un pipeline GitHub Actions."
)
st.caption(
    "Source : API Frankfurter (fournisseur `bam`), qui reprend les cours publiés par Bank "
    f"Al-Maghrib. Code : [{REPO_URL.removeprefix('https://')}]({REPO_URL})."
)

tab_today, tab_history, tab_vol, tab_basket, tab_quality = st.tabs(
    ["Cours du jour", "Historique", "Volatilité", "Panier du dirham", "Qualité des données"]
)

# ---------------------------------------------------------------- Q1: today's rate
with tab_today:
    snapshot = fx_data.latest_snapshot(daily)
    st.subheader(f"Cours du {last_day:%d/%m/%Y}")
    st.caption("Combien de dirhams pour 1 unité de devise, et variation depuis la veille.")
    main = snapshot[snapshot["currency"].isin(MAIN_CURRENCIES)].set_index("currency")
    columns = st.columns(4)
    for i, code in enumerate(c for c in MAIN_CURRENCIES if c in main.index):
        row = main.loc[code]
        change = row["pct_change_1d"]
        columns[i % 4].metric(
            f"MAD pour 1 {code}",
            f"{row['mad_per_unit']:.4f}",
            None if pd.isna(change) else f"{change:+.2f} %",
            delta_color="off",
            border=True,
        )
    st.markdown("**Toutes les devises**")
    st.dataframe(
        snapshot[["currency", "mad_per_unit", "pct_change_1d", "pct_change_1w", "pct_change_1m"]],
        hide_index=True,
        column_config={
            "currency": "Devise",
            "mad_per_unit": st.column_config.NumberColumn("MAD pour 1 unité", format="%.4f"),
            "pct_change_1d": st.column_config.NumberColumn("Var. 1 jour", format="%+.2f %%"),
            "pct_change_1w": st.column_config.NumberColumn("Var. 1 semaine", format="%+.2f %%"),
            "pct_change_1m": st.column_config.NumberColumn("Var. 1 mois", format="%+.2f %%"),
        },
    )
    st.caption(
        "Une hausse veut dire qu'il faut plus de dirhams pour 1 unité : la devise monte, "
        "le dirham baisse face à elle."
    )

# ---------------------------------------------------------------- Q3: history
with tab_history:
    left, right = st.columns([1, 3])
    currency = left.selectbox("Devise", currencies, index=currencies.index("EUR"))
    years = sorted(daily["rate_date"].dt.year.unique())
    start_year = left.select_slider("Depuis", options=years, value=max(years[0], years[-1] - 10))

    rows = daily[(daily["currency"] == currency) & (daily["rate_date"].dt.year >= start_year)]
    rows = rows.sort_values("rate_date").assign(
        moving_avg=lambda d: d["mad_per_unit"].rolling(30, min_periods=10).mean()
    )
    chart = rows.melt(
        id_vars="rate_date", value_vars=["mad_per_unit", "moving_avg"], var_name="série"
    )
    chart["série"] = chart["série"].map(
        {"mad_per_unit": "Cours du jour", "moving_avg": "Moyenne mobile 30 cotations"}
    )
    fig = px.line(
        chart,
        x="rate_date",
        y="value",
        color="série",
        labels={"rate_date": "", "value": f"MAD pour 1 {currency}", "série": ""},
    )
    fig.update_layout(legend={"orientation": "h", "y": 1.1}, margin={"t": 30})
    right.plotly_chart(fig)

    st.subheader(f"Quand fallait-il convertir ses {currency} en dirhams ?")
    st.caption(
        f"Moyenne mensuelle du cours depuis {start_year} (mois en cours exclu, car pas terminé). "
        f"Pour un exportateur payé en {currency}, le meilleur mois est celui où 1 {currency} "
        "rapportait le plus de dirhams. C'est un constat sur le passé, pas une prévision."
    )
    period = monthly[monthly["month_start"].dt.year >= start_year]
    best, worst = fx_data.best_and_worst_months(period, currency)
    month_columns = {
        "month_start": st.column_config.DateColumn("Mois", format="MM/YYYY"),
        "avg_mad_per_unit": st.column_config.NumberColumn("Cours moyen (MAD)", format="%.4f"),
        "n_days": "Jours cotés",
    }
    col_best, col_worst = st.columns(2)
    col_best.markdown("**5 meilleurs mois**")
    col_best.dataframe(
        best[["month_start", "avg_mad_per_unit", "n_days"]],
        hide_index=True,
        column_config=month_columns,
    )
    col_worst.markdown("**5 pires mois**")
    col_worst.dataframe(
        worst[["month_start", "avg_mad_per_unit", "n_days"]],
        hide_index=True,
        column_config=month_columns,
    )

    season = fx_data.seasonality(monthly, currency, since_year=start_year)
    if season.empty:
        st.info("Pas assez d'années complètes pour calculer une saisonnalité.")
    else:
        n_years = int(season["n_years"].max())
        fig = px.bar(
            season,
            x="month_name",
            y="avg_gap_pct",
            labels={"month_name": "", "avg_gap_pct": "Écart moyen à la moyenne de l'année (%)"},
            title=f"Saisonnalité : écart moyen de chaque mois ({n_years} années complètes)",
        )
        st.plotly_chart(fig)
        st.caption(
            "Une barre positive veut dire que ce mois était en moyenne au-dessus de la moyenne "
            "de son année. Des écarts petits (moins de 1 %) sont surtout du bruit."
        )

# ---------------------------------------------------------------- Q2: volatility
with tab_vol:
    chosen = st.multiselect(
        "Devises", currencies, default=[c for c in ("EUR", "USD") if c in currencies]
    )
    since = st.select_slider(
        "Depuis", options=years, value=max(years[0], years[-1] - 10), key="vol_since"
    )
    rows = volatility[
        volatility["currency"].isin(chosen) & (volatility["rate_date"].dt.year >= since)
    ]
    fig = px.line(
        rows,
        x="rate_date",
        y="volatility_30d_pct",
        color="currency",
        labels={"rate_date": "", "volatility_30d_pct": "Volatilité 30 jours (%)", "currency": ""},
    )
    st.plotly_chart(fig)
    st.caption(
        "Volatilité = écart-type des variations quotidiennes sur les 30 derniers jours "
        "(au moins 10 cotations). Plus elle est haute, plus le cours bouge d'un jour à l'autre."
    )
    st.subheader("Volatilité médiane par devise, depuis le 13/04/2015")
    since_basket = volatility[volatility["rate_date"] >= "2015-04-13"]
    medians = (
        since_basket.groupby("currency")["volatility_30d_pct"].median().sort_values().reset_index()
    )
    fig = px.bar(
        medians,
        x="currency",
        y="volatility_30d_pct",
        labels={"currency": "", "volatility_30d_pct": "Volatilité médiane 30 jours (%)"},
    )
    st.plotly_chart(fig)
    st.caption(
        "Depuis le 13/04/2015, le dirham est piloté par un panier 60 % EUR / 40 % USD : "
        "les devises à gauche sont celles qui bougent le moins face au dirham."
    )
    st.subheader("Variations de plus de 5 % en un jour")
    st.dataframe(
        large_moves.sort_values("rate_date", ascending=False)[
            ["rate_date", "currency", "previous_date", "mad_per_unit", "pct_change_1d"]
        ],
        hide_index=True,
        column_config={
            "rate_date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            "currency": "Devise",
            "previous_date": st.column_config.DateColumn(
                "Cotation précédente", format="DD/MM/YYYY"
            ),
            "mad_per_unit": st.column_config.NumberColumn("MAD pour 1 unité", format="%.4f"),
            "pct_change_1d": st.column_config.NumberColumn("Variation", format="%+.2f %%"),
        },
    )

# ---------------------------------------------------------------- Q4: basket
with tab_basket:
    st.subheader("Indice du panier EUR / USD (base 100 le 13/04/2015)")
    fig = px.line(
        basket, x="rate_date", y="basket_index", labels={"rate_date": "", "basket_index": "Indice"}
    )
    fig.add_hline(y=100, line_dash="dot")
    st.plotly_chart(fig)
    latest = basket.sort_values("rate_date").iloc[-1]
    st.markdown(
        f"Dernière valeur : **{latest['basket_index']:.2f}** le {latest['rate_date']:%d/%m/%Y}. "
        "Au-dessus de 100 : il faut plus de dirhams qu'en avril 2015 pour acheter le panier "
        "(le dirham s'est affaibli face au panier) ; en dessous : il s'est renforcé."
    )
    st.info(
        "Pondérations officielles : **60 % EUR, 40 % USD** depuis le 13/04/2015, d'après la page "
        f"[Historique du régime de change]({BASKET_SOURCE}) de Bank Al-Maghrib. Cette page ne "
        "donne pas la formule exacte du cours central : cet indice est une **reconstruction "
        "illustrative** (moyenne géométrique pondérée), pas un chiffre officiel."
    )

# ---------------------------------------------------------------- Q5: data quality
with tab_quality:
    st.subheader("Contrôles du dernier passage du pipeline")
    shown = report.sort_values("check_order").assign(
        status=lambda d: d["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}")
    )
    st.dataframe(
        shown[["check_name", "metric_value", "status", "details"]],
        hide_index=True,
        column_config={
            "check_name": "Contrôle",
            "metric_value": st.column_config.NumberColumn("Valeur", format="%g"),
            "status": "Statut",
            "details": "Détail",
        },
    )
    st.caption(
        "🟢 ok · 🔵 information · 🟠 à surveiller · 🔴 erreur (en cas d'erreur, le pipeline "
        "s'arrête et ne publie pas de données)."
    )

    st.subheader("Jours sans cotation, par année et par raison")
    reasons = {
        "weekend": "Week-end",
        "public_holiday": "Jour férié",
        "public_holiday_estimated": "Fête religieuse (date estimée ±1 j)",
        "business_day_without_quote": "Jour ouvré sans cotation (inexpliqué)",
    }
    per_year = fx_data.gaps_per_year(gaps)
    per_year["gap_reason"] = per_year["gap_reason"].map(reasons).fillna(per_year["gap_reason"])
    fig = px.bar(
        per_year,
        x="year",
        y="n_days",
        color="gap_reason",
        labels={"year": "", "n_days": "Jours", "gap_reason": ""},
        color_discrete_map={  # normal gaps in calm colours, the ones to check in red
            reasons["weekend"]: "#c7c7c7",
            reasons["public_holiday"]: "#9ecae1",
            reasons["public_holiday_estimated"]: "#3182bd",
            reasons["business_day_without_quote"]: "#d62728",
        },
    )
    fig.update_layout(legend={"orientation": "h", "y": -0.15})
    st.plotly_chart(fig)
    st.caption(
        "Un trou n'est pas forcément une erreur : Bank Al-Maghrib ne publie pas le week-end ni "
        "les jours fériés. Seuls les jours ouvrés sans cotation sont à surveiller. Les jours "
        "fériés viennent du paquet Python `holidays`."
    )

    st.subheader("Couverture par devise")
    st.dataframe(
        coverage.sort_values("currency")[
            ["currency", "first_date", "last_date", "n_days", "n_missing_days", "coverage_status"]
        ],
        hide_index=True,
        column_config={
            "currency": "Devise",
            "first_date": st.column_config.DateColumn("Première date", format="DD/MM/YYYY"),
            "last_date": st.column_config.DateColumn("Dernière date", format="DD/MM/YYYY"),
            "n_days": "Jours cotés",
            "n_missing_days": "Jours manquants",
            "coverage_status": "Statut",
        },
    )
