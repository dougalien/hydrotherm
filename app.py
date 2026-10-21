"""
Data Center Water vs. Climate-Driven ET — a hand-checkable comparison tool.

Single-file Streamlit app. All physics is closed-form so every number can be
reproduced with a calculator. Every panel has a "hand calculation" expander
that shows the equation with the student's numbers substituted.

Run:  streamlit run app.py
"""

import math

import pandas as pd
import io
import csv

import streamlit as st
import plotly.graph_objects as go
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from figtools import show_figure, to_png

# ---------------------------------------------------------------------------
# Constants (SI)
# ---------------------------------------------------------------------------
RHO_W = 1000.0          # kg/m^3, density of liquid water (constant approximation)
CP_W = 4186.0           # J/(kg K), specific heat of liquid water
SEC_PER_YR = 365.0 * 86400.0
HR_PER_YR = 8760.0
J_PER_MWH = 3.6e9

COLOR_DC = "#2a78d6"    # series 1 (data center)
COLOR_ET = "#eb6834"    # series 2 (ET)


def latent_heat(t_c: float) -> float:
    """Latent heat of vaporization of water, J/kg. Linear fit valid ~0-40 C:
    L = 2.501e6 - 2361*T  (T in C)."""
    return 2.501e6 - 2361.0 * t_c


def cc_rate(t_c: float) -> float:
    """Clausius-Clapeyron fractional rate d(ln e_s)/dT, per K, from the
    Tetens/Magnus form e_s = 0.6108 exp(17.27 T / (T + 237.3))."""
    return 17.27 * 237.3 / (t_c + 237.3) ** 2


def fmt(x: float, unit: str = "", sig: int = 3) -> str:
    """Readable number: plain for moderate values, scientific otherwise."""
    if x == 0 or not math.isfinite(x):
        return f"{x} {unit}".strip()
    ax = abs(x)
    if 1e-3 <= ax < 1e6:
        s = f"{x:,.{max(sig - 1 - int(math.floor(math.log10(ax))), 0)}f}"
    else:
        s = f"{x:.{sig - 1}e}"
    return f"{s} {unit}".strip()


def md(text: str) -> None:
    """Markdown with hard line breaks, so each equation line stays on its own line."""
    st.markdown(text.replace("\n", "  \n"))


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.set_page_config(page_title="DC Water vs ET", layout="wide")
st.title("Data Center Cooling Water vs. Climate-Driven Evapotranspiration")
st.caption(
    "Simple energy-balance comparison. Both processes are the same physics: "
    "liquid water absorbing heat and leaving as vapor (latent heat). "
    "All default values are placeholders — replace them with reported data and cite the source. "
    "Tab 4 adds a climate-attribution impact factor based on the CO₂ from the facility's electricity, and tab 5 scales it to the whole data-center fleet."
)

with st.sidebar:
    st.header("Shared constants")
    t_water = st.number_input("Water / air temperature for latent heat (°C)", 0.0, 40.0, 25.0, 1.0)
    L = latent_heat(t_water)
    st.write(f"L = 2.501×10⁶ − 2361·T = **{fmt(L, 'J/kg')}**")
    st.write(f"ρ = {RHO_W:.0f} kg/m³, c = {CP_W:.0f} J/(kg·K)")
    st.write(f"1 mm/day of ET ≈ **{fmt(RHO_W * 1e-3 * L / 86400, 'W/m²')}** of latent heat flux")

tab_dc, tab_et, tab_cmp, tab_att, tab_fleet, tab_mix, tab_meth = st.tabs(
    ["1 · Data center", "2 · Evapotranspiration", "3 · Water stress comparison", "4 · Climate attribution",
     "5 · Fleet scale-up", "6 · Reservoir mixing", "7 · Methods & sources"]
)

# ---------------------------------------------------------------------------
# 1. Data center
# ---------------------------------------------------------------------------
with tab_dc:
    st.subheader("Data center heat rejection and water use")
    c1, c2, c3 = st.columns(3)
    with c1:
        it_mw = st.number_input("IT load, nameplate (MW)", 0.0, 10000.0, 100.0, 10.0)
        util = st.slider("Average utilization (% of nameplate)", 0, 100, 80) / 100
        pue = st.number_input("PUE (facility energy ÷ IT energy)", 1.0, 3.0, 1.2, 0.05)
    with c2:
        heat_basis = st.radio(
            "Heat that must be rejected",
            ["All facility power (IT × PUE) — upper bound", "IT power only"],
        )
        mode = st.radio("Water estimate method", ["Energy balance (latent heat)", "Reported WUE (L/kWh IT)"])
    with c3:
        if mode.startswith("Energy"):
            f_evap = st.slider("Fraction of heat removed by evaporation (%)", 0, 100, 80) / 100
            coc = st.number_input("Cooling-tower cycles of concentration", 1.5, 20.0, 4.0, 0.5)
            wue = None
        else:
            wue = st.number_input("Reported WUE (L per kWh of IT energy)", 0.0, 10.0, 1.8, 0.1)
            f_evap, coc = None, None
        include_indirect = st.checkbox("Include indirect (power-generation) water", False)
        grid_wi = st.number_input(
            "Grid water intensity, consumptive (L/kWh)", 0.0, 20.0, 2.0, 0.1,
            disabled=not include_indirect,
            help="Placeholder. Use a value for the regional generation mix from a cited source.",
        )

    it_energy_mwh = it_mw * util * HR_PER_YR
    fac_energy_mwh = it_energy_mwh * pue
    heat_mwh = fac_energy_mwh if heat_basis.startswith("All") else it_energy_mwh
    Q_dc = heat_mwh * J_PER_MWH                       # J/yr
    P_dc = Q_dc / SEC_PER_YR                          # W average

    if mode.startswith("Energy"):
        evap_m3 = f_evap * Q_dc / L / RHO_W           # m^3/yr consumed
        blowdown_m3 = evap_m3 / (coc - 1.0)           # m^3/yr discharged
        withdrawal_m3 = evap_m3 + blowdown_m3
        direct_m3 = evap_m3
    else:
        direct_m3 = wue * it_energy_mwh * 1000 / 1000  # L/kWh * kWh -> L -> m^3
        evap_m3, blowdown_m3, withdrawal_m3 = direct_m3, float("nan"), float("nan")

    indirect_m3 = grid_wi * fac_energy_mwh * 1000 / 1000 if include_indirect else 0.0
    total_dc_m3 = direct_m3 + indirect_m3

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Average heat rejected", fmt(P_dc / 1e6, "MW"))
    m2.metric("Direct water consumed", fmt(direct_m3 / 1e6, "Mm³/yr"))
    m3.metric("Indirect water", fmt(indirect_m3 / 1e6, "Mm³/yr") if include_indirect else "off")
    m4.metric("Direct per MWh heat", fmt(direct_m3 / heat_mwh if heat_mwh else 0, "m³/MWh"))
    if mode.startswith("Energy"):
        st.write(
            f"Blowdown (discharged, not consumed): **{fmt(blowdown_m3, 'm³/yr')}** · "
            f"Total withdrawal: **{fmt(withdrawal_m3, 'm³/yr')}**"
        )

    with st.expander("Hand calculation"):
        md(f"""
**Step 1 — energy.** IT energy = {fmt(it_mw)} MW × {util:.2f} × 8760 h = **{fmt(it_energy_mwh, 'MWh/yr')}**
Facility energy = IT × PUE = {fmt(it_energy_mwh)} × {pue} = **{fmt(fac_energy_mwh, 'MWh/yr')}**

**Step 2 — heat to reject.** Q = {fmt(heat_mwh, 'MWh')} × 3.6×10⁹ J/MWh = **{fmt(Q_dc, 'J/yr')}**
(average power = Q ÷ 3.1536×10⁷ s = {fmt(P_dc / 1e6, 'MW')})
""")
        if mode.startswith("Energy"):
            md(f"""
**Step 3 — evaporation.** m = f · Q / L = {f_evap:.2f} × {fmt(Q_dc)} ÷ {fmt(L)} = {fmt(evap_m3 * RHO_W, 'kg/yr')}
Volume = mass ÷ 1000 kg/m³ = **{fmt(evap_m3, 'm³/yr')}**

**Step 4 — blowdown.** B = E / (CoC − 1) = {fmt(evap_m3)} ÷ ({coc} − 1) = **{fmt(blowdown_m3, 'm³/yr')}**
Evaporation is *consumption*; blowdown is *withdrawn and returned* (usually to sewer).

Theoretical ceiling (100 % evaporative): 3.6×10⁹ ÷ {fmt(L)} ÷ 1000 = **{fmt(J_PER_MWH / L / RHO_W, 'm³ per MWh of heat')}**
""")
        else:
            md(f"""
**Step 3 — reported WUE.** V = WUE × IT energy = {wue} L/kWh × {fmt(it_energy_mwh * 1000, 'kWh')} = {fmt(direct_m3 * 1000, 'L')} = **{fmt(direct_m3, 'm³/yr')}**
""")
        if include_indirect:
            md(f"""
**Indirect.** V = {grid_wi} L/kWh × {fmt(fac_energy_mwh * 1000, 'kWh')} = **{fmt(indirect_m3, 'm³/yr')}**
""")

