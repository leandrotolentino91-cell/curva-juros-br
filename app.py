"""
Curva de Juros Brasil — dashboard de comparação da curva DI / ETTJ no tempo.

Rodar localmente:   streamlit run app.py
Dados: B3 (TaxaSwap: curvas DI x Pré e DI x IPCA, construídas com os ajustes do DI1),
       ANBIMA (ETTJ, reserva), B3 cotações DI1 (ao vivo), BCB (Selic e Focus).
Detalhes das fontes em core/fontes.py e docs/FONTES_DE_DADOS.md.

>>> COMO AJUSTAR AS DATAS DE COMPARAÇÃO <<<
Edite o dicionário PERIODOS abaixo (nome → nº de meses para trás). Os nomes
aparecem no seletor da barra lateral; cores ficam em core/graficos.py (CORES).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta

from core import analise as an
from core import fontes
from core import graficos as gr
from core.calendario import dia_util_anterior, somar_dias_uteis

# ----------------------------------------------------------------------------
# Configurações editáveis
# ----------------------------------------------------------------------------
PERIODOS: dict[str, int] = {"1 mês": 1, "3 meses": 3, "6 meses": 6, "1 ano": 12, "2 anos": 24}
PERIODOS_PADRAO = ["1 mês", "6 meses", "1 ano"]
PRAZOS_KPI = ["1A", "2A", "5A", "10A"]
CURTO = {"1 mês": "1m", "3 meses": "3m", "6 meses": "6m", "1 ano": "1a", "2 anos": "2a", "Data escolhida": "data"}
TTL_CACHE_S = 60 * 60  # cache em memória (1h). O botão "Atualizar dados" limpa na hora.

st.set_page_config(page_title="Curva de Juros Brasil · DI / ETTJ", page_icon="📈", layout="wide",
                   initial_sidebar_state="auto")

st.markdown("""
<style>
.block-container{padding-top:1.4rem;padding-bottom:2rem;max-width:1500px}
div[data-testid="stMetric"]{border:1px solid rgba(128,128,128,.25);border-radius:12px;padding:10px 14px}
div[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:3px 10px;border-radius:999px;margin:2px 4px 2px 0;font-size:.85rem;
     border:1px solid rgba(128,128,128,.35)}
