"""
Gráficos Plotly. Todos usam o tema do Streamlit (claro/escuro automático) via
st.plotly_chart(fig, theme="streamlit"); aqui definimos apenas cores das séries,
hover e layout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .analise import FAIXAS

# Paleta legível nos dois temas. A curva ATUAL é sempre a mais forte.
CORES = {
    "Atual": "#2563EB", "1 mês": "#F59E0B", "3 meses": "#10B981", "6 meses": "#A855F7",
    "1 ano": "#EF4444", "2 anos": "#64748B", "Data escolhida": "#EC4899",
}
TRACOS = {"Atual": "solid", "1 mês": "solid", "3 meses": "dot", "6 meses": "dash",
          "1 ano": "dashdot", "2 anos": "longdash", "Data escolhida": "dot"}
VERDE, VERMELHO = "#16A34A", "#DC2626"
FAIXA_FILL = ["rgba(37,99,235,0.06)", "rgba(168,85,247,0.06)", "rgba(239,68,68,0.06)"]


def cor(nome: str) -> str:
    return CORES.get(nome, "#0EA5E9")


def _layout(fig: go.Figure, titulo: str = "", altura: int = 460, yfmt: str = ".2f",
            ytitulo: str = "% a.a.") -> go.Figure:
    fig.update_layout(
        title=dict(text=titulo, x=0, xanchor="left", font=dict(size=15)) if titulo else None,
        height=altura, margin=dict(l=10, r=10, t=56 if titulo else 24, b=10),
        hovermode="closest", legend=dict(orientation="h", y=-0.14, yanchor="top", x=0, xanchor="left"),
        yaxis=dict(title=ytitulo, tickformat=yfmt, zeroline=False),
        hoverlabel=dict(namelength=-1),
    )
    return fig


# ----------------------------------------------------------------------------
def curvas_sobrepostas(series: list[dict], eixo: str, selic: float | None = None,
                       titulo: str = "") -> go.Figure:
    """
    series: [{nome, x, y, rotulo, delta_bps, data}] — delta_bps = atual − esta curva.
    eixo: 'anos' ou 'vencimento'
    """
    fig = go.Figure()
    for s in series:
        principal = s["nome"] == "Atual"
        delta_txt = ["—" if principal or not np.isfinite(d) else f"{d:+.1f} bps"
                     for d in s["delta_bps"]]
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], name=f'{s["nome"]} ({s["data"]:%d/%m/%y})',
            mode="lines+markers", line=dict(color=cor(s["nome"]), width=3.2 if principal else 1.8,
                                            dash=TRACOS.get(s["nome"], "solid"), shape="spline", smoothing=0.4),
            marker=dict(size=7 if principal else 5),
            customdata=np.column_stack([s["rotulo"], delta_txt]),
            hovertemplate=("<b>%{customdata[0]}</b><br>" + s["nome"] +
                           ": %{y:.3f}%<br>Atual − esta: %{customdata[1]}<extra></extra>"),
        ))
    if selic is not None:
        fig.add_hline(y=selic, line=dict(color="#94A3B8", width=1, dash="dot"),
                      annotation_text=f"Selic meta {selic:.2f}%", annotation_position="bottom right")
    fig.update_xaxes(title="Prazo (anos úteis, DU/252)" if eixo == "anos" else "Vencimento")
    return _layout(fig, titulo, 520, ".2f")


def barras_variacao(var: pd.DataFrame, rotulos: list[str], anos: list[float], titulo="") -> go.Figure:
    """var: colunas = períodos, valores em bps (atual − período). Fundo por faixa de prazo."""
    fig = go.Figure()
    for p in var.columns:
        v = var[p].values
        fig.add_trace(go.Bar(
            x=rotulos, y=v, name=f"vs {p}", marker_color=cor(p),
            hovertemplate="<b>%{x}</b><br>vs " + p + ": %{y:+.1f} bps<extra></extra>"))
    # faixas curto / intermediário / longo
    anos = np.asarray(anos)
    for (nome, a, b), fill in zip(FAIXAS, FAIXA_FILL):
        idx = np.where((anos > a) & (anos <= b) | ((a == 0) & (anos <= b)))[0]
        if idx.size:
            fig.add_vrect(x0=idx.min() - 0.5, x1=idx.max() + 0.5, fillcolor=fill, line_width=0, layer="below")
            fig.add_annotation(x=(idx.min() + idx.max()) / 2, y=1.0, xref="x", yref="paper", yanchor="bottom",
                               text=f"<b>{nome}</b>", showarrow=False, font=dict(size=11), opacity=0.75)
    fig.add_hline(y=0, line=dict(color="#94A3B8", width=1))
    fig.update_layout(barmode="group", bargap=0.25)
    fig.update_xaxes(type="category")
    return _layout(fig, titulo, 440, ".0f", "bps (+ abriu / − fechou)")


def heatmap_variacao(var: pd.DataFrame, rotulos: list[str], titulo="") -> go.Figure:
    z = var.values
    lim = float(np.nanmax(np.abs(z))) if np.isfinite(z).any() else 1
    txt = np.where(np.isfinite(z), np.vectorize(lambda x: f"{x:+.0f}")(np.nan_to_num(z)), "")
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"vs {c}" for c in var.columns], y=rotulos, zmid=0, zmin=-lim, zmax=lim,
        colorscale=[[0, VERDE], [0.5, "#F8FAFC"], [1, VERMELHO]],
        text=txt, texttemplate="%{text}", textfont=dict(size=12),
        colorbar=dict(title="bps"),
        hovertemplate="<b>%{y}</b> · %{x}<br>%{z:+.1f} bps<extra></extra>"))
    fig.update_yaxes(autorange="reversed", type="category")
    return _layout(fig, titulo, max(320, 34 * len(rotulos) + 90), ".0f", "")


def spreads_historico(hist_cm: pd.DataFrame, spreads: dict, marcas: dict | None = None, titulo="") -> go.Figure:
    fig = go.Figure()
    paleta = ["#2563EB", "#F59E0B", "#10B981", "#A855F7"]
    for (nome, (a, b)), c in zip(spreads.items(), paleta):
        if a in hist_cm and b in hist_cm:
            fig.add_trace(go.Scatter(x=hist_cm["data"], y=(hist_cm[a] - hist_cm[b]) * 100, name=nome,
                                     line=dict(color=c, width=2),
                                     hovertemplate="%{x|%d/%m/%Y}<br>" + nome + ": %{y:.0f} bps<extra></extra>"))
    for nome, d in (marcas or {}).items():
        if nome != "Atual":
            fig.add_vline(x=pd.Timestamp(d).value / 1e6, line=dict(color=cor(nome), width=1, dash="dot"),
                          annotation_text=nome, annotation_position="top", annotation_font_size=10)
    fig.add_hline(y=0, line=dict(color="#94A3B8", width=1))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, titulo, 420, ".0f", "bps")


def spreads_periodos(tab: pd.DataFrame, titulo="") -> go.Figure:
    """tab: linhas = spreads, colunas = períodos (bps)."""
    fig = go.Figure()
    for p in tab.columns:
        fig.add_trace(go.Bar(x=tab.index, y=tab[p], name=p, marker_color=cor(p),
                             hovertemplate="%{x}<br>" + p + ": %{y:.0f} bps<extra></extra>"))
    fig.add_hline(y=0, line=dict(color="#94A3B8", width=1))
    fig.update_layout(barmode="group")
    return _layout(fig, titulo, 380, ".0f", "bps")


def historico_linhas(df: pd.DataFrame, colunas: list[str], titulo="", selic: pd.DataFrame | None = None,
                     marcas: dict | None = None) -> go.Figure:
    fig = go.Figure()
    paleta = ["#2563EB", "#F59E0B", "#10B981", "#A855F7", "#EF4444", "#0EA5E9", "#64748B", "#EC4899", "#84CC16"]
    for c, k in zip(colunas, paleta * 3):
        fig.add_trace(go.Scatter(x=df["data"], y=df[c], name=c, line=dict(color=k, width=2),
                                 hovertemplate="%{x|%d/%m/%Y}<br>" + c + ": %{y:.3f}%<extra></extra>"))
    if selic is not None and not selic.empty:
        fig.add_trace(go.Scatter(x=selic["data"], y=selic["valor"], name="Selic meta", line_shape="hv",
                                 line=dict(color="#94A3B8", width=1.5, dash="dot"),
                                 hovertemplate="%{x|%d/%m/%Y}<br>Selic meta: %{y:.2f}%<extra></extra>"))
    for nome, d in (marcas or {}).items():
        if nome != "Atual":
            fig.add_vline(x=pd.Timestamp(d).value / 1e6, line=dict(color=cor(nome), width=1, dash="dot"))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, titulo, 440)


def real_nominal(series: list[dict], titulo="") -> go.Figure:
    """series: [{nome, anos, pre, real, impl, data}] — sólido = pré, tracejado = IPCA+, pontilhado = implícita."""
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Prefixada (nominal) × IPCA+ (real)", "Inflação implícita (breakeven)"),
                        horizontal_spacing=0.08)
    for s in series:
        c = cor(s["nome"])
        lbl = f'{s["nome"]} ({s["data"]:%d/%m/%y})'
        fig.add_trace(go.Scatter(x=s["anos"], y=s["pre"], name=f"Pré · {lbl}", line=dict(color=c, width=2.4),
                                 legendgroup=s["nome"],
                                 hovertemplate="%{x:.1f}a · Pré: %{y:.2f}%<extra>" + s["nome"] + "</extra>"), 1, 1)
        fig.add_trace(go.Scatter(x=s["anos"], y=s["real"], name=f"IPCA+ · {lbl}", line=dict(color=c, width=2, dash="dash"),
                                 legendgroup=s["nome"],
                                 hovertemplate="%{x:.1f}a · IPCA+: %{y:.2f}%<extra>" + s["nome"] + "</extra>"), 1, 1)
        fig.add_trace(go.Scatter(x=s["anos"], y=s["impl"], name=f"Implícita · {lbl}", line=dict(color=c, width=2, dash="dot"),
                                 legendgroup=s["nome"], showlegend=False,
                                 hovertemplate="%{x:.1f}a · Implícita: %{y:.2f}%<extra>" + s["nome"] + "</extra>"), 1, 2)
    fig.update_xaxes(title="anos (DU/252)")
    fig.update_yaxes(tickformat=".2f", title="% a.a.", row=1, col=1)
    fig.update_yaxes(tickformat=".2f", row=1, col=2)
    fig.update_layout(height=480, margin=dict(l=10, r=10, t=60, b=10), title=titulo or None,
                      legend=dict(orientation="h", y=-0.18), hovermode="closest")
    return fig


def forwards_focus(fwd: pd.DataFrame, focus: pd.DataFrame | None, selic: float | None, titulo="") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=fwd["ano_calendario"].astype(str), y=fwd["forward"], name="Forward DI implícito (jan→jan)",
                         marker_color="#2563EB", opacity=0.85,
                         customdata=fwd["periodo"],
                         hovertemplate="%{customdata}<br>Forward: %{y:.2f}%<extra></extra>"))
    if focus is not None and not focus.empty:
        f = focus[focus["Indicador"] == "Selic"]
        fig.add_trace(go.Scatter(x=f["DataReferencia"].astype(str), y=f["Mediana"], name="Focus · Selic fim de ano (mediana)",
                                 mode="lines+markers", line=dict(color="#F59E0B", width=2.5), marker=dict(size=9),
                                 hovertemplate="Focus %{x}: %{y:.2f}%<extra></extra>"))
    if selic is not None:
        fig.add_hline(y=selic, line=dict(color="#94A3B8", dash="dot"), annotation_text=f"Selic meta atual {selic:.2f}%")
    fig.update_xaxes(type="category", title="Ano")
    return _layout(fig, titulo, 400)


def ao_vivo(df: pd.DataFrame, titulo="") -> go.Figure:
    fig = go.Figure()
    for col, nome, c, w, dash in (("ajuste_anterior", "Ajuste D-1", "#94A3B8", 1.6, "dash"),
                                  ("abertura", "Abertura", "#F59E0B", 1.8, "solid"),
                                  ("ultimo", "Último", "#2563EB", 3, "solid")):
        d = df[df[col].notna()]
        fig.add_trace(go.Scatter(x=d["vencimento"], y=d[col], name=nome, mode="lines+markers",
                                 line=dict(color=c, width=w, dash=dash), customdata=d["contrato"],
                                 hovertemplate="<b>%{customdata}</b><br>" + nome + ": %{y:.3f}%<extra></extra>"))
    fig.update_xaxes(title="Vencimento")
    return _layout(fig, titulo, 440)