# ---------------------------------------------------------------------------
# 2. Evapotranspiration
# ---------------------------------------------------------------------------
with tab_et:
    st.subheader("Change in evapotranspiration over a basin or aquifer")
    et_mode = st.radio(
        "How is ΔET obtained?",
        ["Reported ΔET from the paper (preferred)", "Estimate from warming (ΔT) — upper bound"],
    )
    c1, c2 = st.columns(2)
    with c1:
        area_km2 = st.number_input("Area of basin / aquifer footprint (km²)", 0.01, 1.0e8, 1000.0, 100.0)
        et0 = st.number_input("Baseline actual ET (mm/yr)", 0.0, 3000.0, 600.0, 10.0,
                              help="Needed for the warming estimate and the reverse calculation.")
    with c2:
        if et_mode.startswith("Reported"):
            d_et_mm = st.number_input("Reported ΔET (mm/yr)", 0.0, 1000.0, 20.0, 1.0)
            sens = None
            dT = None
        else:
            dT = st.number_input("Warming ΔT (°C)", 0.0, 10.0, 1.0, 0.1)
            cc = cc_rate(t_water)
            use_cc = st.checkbox(f"Use Clausius–Clapeyron rate ({cc * 100:.1f} %/°C at {t_water:.0f} °C)", True)
            sens = cc if use_cc else st.number_input("ET sensitivity (%/°C)", 0.0, 10.0, 2.0, 0.1) / 100
            d_et_mm = et0 * sens * dT

    area_m2 = area_km2 * 1e6
    d_et_m3 = d_et_mm / 1000 * area_m2
    P_et = d_et_m3 * RHO_W * L / SEC_PER_YR

    # sensitivity for the reverse calc (always available)
    sens_rev = sens if sens is not None else cc_rate(t_water)

    m1, m2, m3 = st.columns(3)
    m1.metric("ΔET", fmt(d_et_mm, "mm/yr"))
    m2.metric("ΔET volume", fmt(d_et_m3 / 1e6, "Mm³/yr"))
    m3.metric("Equivalent latent heat", fmt(P_et / 1e6, "MW"))
    if not et_mode.startswith("Reported"):
        st.warning(
            "Clausius–Clapeyron scaling describes saturation vapor pressure, not actual ET. "
            "In water-limited basins actual ET rises much less, or not at all. Treat this as an upper bound."
        )

    with st.expander("Hand calculation"):
        if not et_mode.startswith("Reported"):
            md(f"""
**Step 0 — ΔET from warming.** ΔET = ET₀ × s × ΔT = {et0} mm/yr × {sens:.4f} /°C × {dT} °C = **{fmt(d_et_mm, 'mm/yr')}**
(Clausius–Clapeyron: s = 17.27 × 237.3 ÷ (T + 237.3)² = {cc_rate(t_water):.4f} /°C at {t_water:.0f} °C)
""")
        md(f"""
**Step 1 — volume.** V = ΔET × A = ({fmt(d_et_mm)} ÷ 1000) m × {fmt(area_m2, 'm²')} = **{fmt(d_et_m3, 'm³/yr')}**

**Step 2 — energy.** E = ρ V L = 1000 × {fmt(d_et_m3)} × {fmt(L)} = {fmt(d_et_m3 * RHO_W * L, 'J/yr')}
Average power = E ÷ 3.1536×10⁷ s = **{fmt(P_et / 1e6, 'MW')}**
""")