.tag.rot{background:rgba(236,72,153,.15);border-color:#EC4899;font-weight:600}
.tag.inv{background:rgba(239,68,68,.13);border-color:#EF4444}
.card{border:1px solid rgba(128,128,128,.25);border-radius:12px;padding:12px 14px;height:100%}
.card h4{margin:0 0 6px 0;font-size:1rem}
.mut{opacity:.7;font-size:.85rem}
</style>""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Camada de dados com cache do Streamlit (por cima do cache em disco)
# ----------------------------------------------------------------------------
@st.cache_data(ttl=TTL_CACHE_S, show_spinner=False)
def carregar_curva(alvo: date) -> tuple[date, pd.DataFrame]:
    """Curva do último dia útil com dados <= alvo."""
    df = fontes.curva_mais_recente_ate(alvo)
    return df["data"].iloc[0].date(), df


@st.cache_data(ttl=TTL_CACHE_S, show_spinner=False)
def carregar_historico(datas: tuple[date, ...]) -> tuple[pd.DataFrame, list[str]]:
    return fontes.curvas_varias_datas(list(datas))


@st.cache_data(ttl=TTL_CACHE_S, show_spinner=False)
def carregar_selic(inicio: date, fim: date) -> pd.DataFrame:
    try:
        return fontes.selic_meta(inicio, fim)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


@st.cache_data(ttl=TTL_CACHE_S, show_spinner=False)
def carregar_focus() -> pd.DataFrame:
    try:
        return fontes.focus_anual()
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def carregar_ao_vivo():
    return fontes.di1_ao_vivo()


def data_do_periodo(base: date, meses: int, convencao: str) -> date:
    d = base - relativedelta(months=meses)
    if convencao.startswith("Último"):
        d = (d.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
    return dia_util_anterior(d)


def datas_historico(fim: date, anos: float, passo_du: int) -> list[date]:
    ini = fim - timedelta(days=int(365 * anos))
    out, d = [], fim
    while d >= ini:
        out.append(d)
        d = somar_dias_uteis(d, -passo_du)
    return sorted(out)


def csv_br(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", decimal=",", float_format="%.4f").encode("utf-8-sig")


def fmt_pct(x):
    return "—" if x is None or not np.isfinite(x) else f"{x:.3f}%"


# ----------------------------------------------------------------------------
# Barra lateral
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Parâmetros")
    if st.button("🔄 Atualizar dados", width="stretch", type="primary",
                 help="Limpa o cache e baixa novamente as datas recentes"):
        st.cache_data.clear()
        n = fontes.limpar_cache_recente()
        st.toast(f"Cache limpo ({n} arquivos recentes). Baixando de novo…")
        st.rerun()

    ref_escolhida = st.date_input("Data de referência (curva atual)", value=date.today(),
                                  max_value=date.today(), format="DD/MM/YYYY",
                                  help="Usa o último dia útil com dados publicados até esta data.")
    periodos_sel = st.multiselect("Comparar com", list(PERIODOS), default=PERIODOS_PADRAO)
    convencao = st.radio("Data dos períodos", ["Mesmo dia (dia útil anterior)", "Último dia útil do mês"],
                         help="Ex.: ref. 14/10 → 1 mês = 14/09 ou 30/09…")
    usar_extra = st.checkbox("Adicionar uma data livre")
    data_extra = st.date_input("Data livre", value=date.today() - timedelta(days=90), max_value=date.today(),
                               format="DD/MM/YYYY", disabled=not usar_extra)

    st.divider()
    modo_vertices = st.radio("Vértices", ["Contratos DI1 (vencimento fixo)", "Prazos constantes (3M…15A)"],
                             help="Contratos: compara o MESMO vencimento (ex.: jan/29) nas datas. "
                                  "Prazos constantes: compara o mesmo prazo (ex.: 2 anos) a partir de cada data.")
    so_principais = st.toggle("Só vértices principais", value=True,
                              help="Contratos jan/27, 28, 29, 30, 32, 35, 40 (relativos ao ano atual).")
    eixo_x = st.radio("Eixo X da curva", ["Prazo (anos)", "Data de vencimento"], horizontal=True)
    limiar = st.slider("Limiar para classificar movimento (bps)", 1, 30, 5)

    st.divider()
    st.subheader("Histórico")
    janela = st.select_slider("Janela", options=[0.5, 1.0, 2.0, 3.0], value=2.0,
                              format_func=lambda x: f"{x:g} ano" + ("s" if x > 1 else "") if x >= 1 else "6 meses")
    freq = st.radio("Frequência", ["Semanal", "Quinzenal", "Mensal"], horizontal=True,
                    help="Semanal = 1 ponto a cada 5 dias úteis. A 1ª carga baixa vários arquivos da B3 "
                         "(fica em cache depois).")
    passo = {"Semanal": 5, "Quinzenal": 10, "Mensal": 21}[freq]

# ----------------------------------------------------------------------------
# Carga das curvas
# ----------------------------------------------------------------------------
st.title("📈 Curva de Juros Brasil · DI / ETTJ")

try:
    with st.spinner("Buscando a curva mais recente na B3…"):
        d_atual, c_atual = carregar_curva(ref_escolhida)
except Exception as e:  # noqa: BLE001
    st.error(f"Não foi possível obter a curva atual. Fonte indisponível ou sem pregão recente.\n\n`{e}`")
    st.info("Tente **Atualizar dados** em alguns minutos ou escolha outra data de referência.")
    st.stop()

curvas: dict[str, tuple[date, pd.DataFrame]] = {"Atual": (d_atual, c_atual)}
avisos = []
alvos = {p: data_do_periodo(d_atual, PERIODOS[p], convencao) for p in periodos_sel}
if usar_extra:
    alvos["Data escolhida"] = dia_util_anterior(data_extra)
with st.spinner("Buscando curvas de comparação…"):
    for nome, alvo in alvos.items():
        try:
            curvas[nome] = carregar_curva(alvo)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"{nome} ({alvo:%d/%m/%Y}): {e}")
nomes = list(curvas)
comp = [n for n in nomes if n != "Atual"]
fonte_atual = c_atual["fonte"].iloc[0]

st.caption(
    f"Curva atual: **{d_atual:%d/%m/%Y}** (fonte {fonte_atual}) · Comparações: "
    + (" · ".join(f"{n} = {curvas[n][0]:%d/%m/%Y}" for n in comp) or "nenhuma")
    + " · Taxas % a.a. base 252 · Δ = atual − período (➕ abriu / ➖ fechou)")
for a in avisos:
    st.warning(f"Sem dados para {a}")

# Tabelas base
tab_cm = an.tabela_prazos(curvas)
contratos = an.contratos_di1(d_atual, principais=so_principais)
tab_ct = an.tabela_contratos(curvas, contratos)
if modo_vertices.startswith("Contratos"):
    base, rot, anos_v = tab_ct, tab_ct["rotulo"].tolist(), tab_ct["anos_ref"].tolist()
else:
    base = tab_cm if not so_principais else tab_cm[tab_cm["prazo"].isin(["6M", "1A", "2A", "3A", "5A", "10A", "15A"])]
    rot, anos_v = base["prazo"].tolist(), base["anos_ref"].tolist()
var = an.variacoes_bps(base, "Atual", nomes)
var.index = rot

selic_df = carregar_selic(d_atual - timedelta(days=int(365 * max(janela, 2)) + 30), d_atual)
selic_atual = float(selic_df["valor"].iloc[-1]) if not selic_df.empty else None
if not selic_df.empty:  # estende o degrau da Selic até a data atual
    selic_df = pd.concat([selic_df, pd.DataFrame({"data": [pd.Timestamp(d_atual)], "valor": [selic_atual]})])

# ----------------------------------------------------------------------------
# KPIs
# ----------------------------------------------------------------------------
cols = st.columns(len(PRAZOS_KPI) + 2)
ref_kpi = comp[0] if comp else None
tcm = tab_cm.set_index("prazo")
for c, p in zip(cols, PRAZOS_KPI):
    v = tcm.at[p, "Atual"]
    dlt = (v - tcm.at[p, ref_kpi]) * 100 if ref_kpi else None
    c.metric(f"DI {p}", "—" if not np.isfinite(v) else f"{v:.2f}%",
             None if dlt is None or not np.isfinite(dlt) else f"{dlt:+.0f} bps ({CURTO.get(ref_kpi, ref_kpi)})",
             delta_color="inverse", help=f"Taxa do prazo constante de {p} (interpolada). Δ vs {ref_kpi}.")
sp_atual = an.spreads_de(tab_cm, "Atual")
dsp = (sp_atual["10A−2A"] - an.spreads_de(tab_cm, ref_kpi)["10A−2A"]) if ref_kpi else None
cols[-2].metric("10A−2A", f"{sp_atual['10A−2A']:+.0f} bps",
                None if dsp is None or not np.isfinite(dsp) else f"{dsp:+.0f} ({CURTO.get(ref_kpi, ref_kpi)})",
                delta_color="off", help="Inclinação: taxa de 10 anos − 2 anos")
cols[-1].metric("Selic meta", f"{selic_atual:.2f}%" if selic_atual else "—")

# ----------------------------------------------------------------------------
# Abas
# ----------------------------------------------------------------------------
abas = st.tabs(["📈 Curvas", "📊 Variação (bps)", "📐 Inclinação", "📋 Tabela", "🏷️ Real × Nominal",
                "🕰️ Histórico", "🎯 Selic & Focus", "⚡ Ao vivo", "⬇️ Exportar & fontes"])

# --- 1) Curvas sobrepostas + classificação de movimento ----------------------
with abas[0]:
    series = []
    for n in nomes:
        d, c = curvas[n]
        if modo_vertices.startswith("Contratos"):
            ct = an.contratos_di1(d_atual, principais=False) if not so_principais else contratos
            y = np.array([an.taxa_contrato(c, d, v) for v in ct["vencimento"]])
            y_atual = np.array([an.taxa_contrato(c_atual, d_atual, v) for v in ct["vencimento"]])
            x = ct["anos_ref"].values if eixo_x.startswith("Prazo") else pd.to_datetime(ct["vencimento"])
            rot_s = [f"{r} ({k})" for r, k in zip(ct["rotulo"], ct["contrato"])]
        else:
            pre = c[c["curva"] == "PRE"]
            pre = pre[pre["du"] >= 21]
            du = pre["du"].values
            y = pre["taxa"].values
            y_atual = an.taxa_em(c_atual, du)
            x = du / 252 if eixo_x.startswith("Prazo") else pd.to_datetime([somar_dias_uteis(d, int(k)) for k in du])
            rot_s = [f"{k/252:.2f} anos · {k} DU" for k in du]
        series.append({"nome": n, "x": x, "y": y, "rotulo": rot_s, "delta_bps": (y_atual - y) * 100, "data": d})
    st.plotly_chart(gr.curvas_sobrepostas(series, "anos" if eixo_x.startswith("Prazo") else "vencimento",
                                          selic_atual, "Curva prefixada (DI x Pré) — atual × períodos"),
                    width="stretch", theme="streamlit")
    st.caption("Clique na legenda para ocultar/mostrar curvas; duplo clique isola uma. Arraste para dar zoom.")

    if comp:
        st.subheader("Leitura do movimento")
        cc = st.columns(min(len(comp), 4))
        for i, n in enumerate(comp):
            r = an.classificar(tab_cm, "Atual", n, limiar)
            tags = "".join(
                f'<span class="tag {"rot" if "ROTAÇÃO" in t else "inv" if "INVERT" in t else ""}">{t}</span>'
                for t in r["tags"])
            cc[i % len(cc)].markdown(
                f'<div class="card"><h4>vs {n} <span class="mut">({curvas[n][0]:%d/%m/%Y})</span></h4>'
                f'{tags}<br><span class="mut">Curto: {r["curto"]} · Longo: {r["longo"]}<br>'
                f'Inclinação {r["longo_lbl"]}−1A: {r["inclinacao_passada"]:+.0f} → {r["inclinacao_atual"]:+.0f} bps '
                f'(Δ {r["d_inclinacao"]:+.0f})</span></div>', unsafe_allow_html=True)

# --- 2) Variação em bps + heatmap -------------------------------------------
with abas[1]:
    if var.empty or not comp:
        st.info("Selecione ao menos um período de comparação na barra lateral.")
    else:
        st.plotly_chart(gr.barras_variacao(var[comp], rot, anos_v, "Variação por vértice: atual − período (bps)"),
                        width="stretch", theme="streamlit")
        st.plotly_chart(gr.heatmap_variacao(var[comp], rot, "Mapa de calor — 🟥 abertura · 🟩 fechamento (bps)"),
                        width="stretch", theme="streamlit")

# --- 3) Inclinação / spreads -------------------------------------------------
with abas[2]:
    sp = pd.DataFrame({n: an.spreads_de(tab_cm, n) for n in nomes})
    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.markdown("**Spreads por período (bps)**")
        show = sp.copy()
        for n in comp:
            show[f"Δ vs {n}"] = sp["Atual"] - sp[n]
        st.dataframe(show.style.format("{:+.0f}", na_rep="—"), width="stretch")
        st.caption("Δ positivo = curva mais inclinada hoje do que no período; negativo = mais achatada.")
    with c2:
        st.plotly_chart(gr.spreads_periodos(sp, "Spreads de inclinação por período"),
                        width="stretch", theme="streamlit")
    st.markdown("**Evolução histórica dos spreads**")
    datas_h = datas_historico(d_atual, janela, passo)
    with st.spinner(f"Carregando histórico ({len(datas_h)} datas; a 1ª vez pode levar ~1 min)…"):
        hist, av_h = carregar_historico(tuple(datas_h))
    if hist.empty:
        st.warning("Histórico indisponível no momento.")
        hist_cm = pd.DataFrame()
    else:
        hist_cm = an.historico_prazos(hist)
        st.plotly_chart(gr.spreads_historico(hist_cm, an.SPREADS, {n: curvas[n][0] for n in nomes},
                                             f"Spreads (bps) — {freq.lower()}, últimos {janela:g} ano(s)"),
                        width="stretch", theme="streamlit")
    if av_h:
        with st.expander(f"{len(av_h)} data(s) do histórico falharam"):
            st.write(av_h)

# --- 4) Tabela comparativa ---------------------------------------------------
with abas[3]:
    def tabela_formatada(tab: pd.DataFrame, chave: str) -> pd.DataFrame:
        out = tab[[chave] + nomes].copy()
        for n in comp:
            out[f"Δ {n} (bps)"] = (tab["Atual"] - tab[n]) * 100
        return out

    def estilo(df: pd.DataFrame):
        def cor(v):
            if not isinstance(v, (int, float)) or not np.isfinite(v) or abs(v) < 0.5:
                return ""
            return f"color:{gr.VERMELHO};font-weight:600" if v > 0 else f"color:{gr.VERDE};font-weight:600"
        fmt = {n: "{:.3f}" for n in nomes} | {c: "{:+.1f}" for c in df.columns if c.startswith("Δ")}
        return df.style.format(fmt, na_rep="—").map(cor, subset=[c for c in df.columns if c.startswith("Δ")])

    st.markdown("**Contratos DI1 — mesmo vencimento em cada data (% a.a.)**")
    t1 = tabela_formatada(tab_ct.assign(Vértice=tab_ct["rotulo"] + " · " + tab_ct["contrato"]), "Vértice")
    st.dataframe(estilo(t1), width="stretch", hide_index=True)
    st.markdown("**Prazos constantes (% a.a.)**")
    t2 = tabela_formatada(tab_cm.rename(columns={"prazo": "Prazo"}), "Prazo")
    st.dataframe(estilo(t2), width="stretch", hide_index=True)
    st.caption("🟥 Δ positivo = abriu (taxa subiu desde o período) · 🟩 Δ negativo = fechou.")

# --- 5) Real × Nominal -------------------------------------------------------
with abas[4]:
    if (c_atual["curva"] == "DIC").sum() < 3:
        st.info("Curva IPCA (DI x IPCA) indisponível para a data atual.")
    else:
        sel_rn = st.multiselect("Períodos", nomes, default=nomes[:3], key="rn")
        grid = np.arange(126, 252 * 30 + 1, 21)
        ser = []
        for n in sel_rn:
            d, c = curvas[n]
            if (c["curva"] == "DIC").sum() < 3:
                continue
            ser.append({"nome": n, "data": d, "anos": grid / 252, "pre": an.taxa_em(c, grid, "PRE"),
                        "real": an.taxa_em(c, grid, "DIC"), "impl": an.inflacao_implicita(c, grid)})
        st.plotly_chart(gr.real_nominal(ser), width="stretch", theme="streamlit")
        prz = {k: v for k, v in an.PRAZOS_CM.items() if v >= 252}
        linhas = []
        for n in nomes:
            d, c = curvas[n]
            du = np.array(list(prz.values()))
            for k, p, r, i in zip(prz, an.taxa_em(c, du, "PRE"), an.taxa_em(c, du, "DIC"),
                                  an.inflacao_implicita(c, du)):
                linhas.append({"Período": n, "Prazo": k, "Pré": p, "IPCA+": r, "Implícita": i})
        rn = pd.DataFrame(linhas).pivot(index="Prazo", columns="Período", values=["Pré", "IPCA+", "Implícita"])
        rn = rn.reindex(list(prz)).reindex(columns=nomes, level=1)
        st.dataframe(rn.style.format("{:.2f}", na_rep="—"), width="stretch")
        st.caption("IPCA+ = curva DI x IPCA da B3 (cupom de IPCA). Implícita = (1+pré)/(1+real) − 1.")

# --- 6) Histórico de um vértice ----------------------------------------------
with abas[5]:
    if hist.empty:
        st.warning("Histórico indisponível no momento.")
    else:
        c1, c2 = st.columns([1, 2])
        todos_ct = an.contratos_di1(d_atual, principais=False)
        jan = todos_ct[todos_ct["contrato"].str[3] == "F"]
        padrao = [k for k in jan["contrato"] if k.endswith(f"{(d_atual.year + 3) % 100:02d}")]
        with c1:
            ct_sel = st.multiselect("Contratos DI1", todos_ct["contrato"].tolist(),
                                    default=padrao or jan["contrato"].tolist()[:1])
            cm_sel = st.multiselect("Prazos constantes", list(an.PRAZOS_CM), default=[], placeholder="Escolha prazos…")
            mostra_selic = st.checkbox("Mostrar Selic meta", value=True)
        series_h = pd.DataFrame({"data": sorted(hist["data"].unique())})
        for k in ct_sel:
            v = todos_ct.set_index("contrato").at[k, "vencimento"]
            h = an.historico_contrato(hist, v)
            series_h = series_h.merge(h[["data", "taxa"]].rename(columns={"taxa": k}), on="data", how="left")
        if cm_sel and not hist_cm.empty:
            series_h = series_h.merge(hist_cm[["data"] + cm_sel], on="data", how="left")
        cols_h = ct_sel + cm_sel
        with c2:
            if cols_h:
                ultimo = series_h[cols_h].iloc[-1]
                prim = series_h[cols_h].apply(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
                st.dataframe(pd.DataFrame({"Atual": ultimo, "Início janela": prim,
                                           "Δ (bps)": (ultimo - prim) * 100,
                                           "Mín": series_h[cols_h].min(), "Máx": series_h[cols_h].max()})
                             .style.format({"Atual": "{:.3f}", "Início janela": "{:.3f}", "Δ (bps)": "{:+.0f}",
                                            "Mín": "{:.3f}", "Máx": "{:.3f}"}, na_rep="—"), width="stretch")
        if cols_h:
            st.plotly_chart(gr.historico_linhas(series_h, cols_h, f"Evolução histórica — {freq.lower()}",
                                                selic_df if mostra_selic else None,
                                                {n: curvas[n][0] for n in nomes}),
                            width="stretch", theme="streamlit")
            st.download_button("⬇️ CSV do histórico", csv_br(series_h), "historico_vertices.csv", "text/csv")

# --- 7) Selic & Focus --------------------------------------------------------
with abas[6]:
    focus = carregar_focus()
    fwd = an.forwards_anuais(c_atual, d_atual)
    st.plotly_chart(gr.forwards_focus(fwd, focus, selic_atual,
                                      "Forward implícito na curva (média do CDI no ano) × Focus (Selic de fim de ano)"),
                    width="stretch", theme="streamlit")
    st.caption("O forward jan→jan aproxima o CDI médio esperado no ano (CDI ≈ Selic − 0,10 p.p.); "
               "o Focus mede a Selic no FIM do ano — compare tendência, não nível exato. "
               "A diferença inclui prêmio de risco/termo.")
    if focus.empty:
        st.info("Focus indisponível no momento (API do BCB).")
    else:
        st.markdown(f"**Focus — mediana em {focus['Data'].max():%d/%m/%Y}**")
        fp = focus.pivot(index="DataReferencia", columns="Indicador", values="Mediana")
        st.dataframe(fp.style.format("{:.2f}"), width="stretch")

# --- 8) Ao vivo ---------------------------------------------------------------
with abas[7]:
    st.markdown("Cotações do DI1 durante o pregão (B3, atraso ~15 min): **ajuste anterior × abertura × último**.")
    if st.toggle("Carregar cotações ao vivo", value=False):
        if st.button("↻ Recarregar"):
            carregar_ao_vivo.clear()
        try:
            live, ts = carregar_ao_vivo()
            live = live[(live["contratos_abertos"].fillna(0).astype(float) > 0) |
                        (live["negocios"].fillna(0).astype(float) > 0)]
            if live.empty:
                st.info("Sem negócios/contratos em aberto no momento.")
            else:
                live["Δ dia (bps)"] = (live["ultimo"].fillna(live["ajuste_anterior"]) - live["ajuste_anterior"]) * 100
                live["Δ abertura (bps)"] = (live["ultimo"] - live["abertura"]) * 100
                st.caption(f"Horário B3: {ts}")
                st.plotly_chart(gr.ao_vivo(live, "DI1 — curva intradiária"), width="stretch", theme="streamlit")
                st.dataframe(live.style.format({c: "{:.3f}" for c in ["ajuste_anterior", "abertura", "minima", "maxima",
                                                                     "ultimo", "compra", "venda"]}
                                               | {"Δ dia (bps)": "{:+.1f}", "Δ abertura (bps)": "{:+.1f}"}, na_rep="—"),
                             width="stretch", hide_index=True)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Cotação ao vivo indisponível (a B3 pode bloquear acessos fora do Brasil ou fora do pregão). `{e}`")

# --- 9) Exportar & fontes ----------------------------------------------------
with abas[8]:
    st.markdown("#### Exportar (CSV com `;` e vírgula decimal — abre direto no Excel em PT-BR)")
    brutos = pd.concat([c.assign(periodo=n) for n, (_, c) in curvas.items()], ignore_index=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button("Curvas brutas (vértices B3)", csv_br(brutos), f"curvas_{d_atual:%Y%m%d}.csv", "text/csv",
                       width="stretch")
    c2.download_button("Tabela de contratos", csv_br(tabela_formatada(tab_ct, "contrato")),
                       f"contratos_{d_atual:%Y%m%d}.csv", "text/csv", width="stretch")
    c3.download_button("Prazos constantes", csv_br(tabela_formatada(tab_cm, "prazo")),
                       f"prazos_{d_atual:%Y%m%d}.csv", "text/csv", width="stretch")
    c4.download_button("Histórico (prazos)", csv_br(hist_cm) if not hist_cm.empty else b"",
                       f"historico_{d_atual:%Y%m%d}.csv", "text/csv", width="stretch",
                       disabled=hist_cm.empty)
    st.markdown("""
#### Fontes e metodologia
- **Curva prefixada (DI x Pré)** e **IPCA+ (DI x IPCA)**: arquivo público *Taxas de Mercado para Swaps* da B3
  (Pesquisa por Pregão), construído a partir dos **ajustes diários dos futuros de DI1**. Vértices em dias úteis.
- **Reserva**: ETTJ ANBIMA (prefixada/IPCA), usada quando a B3 falha.
- **Taxa de um contrato** (ex.: DI1F29) em cada data = curva daquela data interpolada (flat-forward 252)
  nos dias úteis até o vencimento do contrato (1º dia útil do mês).
- **Prazos constantes**: mesma interpolação em 63, 126, 252… 3780 DU.
- **Dias úteis**: calendário nacional ANBIMA (feriados fixos + Carnaval, Sexta Santa, Corpus Christi; 20/11 desde 2024).
- **Selic meta**: SGS/BCB série 432. **Focus**: API Olinda/BCB (mediana anual).
- **Ao vivo**: cotações DI1 da B3 com atraso. Pode não responder a servidores fora do Brasil.
""")
    st.caption(f"Cache em disco: `{fontes.CACHE_DIR}` · gerado em {datetime.now():%d/%m/%Y %H:%M}")