# ---------------------------------------------------------------------------
# 3. Comparison
# ---------------------------------------------------------------------------
with tab_cmp:
    st.subheader("Same units, same scale")
    ratio = total_dc_m3 / d_et_m3 if d_et_m3 > 0 else float("inf")
    area_equiv_km2 = total_dc_m3 / (d_et_mm / 1000) / 1e6 if d_et_mm > 0 else float("inf")
    base_et_m3_per_c = et0 / 1000 * area_m2 * sens_rev   # m^3/yr per degC
    dT_equiv = total_dc_m3 / base_et_m3_per_c if base_et_m3_per_c > 0 else float("inf")

    m1, m2, m3 = st.columns(3)
    m1.metric("Data center ÷ ΔET", fmt(ratio) if math.isfinite(ratio) else "∞")
    m2.metric("Equivalent area", fmt(area_equiv_km2, "km²") if math.isfinite(area_equiv_km2) else "—",
              help="Area over which the ΔET equals the data center water")
    m3.metric("Equivalent warming", fmt(dT_equiv, "°C") if math.isfinite(dT_equiv) else "—",
              help="Warming over the chosen area whose extra ET equals the data center water")

    labels, vals, colors = ["Data center — direct"], [direct_m3], [COLOR_DC]
    if include_indirect:
        labels += ["Data center — indirect", "Data center — total"]
        vals += [indirect_m3, total_dc_m3]
        colors += [COLOR_DC, COLOR_DC]
    labels.append(f"ΔET over {fmt(area_km2)} km²")
    vals.append(d_et_m3)
    colors.append(COLOR_ET)

    plot_vals = [max(v, 1e-9) for v in vals]
    fig = go.Figure(go.Bar(
        x=plot_vals, y=labels, orientation="h", marker_color=colors,
        text=[fmt(v, "m³/yr") for v in vals], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{text}<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(type="log", title="Water volume (m³/yr, log scale)", gridcolor="rgba(128,128,128,0.2)"),
        yaxis=dict(autorange="reversed"),
        height=120 + 60 * len(labels), margin=dict(l=10, r=130, t=10, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False, bargap=0.45,
    )
    st.plotly_chart(fig, width="stretch")
    st.caption("Log scale: equal distances are equal ratios (1M to 10M is a factor of 10). Blue = data center, orange = ΔET.")

    st.table({
        "Quantity": ["Data center (counted)", "ΔET over area"],
        "Water (m³/yr)": [fmt(total_dc_m3), fmt(d_et_m3)],
        "Latent-heat equivalent (MW)": [fmt(total_dc_m3 * RHO_W * L / SEC_PER_YR / 1e6), fmt(P_et / 1e6)],
    })

    with st.expander("Hand calculation"):
        md(f"""
**Ratio** = {fmt(total_dc_m3)} ÷ {fmt(d_et_m3)} = **{fmt(ratio)}**

**Equivalent area** — the area over which the ΔET equals the data center's water:
A* = V_DC ÷ ΔET = {fmt(total_dc_m3)} m³ ÷ {fmt(d_et_mm / 1000)} m = {fmt(area_equiv_km2 * 1e6, 'm²')} = **{fmt(area_equiv_km2, 'km²')}**

**Reverse (equivalent warming)** — the warming over the chosen area whose extra ET equals the data center's water:
ΔT* = V_DC ÷ (ET₀ × A × s) = {fmt(total_dc_m3)} ÷ ({et0 / 1000} m × {fmt(area_m2)} m² × {sens_rev:.4f}) = **{fmt(dT_equiv, '°C')}**
(uses {'the sensitivity from tab 2' if sens is not None else 'the Clausius–Clapeyron rate, an upper-bound sensitivity, so ΔT* is a lower bound'})
""")
    st.info(
        "Interpretation depends on the area chosen. The comparison speaks to groundwater only if the "
        "data center draws groundwater from that same aquifer."
    )

# ---------------------------------------------------------------------------
# 4. Climate attribution
# ---------------------------------------------------------------------------
EMISSION_FACTORS = {  # tCO2 per MWh. Lifecycle medians, IPCC AR5 WG3 Annex III; the grid value is a placeholder.
    "Average grid (placeholder)": 0.40,
    "Coal": 0.82,
    "Natural gas (combined cycle)": 0.49,
    "Nuclear": 0.012,
    "Wind (onshore)": 0.011,
    "Solar PV (utility)": 0.048,
    "Custom": None,
}
TCRE_LOW, TCRE_HIGH, S_LOW = 0.27, 0.63, 0.02  # AR6 likely range of TCRE; low ET sensitivity for water-limited land

with tab_att:
    st.subheader("Impact factor: extra ET attributable to the CO₂ from the electricity")
    st.caption(
        "Chain: electricity → CO₂ → warming (TCRE) → extra ET → groundwater stress. Warming is global, so the result is a "
        "proportional share of a diffuse effect, not a locally measurable one."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Electricity and its CO₂**")
        basis = st.radio("Electricity basis", ["Facility energy from tab 1", "Enter MWh/yr"])
        att_mwh = fac_energy_mwh if basis.startswith("Facility") else st.number_input(
            "Electricity (MWh/yr)", 0.0, 1.0e8, 800000.0, 10000.0)
        src_a = st.selectbox("Main source", list(EMISSION_FACTORS), 0)
        ef_a = EMISSION_FACTORS[src_a] if EMISSION_FACTORS[src_a] is not None else st.number_input(
            "Emission factor A (tCO₂/MWh)", 0.0, 2.0, 0.40, 0.01)
        src_b = st.selectbox("Second source", list(EMISSION_FACTORS), 3)
        ef_b = EMISSION_FACTORS[src_b] if EMISSION_FACTORS[src_b] is not None else st.number_input(
            "Emission factor B (tCO₂/MWh)", 0.0, 2.0, 0.01, 0.01)
        share_b = st.slider("Share of electricity from the second source (%)", 0, 100, 0) / 100
        ef_mix = (1 - share_b) * ef_a + share_b * ef_b
        st.caption("Additionality matters: new clean supply lowers the factor, but re-labelling existing clean power "
                   "does not change grid emissions.")
    with c2:
        st.markdown("**Climate response**")
        tcre = st.number_input("TCRE (°C per 1000 GtCO₂)", 0.05, 1.5, 0.45, 0.01,
                               help="IPCC AR6: 0.45, likely range 0.27–0.63.")
        s_mode = st.radio("ET sensitivity to warming",
                          ["Clausius–Clapeyron (upper bound)", f"Water-limited land ({S_LOW * 100:.0f} %/°C)", "Custom"])
        if s_mode.startswith("Clausius"):
            s_att = cc_rate(t_water)
        elif s_mode.startswith("Water"):
            s_att = S_LOW
        else:
            s_att = st.number_input("ET sensitivity (%/°C)", 0.0, 10.0, 3.0, 0.1) / 100
        horizon = st.number_input("Persistence horizon (years)", 1, 1000, 100, 10,
                                  help="Warming from a CO₂ pulse stays about constant for centuries, so extra ET repeats each year.")
    with c3:
        st.markdown("**Where the ET change lands**")
        glob_et_km3 = st.number_input("Global land ET (km³/yr)", 1000.0, 200000.0, 65000.0, 1000.0)
        land_km2 = st.number_input("Global land area (km²)", 1.0e6, 1.0e9, 1.49e8, 1.0e6, format="%.3g")
        st.write(f"Basin area from tab 2: **{fmt(area_km2, 'km²')}**")
        st.write(f"Share of land: **{fmt(area_km2 / land_km2)}**")

    glob_et_m3 = glob_et_km3 * 1e9

    def impact_per_mwh(ef, tcre_v, s_v):
        """Extra global ET over the horizon from one MWh, m³ per MWh."""
        return ef * tcre_v / 1e12 * s_v * glob_et_m3 * horizon

    co2_t = att_mwh * ef_mix
    warm_c = co2_t * tcre / 1e12
    et_yr_m3 = warm_c * s_att * glob_et_m3                  # extra global ET each year, persistent
    et_hor_m3 = et_yr_m3 * horizon
    local_hor_m3 = et_hor_m3 * area_km2 / land_km2
    if_mwh = impact_per_mwh(ef_mix, tcre, s_att)
    direct_per_mwh = direct_m3 / fac_energy_mwh if fac_energy_mwh else 0.0
    ratio_att = et_hor_m3 / direct_m3 if direct_m3 and math.isfinite(direct_m3) else float("inf")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("CO₂ per year", fmt(co2_t, "t"))
    m2.metric("Warming per year of operation", fmt(warm_c, "°C"))
    m3.metric(f"Impact factor ({horizon} yr)", fmt(if_mwh, "m³/MWh"), help="Extra global ET per MWh of electricity")
    m4.metric("Share landing on tab 2 area", fmt(local_hor_m3, "m³"), help=f"Over {horizon} years, by area share")
    st.write(
        f"Extra global ET from one operating year of emissions: **{fmt(et_yr_m3, 'm³/yr')}** each year, "
        f"**{fmt(et_hor_m3 / 1e6, 'Mm³')}** over {horizon} years. "
        f"Direct cooling water for that same year (tab 1): **{fmt(direct_m3 / 1e6, 'Mm³')}**"
        + (f", ratio induced ÷ direct = **{fmt(ratio_att)}**." if math.isfinite(ratio_att) else ".")
    )

    # impact factor by source, with an uncertainty range, next to the direct cooling water per MWh
    names = [k for k, v in EMISSION_FACTORS.items() if v is not None]
    central = [impact_per_mwh(EMISSION_FACTORS[k], tcre, s_att) for k in names]
    low = [impact_per_mwh(EMISSION_FACTORS[k], TCRE_LOW, S_LOW) for k in names]
    high = [impact_per_mwh(EMISSION_FACTORS[k], TCRE_HIGH, cc_rate(t_water)) for k in names]
    vals = central + [direct_per_mwh]
    labels = [f"{n}: {fmt(v, 'm³/MWh')}" for n, v in zip(names + ["Direct cooling water (local, tab 1)"], vals)]
    fig3 = go.Figure(go.Bar(
        x=[max(v, 1e-6) for v in vals], y=labels, orientation="h",
        marker_color=[COLOR_DC] * len(names) + [COLOR_ET],
        error_x=dict(type="data", symmetric=False,
                     array=[max(h - c, 0) for h, c in zip(high, central)] + [0],
                     arrayminus=[max(c - l, 0) for l, c in zip(low, central)] + [0], color="gray"),
        hovertemplate="%{y}<extra></extra>",
    ))
    fig3.update_layout(
        xaxis=dict(type="log", title="Water per MWh (m³/MWh, log scale)", gridcolor="rgba(128,128,128,0.2)"),
        yaxis=dict(autorange="reversed"), height=120 + 55 * len(labels), margin=dict(l=10, r=20, t=10, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False, bargap=0.4,
    )
    st.plotly_chart(fig3, width="stretch")
    st.caption(
        f"Blue: extra global ET over {horizon} years per MWh, by electricity source (bars use your TCRE and sensitivity; "
        f"whiskers span TCRE {TCRE_LOW}–{TCRE_HIGH} with {S_LOW * 100:.0f} %/°C up to Clausius–Clapeyron). "
        "Orange: direct cooling water for this facility. Blue is global and spread out; orange is local."
    )
    st.table({
        "Source": names,
        "tCO₂/MWh": [f"{EMISSION_FACTORS[k]:.3g}" for k in names],
        "Impact factor, central (m³/MWh)": [fmt(c) for c in central],
        "Low (m³/MWh)": [fmt(v) for v in low],
        "High (m³/MWh)": [fmt(v) for v in high],
    })

    with st.expander("Hand calculation"):
        md(f"""
**Step 1 — CO₂.** Emission factor = (1 − {share_b:.2f}) × {ef_a:.3g} + {share_b:.2f} × {ef_b:.3g} = **{ef_mix:.3g} tCO₂/MWh**
Mass = {fmt(att_mwh, 'MWh/yr')} × {ef_mix:.3g} = **{fmt(co2_t, 't/yr')}**

**Step 2 — warming (TCRE).** ΔT = M × TCRE ÷ 10¹² t = {fmt(co2_t)} × {tcre} ÷ 10¹² = **{fmt(warm_c, '°C')}**
(1000 GtCO₂ = 10¹² t, so a TCRE of {tcre} °C per 1000 GtCO₂ is {tcre / 1e12:.3g} °C per tonne)

**Step 3 — extra ET.** Global land ET = {fmt(glob_et_m3, 'm³/yr')}. Fractional rise = s × ΔT = {s_att:.4f} × {fmt(warm_c)} = {fmt(s_att * warm_c)}
Extra ET = {fmt(glob_et_m3)} × {fmt(s_att * warm_c)} = **{fmt(et_yr_m3, 'm³/yr')}**, repeating every year the warming persists.

**Step 4 — horizon and per MWh.** Over {horizon} yr: {fmt(et_yr_m3)} × {horizon} = **{fmt(et_hor_m3, 'm³')}**
Impact factor = {fmt(et_hor_m3)} ÷ {fmt(att_mwh)} MWh = **{fmt(if_mwh, 'm³/MWh')}**

**Step 5 — share on the tab 2 area.** {fmt(et_hor_m3)} × ({fmt(area_km2)} ÷ {fmt(land_km2)} km²) = **{fmt(local_hor_m3, 'm³')}**
""")
    st.info(
        "This assigns a proportional share of warming-driven ET to the facility. It is not a measurable local effect. "
        "Extra ET is not the same as lost water: evaporated water returns as precipitation somewhere, and groundwater is "
        "depleted only where recharge does not rise with ET (Condon et al. 2020). Treat the factor as accurate to about "
        "a factor of 3 to 5."
    )

# ---------------------------------------------------------------------------
# 5. Fleet scale-up
# ---------------------------------------------------------------------------
FLEET_PRESETS = {  # base year, base TWh, target year, target TWh (IEA Energy and AI 2025; LBNL 2024)
    "IEA global (2024 → 2030)": (2024, 415.0, 2030, 945.0),
    "US, LBNL low (2023 → 2028)": (2023, 176.0, 2028, 325.0),
    "US, LBNL high (2023 → 2028)": (2023, 176.0, 2028, 580.0),
    "Custom": (2024, 415.0, 2030, 945.0),
}
END_YEAR = 2050
CLEAN_EF = 0.012  # tCO2/MWh, nuclear/wind-like supply

with tab_fleet:
    st.subheader("Fleet scale-up: all data centers added together")
    st.caption(
        "Because the impact factor is linear in electricity, the same calculation works for one facility or the whole sector. "
        "Warming comes from cumulative CO₂, so each year's fleet emissions add to the warming of the years before. "
        "TCRE, ET sensitivity and global ET come from tab 4."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Fleet electricity**")
        growth_model = st.selectbox(
            "Growth model",
            ["Anchors + steady growth", "LBNL US scenario path", "Logistic S-curve fitted to US history",
             "Exponential fitted to US history"],
            help="The last three use the US history table below and replace the starting point and anchors.")
        use_us = not growth_model.startswith("Anchors")
        st.caption("US models start in 2014 and use the LBNL history. The starting point below applies only to 'Anchors + steady growth'.")
        preset = st.selectbox("Starting point", list(FLEET_PRESETS))
        p_by, p_bt, p_ty, p_tt = FLEET_PRESETS[preset]
        base_year = int(st.number_input("Base year", 2000, 2040, p_by, 1, key=f"fy_{preset}"))
        base_twh = st.number_input("Base-year electricity (TWh/yr)", 1.0, 50000.0, p_bt, 10.0, key=f"fb_{preset}")
        target_year = int(st.number_input("Target year", base_year + 1, 2049, max(p_ty, base_year + 1), 1, key=f"fty_{preset}"))
        target_twh = st.number_input("Target-year electricity (TWh/yr)", 1.0, 100000.0, p_tt, 10.0, key=f"ft_{preset}")
        g_after = st.slider(f"Growth after {target_year} (%/yr)", -10.0, 20.0, 3.0, 0.5) / 100
    with c2:
        st.markdown("**Emissions**")
        ef_base = st.number_input("Grid emission factor, base year (tCO₂/MWh)", 0.0, 1.5, 0.50 if use_us else 0.45, 0.01, key=f"efb_{use_us}",
                                  help="World average is roughly 0.45. Use a regional value for a regional fleet.")
        ef_end = st.number_input(f"Grid emission factor, {END_YEAR} (tCO₂/MWh)", 0.0, 1.5, 0.20, 0.01,
                                 help="Illustrative decarbonization. Linear between the two years.")
        clean_share = st.slider("Share of fleet electricity on new clean supply (%)", 0, 100, 0,
                                help=f"Treated as {CLEAN_EF} tCO₂/MWh in every year.") / 100
        glob_co2_mt = st.number_input("Global CO₂ emissions today (Mt/yr)", 1000.0, 100000.0, 37000.0, 1000.0,
                                      help="Roughly 37 Gt from fossil fuels. For context only.")
    with c3:
        st.markdown("**Water**")
        dw_mode = st.radio("Direct cooling water intensity",
                           ["Fleet average (0.37 L/kWh)", "Tab 1 facility value", "Custom"])
        if dw_mode.startswith("Fleet"):
            dw = 0.37
        elif dw_mode.startswith("Tab 1"):
            dw = direct_per_mwh
        else:
            dw = st.number_input("Direct water (L/kWh)", 0.0, 10.0, 0.5, 0.05)
        st.caption("Fleet average = LBNL 2023 US direct water (about 66 billion L) ÷ 176 TWh. "
                   "L/kWh and m³/MWh are the same number.")
        incl_ind = st.checkbox("Also show indirect (power-generation) water", False)
        iw = st.number_input("Indirect water (L/kWh)", 0.0, 20.0, 4.5, 0.1, disabled=not incl_ind,
                             help="LBNL 2023: about 800 billion L ÷ 176 TWh. It includes hydropower reservoir evaporation, which is disputed.")
        dT_obs = st.number_input("Warming so far (°C)", 0.1, 3.0, 1.3, 0.1,
                                 help="Used to compare the sector with all warming-driven ET.")

    # --- US history and growth-trend models -----------------------------------
    st.markdown("**US data center electricity: history, fitted trends and scenarios**")
    LBNL_HIST = {2014: 58, 2015: 61, 2016: 64, 2017: 70, 2018: 76, 2019: 89, 2020: 106, 2021: 128, 2022: 151, 2023: 176}
    LBNL_LOW = {2023: 176, 2024: 187, 2025: 204, 2026: 243, 2027: 283, 2028: 325}
    LBNL_HIGH = {2023: 176, 2024: 234, 2025: 309, 2026: 406, 2027: 484, 2028: 580}

    def ols(xs, ys):
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        return my - b * mx, b

    t1, t2 = st.columns([1, 2])
    with t1:
        with st.expander("US history table (editable)"):
            st.caption("LBNL 2024 report, Fig. 5.5. The report gives 58 (2014), 76 (2018) and 176 (2023); other years were read off "
                       "the chart and are good to about ±3 TWh. 2024–2028 scenario bounds are read the same way, with the "
                       "2028 endpoints (325 and 580) stated in the report.")
            hist_df = st.data_editor(pd.DataFrame({"Year": list(LBNL_HIST), "TWh": [float(v) for v in LBNL_HIST.values()]}),
                                     hide_index=True, num_rows="dynamic", key="us_hist_editor")
        hist = {int(r.Year): float(r.TWh) for r in hist_df.dropna().itertuples() if r.TWh > 0}
        hist_years = sorted(hist)
        scen = st.selectbox("LBNL scenario path (used if chosen as the model)", ["Low", "Middle", "High"], 1)
        win0 = st.slider("Fit window starts in", hist_years[0], hist_years[-1] - 3, max(2018, hist_years[0]),
                         help="2014–2016 was flat; the fast growth that matters for projections starts about 2017–2018.")
        ceiling = st.number_input("Logistic ceiling (TWh/yr)", 200.0, 5000.0, 800.0, 50.0,
                                  help="Upper limit for the S-curve. For scale, LBNL's high case is 580 TWh in 2028, about 12 % "
                                       "of forecast US electricity (roughly 4,850 TWh).")
        cap_exp = st.checkbox("Cap the exponential fit at the ceiling", True)
    fit_years = [y for y in hist_years if y >= win0]
    fit_vals = [hist[y] for y in fit_years]
    e_a, e_b = ols(fit_years, [math.log(v) for v in fit_vals])          # ln P = a + b t
    logistic_ok = ceiling > 1.02 * max(hist.values())
    if logistic_ok:
        l_a, l_b = ols(fit_years, [math.log(v / (ceiling - v)) for v in fit_vals])  # logit(P/K) = a + r t

    def mid_path(y):
        lo, hi = LBNL_LOW[min(max(y, 2023), 2028)], LBNL_HIGH[min(max(y, 2023), 2028)]
        return {"Low": lo, "High": hi, "Middle": (lo + hi) / 2}[scen]

    def us_scenario(y):
        if y <= 2028:
            return mid_path(y)
        return mid_path(2028) * (1 + g_after) ** (y - 2028)

    def us_exponential(y):
        v = math.exp(e_a + e_b * y)
        return min(v, ceiling) if cap_exp else v

    def us_logistic(y):
        return ceiling / (1 + math.exp(-(l_a + l_b * y))) if logistic_ok else float("nan")

    def us_twh(y):
        if y in hist:
            return hist[y]
        if growth_model.startswith("LBNL"):
            return us_scenario(y)
        if growth_model.startswith("Logistic"):
            return us_logistic(y)
        return us_exponential(y)

    with t2:
        xs_all = list(range(hist_years[0], END_YEAR + 1))
        logy = st.checkbox("Log scale", False, key="trend_log")
        figt = go.Figure()
        figt.add_trace(go.Scatter(x=list(range(2023, 2029)) + list(range(2028, 2022, -1)),
                                  y=[LBNL_LOW[y] for y in range(2023, 2029)] + [LBNL_HIGH[y] for y in range(2028, 2022, -1)],
                                  mode="lines", fill="toself", fillcolor="rgba(128,128,128,0.25)", line=dict(width=0),
                                  name="LBNL 2024 range", hoverinfo="skip"))
        figt.add_trace(go.Scatter(x=hist_years, y=[hist[y] for y in hist_years], mode="lines+markers", name="History (LBNL)",
                                  line=dict(color="black", width=3)))
        figt.add_trace(go.Scatter(x=[y for y in xs_all if y >= hist_years[-1]], y=[us_exponential(y) for y in xs_all if y >= hist_years[-1]],
                                  mode="lines", name=f"Exponential fit from {win0} ({100 * (math.exp(e_b) - 1):.1f} %/yr)",
                                  line=dict(color=COLOR_ET, dash="dash", width=2)))
        if logistic_ok:
            figt.add_trace(go.Scatter(x=[y for y in xs_all if y >= hist_years[-1]], y=[us_logistic(y) for y in xs_all if y >= hist_years[-1]],
                                      mode="lines", name=f"Logistic, ceiling {ceiling:,.0f} TWh", line=dict(color=COLOR_DC, dash="dash", width=2)))
        figt.add_trace(go.Scatter(x=[y for y in xs_all if y >= 2023], y=[us_scenario(y) for y in xs_all if y >= 2023], mode="lines",
                                  name=f"LBNL {scen.lower()} path, then {g_after * 100:.1f} %/yr", line=dict(color="gray", dash="dot", width=2)))
        figt.update_layout(
            xaxis=dict(title="Year", gridcolor="rgba(128,128,128,0.2)"),
            yaxis=dict(title="US data center electricity (TWh/yr)", gridcolor="rgba(128,128,128,0.2)", type="log" if logy else "linear"),
            height=380, margin=dict(l=10, r=10, t=10, b=40), legend=dict(orientation="h", y=-0.25),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(figt, width="stretch")
    cagr = lambda a_, b_: 100 * ((hist[b_] / hist[a_]) ** (1 / (b_ - a_)) - 1) if a_ in hist and b_ in hist and b_ > a_ else float("nan")
    st.caption(
        f"Growth in the history table: **{cagr(2014, 2018):.1f} %/yr** (2014–2018), **{cagr(2018, 2023):.1f} %/yr** (2018–2023). "
        f"Fitted exponential from {win0}: **{100 * (math.exp(e_b) - 1):.1f} %/yr**"
        + (f"; logistic midpoint year **{-l_a / l_b:.0f}**, rate **{l_b:.2f}** per year." if logistic_ok and l_b > 0 else ".")
        + " With about ten annual points the data cannot separate an exponential from an S-curve; the models differ mainly in "
          "what they assume about limits, so compare them rather than trusting one."
    )
    if not logistic_ok:
        st.warning("The logistic ceiling must be above the largest historical value.")
        if growth_model.startswith("Logistic"):
            st.stop()
    model_desc = {
        "anchors": f"Interpolation between years: E(y) = E₀ (E₁ ÷ E₀)^((y − y₀) ÷ (y₁ − y₀)) = {fmt(base_twh)} × ({fmt(target_twh)} ÷ {fmt(base_twh)})^(…); "
                   f"after {target_year} it grows at {g_after * 100:.1f} %/yr.",
        "lbnl": f"US history from the table through 2023, the LBNL {scen.lower()} path to 2028, then {g_after * 100:.1f} %/yr.",
        "logistic": f"US history through 2023, then E(y) = K ÷ (1 + e^(−(a + r y))) with K = {ceiling:,.0f} TWh fitted to {win0}–{hist_years[-1]}.",
        "exp": f"US history through 2023, then E(y) = e^(a + b y) with growth {100 * (math.exp(e_b) - 1):.1f} %/yr fitted to {win0}–{hist_years[-1]}"
               + (f", capped at {ceiling:,.0f} TWh." if cap_exp else "."),
    }
    model_desc = model_desc["anchors" if not use_us else ("lbnl" if growth_model.startswith("LBNL") else "logistic" if growth_model.startswith("Logistic") else "exp")]
    fleet_label = preset if not use_us else growth_model

    # --- year-by-year model ---------------------------------------------------
    def anchor_twh(y):
        if y <= target_year:
            return base_twh * (target_twh / base_twh) ** ((y - base_year) / (target_year - base_year))
        return target_twh * (1 + g_after) ** (y - target_year)

    start_year = hist_years[0] if use_us else base_year

    def fleet_twh(y):
        return us_twh(y) if use_us else anchor_twh(y)

    years = list(range(start_year, END_YEAR + 1))
    fl = []
    cum_t = 0.0
    for y in years:
        e_mwh = fleet_twh(y) * 1e6
        ef_grid = ef_base + (ef_end - ef_base) * (y - start_year) / (END_YEAR - start_year)
        ef_y = (1 - clean_share) * ef_grid + clean_share * CLEAN_EF
        co2_y = e_mwh * ef_y                                  # t
        cum_t += co2_y
        warm_y = cum_t * tcre / 1e12                          # °C, from cumulative CO2
        fl.append(dict(
            year=y, twh=e_mwh / 1e6, ef=ef_y, co2_mt=co2_y / 1e6, cum_gt=cum_t / 1e9, warm=warm_y,
            et_km3=warm_y * s_att * glob_et_km3, direct_km3=e_mwh * dw / 1e9,
            indirect_km3=e_mwh * iw / 1e9 if incl_ind else 0.0,
        ))
    first, last = fl[0], fl[-1]
    y2030 = next((r for r in fl if r["year"] == 2030), last)
    et_total_km3 = dT_obs * s_att * glob_et_km3               # all warming so far
    cum_direct = sum(r["direct_km3"] for r in fl)
    cum_et = sum(r["et_km3"] for r in fl)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Fleet CO₂, {first['year']}", fmt(first["co2_mt"], "Mt/yr"),
              help=f"{100 * first['co2_mt'] / glob_co2_mt:.2f} % of global emissions today")
    m2.metric(f"Fleet CO₂, {y2030['year']}", fmt(y2030["co2_mt"], "Mt/yr"),
              help=f"{100 * y2030['co2_mt'] / glob_co2_mt:.2f} % of today's global emissions")
    m3.metric(f"Warming added by {END_YEAR}", fmt(last["warm"], "°C"), help=f"Cumulative CO₂ {fmt(last['cum_gt'], 'Gt')}")
    m4.metric(f"Extra global ET, {END_YEAR}", fmt(last["et_km3"], "km³/yr"),
              help=f"{100 * last['et_km3'] / et_total_km3:.2f} % of all warming-driven ET so far")
    st.write(
        f"By {END_YEAR} the sector's cumulative CO₂ is **{fmt(last['cum_gt'], 'Gt')}**, which adds **{fmt(last['warm'], '°C')}** of "
        f"warming and **{fmt(last['et_km3'], 'km³/yr')}** of extra global ET, about "
        f"**{fmt(100 * last['et_km3'] / et_total_km3, '%')}** of the ET change from all {dT_obs} °C of warming "
        f"({fmt(et_total_km3, 'km³/yr')}). Direct cooling water in {END_YEAR}: **{fmt(last['direct_km3'], 'km³/yr')}**."
    )

    yrs = [r["year"] for r in fl]
    figf1 = go.Figure()
    figf1.add_trace(go.Scatter(x=yrs, y=[r["et_km3"] for r in fl], mode="lines", name="Extra global ET (from fleet CO₂)",
                               line=dict(color=COLOR_DC, width=3)))
    figf1.add_trace(go.Scatter(x=yrs, y=[r["direct_km3"] for r in fl], mode="lines", name="Direct cooling water",
                               line=dict(color=COLOR_ET, width=3)))
    if incl_ind:
        figf1.add_trace(go.Scatter(x=yrs, y=[r["indirect_km3"] for r in fl], mode="lines", name="Indirect (power generation) water",
                                   line=dict(color=COLOR_ET, width=2, dash="dash")))
    figf1.update_layout(
        xaxis=dict(title="Year", gridcolor="rgba(128,128,128,0.2)"),
        yaxis=dict(title="km³ per year", gridcolor="rgba(128,128,128,0.2)", rangemode="tozero"),
        height=360, margin=dict(l=10, r=10, t=30, b=40), legend=dict(orientation="h", y=1.12),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    figf2 = go.Figure(go.Bar(x=yrs, y=[r["co2_mt"] for r in fl], marker_color=COLOR_DC,
                             hovertemplate="%{x}: %{y:.0f} Mt<extra></extra>"))
    figf2.update_layout(
        xaxis=dict(title="Year"), yaxis=dict(title="Fleet CO₂ (Mt/yr)", gridcolor="rgba(128,128,128,0.2)"),
        height=360, margin=dict(l=10, r=10, t=30, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
    )
    g1, g2 = st.columns(2)
    g1.plotly_chart(figf1, width="stretch")
    g2.plotly_chart(figf2, width="stretch")
    st.caption("Left: extra global ET driven by the fleet's cumulative CO₂ (blue) against the water the fleet evaporates directly "
               "(orange). Blue is global and spread out; orange is where the facilities are. Right: fleet emissions per year.")

    pick = [r for r in fl if r["year"] in (first["year"], 2030, 2040, 2050)]
    st.table({
        "Year": [r["year"] for r in pick],
        "Electricity (TWh)": [fmt(r["twh"]) for r in pick],
        "tCO₂/MWh": [f"{r['ef']:.3f}" for r in pick],
        "CO₂ (Mt/yr)": [fmt(r["co2_mt"]) for r in pick],
        "Cumulative CO₂ (Gt)": [fmt(r["cum_gt"]) for r in pick],
        "Warming (°C)": [fmt(r["warm"]) for r in pick],
        "Extra ET (km³/yr)": [fmt(r["et_km3"]) for r in pick],
        "Direct water (km³/yr)": [fmt(r["direct_km3"]) for r in pick],
    })

    # --- order of magnitude per facility size ---------------------------------
    st.markdown("**Order of magnitude by facility size** (utilization and PUE from tab 1, electricity mix and climate settings from tab 4)")
    sizes = [1, 10, 100, 1000]
    size_mwh = [s_mw * util * HR_PER_YR * pue for s_mw in sizes]
    lo_f, hi_f = impact_per_mwh(ef_mix, TCRE_LOW, S_LOW), impact_per_mwh(ef_mix, TCRE_HIGH, cc_rate(t_water))
    st.table({
        "IT size (MW)": sizes,
        "Electricity (GWh/yr)": [fmt(m / 1e3) for m in size_mwh],
        "CO₂ (kt/yr)": [fmt(m * ef_mix / 1e3) for m in size_mwh],
        f"Extra global ET over {horizon} yr, central (Mm³)": [fmt(m * if_mwh / 1e6) for m in size_mwh],
        "Low – high (Mm³)": [f"{fmt(m * lo_f / 1e6)} – {fmt(m * hi_f / 1e6)}" for m in size_mwh],
        "Direct water, fleet average (Mm³/yr)": [fmt(m * dw / 1e6) for m in size_mwh],
    })
    st.caption(f"Rule of thumb for these settings: about **{fmt(size_mwh[0] * ef_mix, 't CO₂/yr')}** and "
               f"**{fmt(size_mwh[0] * if_mwh / 1e6, 'Mm³')}** of extra global ET per MW of IT load, scaling linearly with size.")

    # --- slide-ready figure (matplotlib, copy-able) -----------------------------
    st.markdown("**Slide figure**")
    fig_s, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.6), dpi=100, gridspec_kw={"width_ratios": [1.15, 1]})
    band_lo = TCRE_LOW * S_LOW / (tcre * s_att) if tcre * s_att else 0.0
    band_hi = TCRE_HIGH * cc_rate(t_water) / (tcre * s_att) if tcre * s_att else 0.0
    ax1.fill_between(yrs, [r["et_km3"] * band_lo for r in fl], [r["et_km3"] * band_hi for r in fl], color=COLOR_DC, alpha=0.15,
                     lw=0, label="Uncertainty range (TCRE and ET sensitivity)")
    ax1.plot(yrs, [r["et_km3"] for r in fl], color=COLOR_DC, lw=4, label="Extra global ET (from fleet CO₂)")
    ax1.plot(yrs, [r["direct_km3"] for r in fl], color=COLOR_ET, lw=4, label="Direct cooling water")
    if incl_ind:
        ax1.plot(yrs, [r["indirect_km3"] for r in fl], color=COLOR_ET, lw=2.5, ls="--", label="Indirect (power generation) water")
    ax1.annotate(f"{last['et_km3']:.1f} km³/yr", (yrs[-1], last["et_km3"]), xytext=(-8, 8), textcoords="offset points",
                 ha="right", fontsize=14, fontweight="bold", color=COLOR_DC)
    ax1.annotate(f"{last['direct_km3']:.2f} km³/yr", (yrs[-1], last["direct_km3"]), xytext=(-8, 8), textcoords="offset points",
                 ha="right", fontsize=14, fontweight="bold", color=COLOR_ET)
    ax1.set_title("(a) The whole fleet", fontsize=18, fontweight="bold", loc="left")
    ax1.set_xlabel("Year", fontsize=15)
    ax1.set_ylabel("km³ per year", fontsize=15)
    ax1.set_ylim(bottom=0)
    ax1.legend(fontsize=13, frameon=False, loc="upper left")

    x = list(range(len(sizes)))
    cen = [m * if_mwh / 1e6 for m in size_mwh]
    lo = [m * lo_f / 1e6 for m in size_mwh]
    hi = [m * hi_f / 1e6 for m in size_mwh]
    dirw = [m * dw / 1e6 for m in size_mwh]
    ax2.bar([i - 0.2 for i in x], cen, width=0.38, color=COLOR_DC, label=f"Extra global ET, accumulated over {horizon} yr")
    ax2.errorbar([i - 0.2 for i in x], cen, yerr=[[max(c - l_, 0) for c, l_ in zip(cen, lo)], [max(h - c, 0) for c, h in zip(cen, hi)]],
                 fmt="none", ecolor="#555", capsize=5, lw=2)
    ax2.bar([i + 0.2 for i in x], dirw, width=0.38, color=COLOR_ET, label="Direct cooling water, one year")
    if any(v > 0 for v in cen + dirw):  # a log axis needs at least one positive bar
        ax2.set_yscale("log")
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{s_mw:,} MW" if s_mw < 1000 else "1 GW" for s_mw in sizes], fontsize=14)
    ax2.set_title("(b) One facility, by size (one year of operation)", fontsize=18, fontweight="bold", loc="left")
    ax2.set_ylabel("Mm³ (log scale)", fontsize=15)
    ax2.legend(fontsize=12, frameon=False, loc="upper left")
    for ax in (ax1, ax2):
        ax.tick_params(labelsize=13)
        ax.grid(alpha=0.25, which="both")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    fig_s.suptitle("Data centers: extra evapotranspiration from their CO₂ vs. their direct cooling water",
                   fontsize=20, fontweight="bold", x=0.01, ha="left")
    fig_s.text(0.01, 0.005,
               f"Fleet: {fleet_label}; grid {ef_base:.2f} → {ef_end:.2f} tCO₂/MWh by {END_YEAR}; TCRE {tcre} °C/1000 GtCO₂; "
               f"ET sensitivity {s_att * 100:.1f} %/°C; facility mix {ef_mix:.2f} tCO₂/MWh. Whiskers: TCRE {TCRE_LOW}–{TCRE_HIGH} with "
               f"{S_LOW * 100:.0f} %/°C to Clausius–Clapeyron.", fontsize=11, color="#555")
    fig_s.tight_layout(rect=(0, 0.04, 1, 0.94))
    show_figure(to_png(fig_s), "fleet_impact", "fleet")

    with st.expander("Hand calculation (base year)"):
        md(f"""
**Step 1 — electricity.** E = {fmt(first['twh'], 'TWh')} = {fmt(first['twh'] * 1e6, 'MWh')} in {first['year']}.
{model_desc}

**Step 2 — CO₂.** EF = (1 − {clean_share:.2f}) × grid + {clean_share:.2f} × {CLEAN_EF} = {first['ef']:.3f} tCO₂/MWh
M = {fmt(first['twh'] * 1e6)} × {first['ef']:.3f} = **{fmt(first['co2_mt'], 'Mt')}** ({fmt(100 * first['co2_mt'] / glob_co2_mt)} % of {fmt(glob_co2_mt, 'Mt')})

**Step 3 — warming from cumulative CO₂.** ΔT(y) = TCRE × Σ M ÷ 10¹² t. By {END_YEAR}: {fmt(last['cum_gt'], 'Gt')} × {tcre} ÷ 1000 = **{fmt(last['warm'], '°C')}**

**Step 4 — extra ET.** ET = s × ΔT × V_ET = {s_att:.4f} × {fmt(last['warm'])} × {fmt(glob_et_km3, 'km³/yr')} = **{fmt(last['et_km3'], 'km³/yr')}** in {END_YEAR}

**Step 5 — context.** All warming so far: {dT_obs} °C × {s_att:.4f} × {fmt(glob_et_km3)} = {fmt(et_total_km3, 'km³/yr')}; the sector's {END_YEAR} share is **{fmt(100 * last['et_km3'] / et_total_km3)} %**.
Direct water = E × intensity = {fmt(last['twh'] * 1e6)} MWh × {dw:.3g} m³/MWh = {fmt(last['direct_km3'], 'km³/yr')} in {END_YEAR}.
""")
    st.info(
        "The fleet totals come from published estimates (IEA Energy and AI 2025, LBNL 2024) and the later years are scenarios, not forecasts. "
        "The result answers 'how much of the warming-driven ET change is due to data-center electricity', not 'which aquifer is stressed'. "
        "Extra ET is global and is not the same as lost water. LBNL's indirect water includes hydropower reservoir evaporation, "
        "and its totals exclude behind-the-meter power and power purchase agreements."
    )

# ---------------------------------------------------------------------------
# 6. Reservoir mixing
# ---------------------------------------------------------------------------
with tab_mix:
    st.subheader("Returning warm cooling water to a pond or reservoir")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Reservoir**")
        res_area_km2 = st.number_input("Surface area (km²)", 0.001, 10000.0, 1.0, 0.1)
        res_depth = st.number_input("Mean depth (m)", 0.1, 500.0, 5.0, 0.5)
        t_res = st.number_input("Initial temperature (°C)", 0.0, 40.0, 20.0, 0.5)
    with c2:
        st.markdown("**Return water**")
        scenario = st.radio(
            "Scenario",
            ["Once-through cooling (all heat to water)", "Cooling-tower blowdown only", "Manual flow & temperature"],
            help="Once-through: water passes the condenser once and returns warmer. "
                 "Blowdown: most heat leaves as vapor; only the small blowdown stream returns.",
        )
        if scenario.startswith("Once"):
            dT_cond = st.number_input("Temperature rise across condenser (°C)", 0.5, 20.0, 8.0, 0.5)
            q_flow = P_dc / (RHO_W * CP_W * dT_cond)             # m^3/s
            t_ret = t_res + dT_cond
        elif scenario.startswith("Cooling"):
            if mode.startswith("Energy"):
                q_flow = blowdown_m3 / SEC_PER_YR
            else:
                st.caption("WUE mode has no blowdown estimate — enter the flow manually.")
                q_flow = st.number_input("Blowdown flow (m³/day)", 0.0, 1e7, 500.0, 50.0) / 86400
            t_ret = st.number_input("Blowdown temperature (°C)", 0.0, 60.0, t_res + 10.0, 0.5)
        else:
            q_flow = st.number_input("Return flow (m³/day)", 0.0, 1e8, 10000.0, 1000.0) / 86400
            t_ret = st.number_input("Return temperature (°C)", 0.0, 60.0, 30.0, 0.5)
    with c3:
        st.markdown("**Time and surface cooling**")
        period_days = st.number_input("Mixing period (days)", 0.1, 3650.0, 1.0, 1.0)
        K = st.number_input(
            "Surface heat-exchange coefficient K (W/m²/°C)", 1.0, 100.0, 25.0, 1.0,
            help="Lumped coefficient for heat loss from the water surface to the atmosphere per °C of "
                 "excess temperature. An assumption — the student should find and cite a value.",
        )

    res_area_m2 = res_area_km2 * 1e6
    V_res = res_area_m2 * res_depth
    P_ret = RHO_W * CP_W * q_flow * (t_ret - t_res)                     # W
    V_ret = q_flow * period_days * 86400                                 # m^3 in period
    T_mix = (V_res * t_res + V_ret * t_ret) / (V_res + V_ret) if (V_res + V_ret) > 0 else t_res
    dT_eq = P_ret / (K * res_area_m2)
    tau_s = RHO_W * CP_W * res_depth / K
    tau_d = tau_s / 86400

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Return flow", fmt(q_flow, "m³/s"), help=f"{fmt(q_flow * 86400, 'm³/day')}")
    m2.metric("Heat in return water", fmt(P_ret / 1e6, "MW"))
    m3.metric(f"Mixed T, {fmt(period_days)} d, no losses", fmt(T_mix, "°C"),
              delta=fmt(T_mix - t_res, "°C"), delta_color="inverse")
    m4.metric("Equilibrium warming", fmt(dT_eq, "°C"),
              help=f"Steady state with surface cooling, reached with time constant τ = {fmt(tau_d, 'days')}")

    # time series with surface cooling
    t_end = max(5 * tau_d, period_days)
    ts = [t_end * i / 200 for i in range(201)]
    Ts = [t_res + dT_eq * (1 - math.exp(-t / tau_d)) for t in ts]
    fig2 = go.Figure(go.Scatter(x=ts, y=Ts, mode="lines", line=dict(color=COLOR_DC, width=2),
                                hovertemplate="day %{x:.1f}: %{y:.2f} °C<extra></extra>"))
    fig2.add_hline(y=t_res + dT_eq, line_dash="dot", line_color="gray",
                   annotation_text=f"equilibrium {t_res + dT_eq:.2f} °C", annotation_position="bottom right")
    fig2.update_layout(
        xaxis=dict(title="Days since discharge began", gridcolor="rgba(128,128,128,0.2)"),
        yaxis=dict(title="Well-mixed reservoir temperature (°C)", gridcolor="rgba(128,128,128,0.2)"),
        height=340, margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
    )
    st.plotly_chart(fig2, width="stretch")
    st.caption("Well-mixed reservoir, constant heat input, heat lost through the surface in proportion to the excess temperature.")

    with st.expander("Hand calculation"):
        flow_line = (
            f"Q = P ÷ (ρ c ΔT) = {fmt(P_dc)} W ÷ (1000 × 4186 × {dT_cond}) = **{fmt(q_flow, 'm³/s')}**"
            if scenario.startswith("Once") else f"Q = **{fmt(q_flow, 'm³/s')}** ({fmt(q_flow * 86400, 'm³/day')})"
        )
        md(f"""
**Step 1 — reservoir volume.** V = A × h = {fmt(res_area_m2, 'm²')} × {res_depth} m = **{fmt(V_res, 'm³')}**

**Step 2 — return flow.** {flow_line}

**Step 3 — heat carried by the return water.** P = ρ c Q (T_return − T_res) = 1000 × 4186 × {fmt(q_flow)} × ({fmt(t_ret)} − {fmt(t_res)}) = **{fmt(P_ret / 1e6, 'MW')}**

**Step 4 — mixing, no losses (heat-capacity balance).** Returned volume in {fmt(period_days)} d: V_w = {fmt(q_flow)} × {fmt(period_days * 86400)} s = {fmt(V_ret, 'm³')}
T_mix = (V_res T_res + V_w T_w) ÷ (V_res + V_w) = ({fmt(V_res)} × {fmt(t_res)} + {fmt(V_ret)} × {fmt(t_ret)}) ÷ {fmt(V_res + V_ret)} = **{fmt(T_mix, '°C')}**
*Upper bound: ignores heat loss to air, inflow/outflow, and stratification. Over long periods it overestimates badly — see step 5.*

**Step 5 — steady state with surface cooling.** Heat in = heat out → P = K A ΔT_eq
ΔT_eq = {fmt(P_ret)} W ÷ ({K} × {fmt(res_area_m2)} m²) = **{fmt(dT_eq, '°C')}**
Time constant τ = ρ c h ÷ K = 1000 × 4186 × {res_depth} ÷ {K} = {fmt(tau_s, 's')} = **{fmt(tau_d, 'days')}**
T(t) = T_res + ΔT_eq (1 − e^(−t/τ)); about 63 % of ΔT_eq is reached after one τ, 95 % after 3τ.
""")

# ---------------------------------------------------------------------------
# 7. Methods & sources
# ---------------------------------------------------------------------------
with tab_meth:
    st.subheader("Equations")
    st.latex(r"L(T) \approx 2.501\times10^{6} - 2361\,T \quad [\mathrm{J\,kg^{-1}},\ T\ \mathrm{in}\ ^\circ\mathrm{C}]")
    st.latex(r"V_{evap} = \frac{f_{evap}\,Q}{\rho\,L}, \qquad V_{blowdown} = \frac{V_{evap}}{CoC-1}")
    st.latex(r"V_{ET} = \Delta ET \cdot A, \qquad \Delta ET_{warming} \le ET_0\, s\, \Delta T,\quad s_{CC} = \frac{17.27\cdot 237.3}{(T+237.3)^2}")
    st.latex(r"T_{mix} = \frac{V_r T_r + V_w T_w}{V_r + V_w}, \qquad \Delta T_{eq} = \frac{P}{K A}, \qquad \tau = \frac{\rho c h}{K}")

    st.latex(r"M = E\,\mathrm{EF}, \qquad \Delta T = M \cdot \mathrm{TCRE}, \qquad V_{ET,global} = s\,\Delta T\,V_{land\,ET}\,N_{yr}, \qquad \mathrm{IF} = \frac{V_{ET,global}}{E}")
    st.latex(r"\Delta T(y) = \mathrm{TCRE}\sum_{k\le y} E_k\,\mathrm{EF}_k, \qquad V_{ET}(y) = s\,\Delta T(y)\,V_{land\,ET}")
    st.subheader("Assumptions to state in the write-up")
    st.markdown("""
- **Consumption vs. withdrawal:** evaporation is consumed; blowdown and once-through water are withdrawn and returned.
- **Water source:** the comparison says something about groundwater only if the facility pumps from the same aquifer.
- **Spatial scale:** ΔET is spread over the whole area; a data center draws from one point. The ratio changes with the area chosen.
- **Warming mode:** Clausius–Clapeyron scaling is an upper bound; actual ET is limited by available water and energy.
- **Reported WUE** is self-reported and defined inconsistently between companies.
- **Reservoir model:** well mixed, constant heat input, one lumped surface coefficient K; no stratification, inflow, or outflow.
- **Climate attribution:** the impact factor assigns a proportional share of warming-driven ET to the electricity's CO₂ using TCRE. Warming is global, so the local share is tiny. It is a fair-share accounting, not a detectable local cause.
- **Electricity source drives the factor:** the factor scales with tCO₂/MWh, so nuclear or wind supply is roughly 30 to 50 times lower than coal or gas. It depends on additionality (new clean supply vs. re-labelled existing supply).
- **Fleet scale-up:** fleet electricity comes from IEA and LBNL estimates and later years are scenarios. Warming is taken as proportional to cumulative CO₂ (TCRE); non-CO₂ gases and the rest of the electricity sector are ignored. The result is the sector's share of the warming-driven ET change, not a local depletion estimate.
- **US growth models:** the history table is LBNL's Fig. 5.5 (three values stated in the text, the rest read off the chart). Exponential, logistic and scenario paths fit the same ten points and diverge after 2023; they differ in assumed limits, not in fit quality.
- **Persistence:** warming from a CO₂ pulse stays about constant for centuries, so extra ET repeats each year; the horizon is a choice.
- **Extra ET is not lost water:** evaporated water returns as rain elsewhere; groundwater is depleted only where recharge does not keep up.
- **Waste heat vs. regional climate:** a data center's sensible heat is negligible compared with solar input over a basin; it does not measurably drive regional ET.
""")

    st.subheader("Starting sources (verify all values before use)")
    st.markdown("""
- Condon, L.E., Atchley, A.L., Maxwell, R.M. (2020). Evapotranspiration depletes groundwater under warming over the contiguous United States. *Nature Communications* 11, 873. https://www.nature.com/articles/s41467-020-14688-0
- Shehabi, A., et al. (2024). *2024 United States Data Center Energy Usage Report.* Lawrence Berkeley National Laboratory. https://eta.lbl.gov/publications/2024-lbnl-data-center-energy-usage-report
- IPCC AR6 WG1, Chapter 5 (Canadell et al. 2021): TCRE of 1.65 [1.0–2.3] °C per 1000 PgC, i.e. 0.45 [0.27–0.63] °C per 1000 GtCO₂.
- IPCC AR5 WG3 Annex III (Schlömer et al. 2014): lifecycle emission medians by technology. Check regional grid factors (e.g. EPA eGRID).
- Apportioning warming to emitters: Ekwurzel et al. (2017), Climatic Change. Verify before citing.
- IEA (2025), *Energy and AI*: data centers about 415 TWh in 2024 (about 1.5 % of world electricity), about 945 TWh by 2030. https://www.iea.org/reports/energy-and-ai
- LBNL 2024 report (above): US data centers 176 TWh in 2023, 325–580 TWh by 2028; direct water about 66 billion L and indirect about 800 billion L in 2023 (indirect includes hydropower reservoir evaporation).
- The Green Grid — definitions of PUE and WUE.
- Latent heat linear fit and Magnus/Tetens vapor-pressure form: standard hydrometeorology texts (e.g., Dingman, *Physical Hydrology*).
""")

    # export
    rows = [
        ("latent_heat_J_per_kg", L), ("dc_heat_rejected_MW", P_dc / 1e6), ("dc_direct_m3_yr", direct_m3),
        ("dc_indirect_m3_yr", indirect_m3), ("dc_total_m3_yr", total_dc_m3), ("area_km2", area_km2),
        ("dET_mm_yr", d_et_mm), ("dET_m3_yr", d_et_m3), ("dET_latent_MW", P_et / 1e6), ("ratio_dc_to_dET", ratio),
        ("equiv_area_km2", area_equiv_km2), ("equiv_warming_C", dT_equiv),
        ("reservoir_volume_m3", V_res), ("return_flow_m3_s", q_flow), ("return_heat_MW", P_ret / 1e6),
        ("T_mix_no_loss_C", T_mix), ("dT_equilibrium_C", dT_eq), ("tau_days", tau_d),
        ("attr_electricity_MWh_yr", att_mwh), ("attr_emission_factor_tCO2_MWh", ef_mix), ("attr_CO2_t_yr", co2_t),
        ("attr_warming_C_per_operating_year", warm_c), ("attr_extra_global_ET_m3_yr", et_yr_m3),
        ("attr_extra_global_ET_horizon_m3", et_hor_m3), ("attr_impact_factor_m3_per_MWh", if_mwh),
        ("attr_share_on_area_horizon_m3", local_hor_m3),
        ("fleet_base_year_CO2_Mt", first["co2_mt"]), ("fleet_cumulative_CO2_Gt_2050", last["cum_gt"]),
        ("fleet_warming_C_2050", last["warm"]), ("fleet_extra_ET_km3_yr_2050", last["et_km3"]),
        ("fleet_direct_water_km3_yr_2050", last["direct_km3"]), ("fleet_cumulative_direct_km3", cum_direct),
        ("fleet_cumulative_extra_ET_km3", cum_et),
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["quantity", "value"])
    w.writerows(rows)
    st.download_button("Download results (CSV)", buf.getvalue(), "dc_water_et_results.csv", "text/csv")
