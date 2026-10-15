"""
Cálculos de curva: interpolação, vértices, spreads, classificação de movimentos.

Convenções
----------
* Taxas em % a.a., base 252 dias úteis (capitalização exponencial).
* Variação = taxa_atual − taxa_passada, em pontos-base (bps).
  Positivo  → a curva ABRIU (taxa subiu)   → vermelho
  Negativo  → a curva FECHOU (taxa caiu)   → verde
* Interpolação flat-forward 252 (padrão de mercado/B3): o log do fator de
  capitalização é linear em DU entre vértices; extrapolação com taxa constante.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .calendario import codigo_di1, dias_uteis, rotulo_vencimento, vencimento_di1

# Prazos constantes (em dias úteis) usados em spreads, heatmap e rotação
PRAZOS_CM: dict[str, int] = {
    "3M": 63, "6M": 126, "1A": 252, "2A": 504, "3A": 756,
    "5A": 1260, "7A": 1764, "10A": 2520, "15A": 3780,
}

# Spreads clássicos de inclinação (longo − curto), em bps
SPREADS: dict[str, tuple[str, str]] = {
    "2A−1A": ("2A", "1A"), "5A−2A": ("5A", "2A"),
    "10A−2A": ("10A", "2A"), "10A−5A": ("10A", "5A"),
}

# Faixas para separar visualmente curto / intermediário / longo (em anos)
FAIXAS = [("Curto (≤1a)", 0, 1.0), ("Intermediário (1–5a)", 1.0, 5.0), ("Longo (>5a)", 5.0, 99)]


def faixa(anos: float) -> str:
    for nome, a, b in FAIXAS:
        if a < anos <= b or (a == 0 and anos <= b):
            return nome
    return FAIXAS[-1][0]


# ----------------------------------------------------------------------------
# Interpolação
# ----------------------------------------------------------------------------
def interpolar(du_pts, taxas, du_alvo) -> np.ndarray:
    """Flat-forward 252. du_pts/taxas: vértices conhecidos; du_alvo: escalar ou array."""
    du_pts = np.asarray(du_pts, dtype=float)
    tx = np.asarray(taxas, dtype=float)
    ok = np.isfinite(du_pts) & np.isfinite(tx) & (du_pts > 0)
    du_pts, tx = du_pts[ok], tx[ok]
    alvo = np.atleast_1d(np.asarray(du_alvo, dtype=float))
    if du_pts.size == 0:
        return np.full(alvo.shape, np.nan)
    ordem = np.argsort(du_pts)
    du_pts, tx = du_pts[ordem], tx[ordem]
    logf = np.log1p(tx / 100) * du_pts / 252          # log do fator de capitalização
    lf = np.interp(alvo, du_pts, logf)
    out = np.expm1(lf * 252 / np.where(alvo > 0, alvo, np.nan)) * 100
    # fora do intervalo: taxa constante (sem extrapolar inclinação)
    out = np.where(alvo < du_pts[0], tx[0], out)
    out = np.where(alvo > du_pts[-1], np.nan, out)    # além do último vértice: sem dado
    return out


def taxa_em(curva: pd.DataFrame, du_alvo, tipo: str = "PRE"):
    c = curva[curva["curva"] == tipo]
    return interpolar(c["du"].values, c["taxa"].values, du_alvo)


# ----------------------------------------------------------------------------
# Vértices DI1 (contratos)
# ----------------------------------------------------------------------------
def contratos_di1(ref: date, anos_max: int = 16, principais: bool = False) -> pd.DataFrame:
    """
    Lista de contratos DI1 relevantes vistos a partir de `ref`.
    principais=True  → janeiros de referência (ex.: jan/27, 28, 29, 30, 32, 35, 40)
    principais=False → 3 primeiros meses + trimestrais (jan/abr/jul/out) até 3 anos + todos os janeiros
    """
    y = ref.year
    lista: set[tuple[int, int]] = set()
    if principais:
        for k in (1, 2, 3, 4, 6, 9, 14):
            lista.add((y + k, 1))
    else:
        a, m = y, ref.month
        for _ in range(3):  # próximos 3 vencimentos mensais
            m += 1
            if m > 12:
                a, m = a + 1, 1
            lista.add((a, m))
        for a in range(y, y + 4):
            for m in (1, 4, 7, 10):
                lista.add((a, m))
        for a in range(y + 1, y + anos_max + 1):
            lista.add((a, 1))
    regs = []
    for a, m in sorted(lista):
        v = vencimento_di1(a, m)
        du = dias_uteis(ref, v)
        if du <= 0:
            continue
        regs.append({"contrato": codigo_di1(a, m), "rotulo": rotulo_vencimento(a, m),
                     "vencimento": v, "du_ref": du, "anos_ref": du / 252})
    return pd.DataFrame(regs)


def taxa_contrato(curva: pd.DataFrame, data_curva: date, vencimento: date, tipo="PRE") -> float:
    du = dias_uteis(data_curva, vencimento)
    if du <= 0:
        return np.nan
    return float(taxa_em(curva, du, tipo)[0])


# ----------------------------------------------------------------------------
# Tabelas comparativas
# ----------------------------------------------------------------------------
def tabela_contratos(curvas: dict[str, tuple[date, pd.DataFrame]], contratos: pd.DataFrame,
                     tipo="PRE") -> pd.DataFrame:
    """Linhas = contratos; colunas = taxa por período (mesmo contrato em cada data)."""
    out = contratos[["contrato", "rotulo", "vencimento", "anos_ref"]].copy()
    for nome, (d, c) in curvas.items():
        out[nome] = [taxa_contrato(c, d, v, tipo) for v in contratos["vencimento"]]
    return out


def tabela_prazos(curvas: dict[str, tuple[date, pd.DataFrame]], tipo="PRE",
                  prazos: dict[str, int] = PRAZOS_CM) -> pd.DataFrame:
    """Linhas = prazos constantes; colunas = taxa por período."""
    out = pd.DataFrame({"prazo": list(prazos), "du": list(prazos.values())})
    out["anos_ref"] = out["du"] / 252
    for nome, (_, c) in curvas.items():
        out[nome] = taxa_em(c, out["du"].values, tipo)
    return out


def variacoes_bps(tab: pd.DataFrame, ref: str, periodos: list[str]) -> pd.DataFrame:
    """Δ (bps) = ref − período, para cada período (positivo = abriu desde então)."""
    out = pd.DataFrame(index=tab.index)
    for p in periodos:
        if p != ref and p in tab:
            out[p] = (tab[ref] - tab[p]) * 100
    return out


def spreads_de(tab_prazos: pd.DataFrame, periodo: str) -> dict[str, float]:
    t = tab_prazos.set_index("prazo")[periodo]
    return {nome: (t.get(a, np.nan) - t.get(b, np.nan)) * 100 for nome, (a, b) in SPREADS.items()}


# ----------------------------------------------------------------------------
# Classificação do movimento (abertura/fechamento, inclinação, rotação, inversão)
# ----------------------------------------------------------------------------
def classificar(tab_prazos: pd.DataFrame, atual: str, passado: str, limiar_bps: float = 5.0) -> dict:
    t = tab_prazos.set_index("prazo")
    curto_a, curto_p = t.at["1A", atual], t.at["1A", passado]
    longo_lbl = "10A" if np.isfinite(t.at["10A", atual]) and np.isfinite(t.at["10A", passado]) else "5A"
    longo_a, longo_p = t.at[longo_lbl, atual], t.at[longo_lbl, passado]
    d_curto = (curto_a - curto_p) * 100
    d_longo = (longo_a - longo_p) * 100
    incl_a = (longo_a - curto_a) * 100
    incl_p = (longo_p - curto_p) * 100
    d_incl = incl_a - incl_p
    th = limiar_bps

    def mov(x):
        return "abriu" if x > th else "fechou" if x < -th else "estável"

    tags, rotacao = [], False
    if d_curto < -th and d_longo > th:
        rotacao = True
        tags.append("🔄 ROTAÇÃO: fechou no curto e abriu no longo (inclinação por rotação)")
    elif d_curto > th and d_longo < -th:
        rotacao = True
        tags.append("🔄 ROTAÇÃO: abriu no curto e fechou no longo (achatamento por rotação)")
    else:
        nivel = (d_curto + d_longo) / 2
        if nivel > th:
            tipo = "Bear steepener (abertura + inclinação)" if d_incl > th else \
                   "Bear flattener (abertura + achatamento)" if d_incl < -th else "Abertura paralela"
        elif nivel < -th:
            tipo = "Bull steepener (fechamento + inclinação)" if d_incl > th else \
                   "Bull flattener (fechamento + achatamento)" if d_incl < -th else "Fechamento paralelo"
        else:
            tipo = "Inclinou" if d_incl > th else "Achatou" if d_incl < -th else "Praticamente estável"
        tags.append(tipo)
    if incl_a < 0 <= incl_p:
        tags.append("⚠️ Curva INVERTEU (longo abaixo do curto)")
    elif incl_p < 0 <= incl_a:
        tags.append("Curva DESINVERTEU")
    elif incl_a < 0:
        tags.append("Curva segue invertida")
    return {
        "curto": f"1A {mov(d_curto)} ({d_curto:+.0f} bps)",
        "longo": f"{longo_lbl} {mov(d_longo)} ({d_longo:+.0f} bps)",
        "d_curto": d_curto, "d_longo": d_longo, "d_inclinacao": d_incl,
        "inclinacao_atual": incl_a, "inclinacao_passada": incl_p, "longo_lbl": longo_lbl,
        "tags": tags, "rotacao": rotacao,
    }


# ----------------------------------------------------------------------------
# Forwards implícitos anuais (jan→jan) — para comparar com Focus/Selic
# ----------------------------------------------------------------------------
def forwards_anuais(curva: pd.DataFrame, ref: date, anos: int = 6) -> pd.DataFrame:
    regs, prev_du, prev_f = [], 0, 1.0
    for a in range(ref.year + 1, ref.year + anos + 1):
        v = vencimento_di1(a, 1)
        du = dias_uteis(ref, v)
        tx = taxa_em(curva, du)[0]
        if not np.isfinite(tx):
            break
        f = (1 + tx / 100) ** (du / 252)
        fwd = ((f / prev_f) ** (252 / (du - prev_du)) - 1) * 100
        regs.append({"ano_calendario": a - 1, "periodo": f"jan/{(a-1)%100:02d}→jan/{a%100:02d}",
                     "forward": fwd, "taxa_spot": tx})
        prev_du, prev_f = du, f
    return pd.DataFrame(regs)


def inflacao_implicita(curva: pd.DataFrame, du) -> np.ndarray:
    pre, real = taxa_em(curva, du, "PRE"), taxa_em(curva, du, "DIC")
    return ((1 + pre / 100) / (1 + real / 100) - 1) * 100


# ----------------------------------------------------------------------------
# Séries históricas
# ----------------------------------------------------------------------------
def historico_prazos(hist: pd.DataFrame, prazos: dict[str, int] = PRAZOS_CM, tipo="PRE") -> pd.DataFrame:
    """hist = concat de curvas de várias datas. Retorna data × prazo (taxa %)."""
    regs = []
    for d, g in hist[hist["curva"] == tipo].groupby("data"):
        vals = interpolar(g["du"].values, g["taxa"].values, list(prazos.values()))
        regs.append({"data": d, **dict(zip(prazos, vals))})
    return pd.DataFrame(regs).sort_values("data").reset_index(drop=True) if regs else pd.DataFrame()


def historico_contrato(hist: pd.DataFrame, vencimento: date, tipo="PRE") -> pd.DataFrame:
    regs = []
    for d, g in hist[hist["curva"] == tipo].groupby("data"):
        du = dias_uteis(d.date(), vencimento)
        if du <= 0:
            continue
        regs.append({"data": d, "du": du, "taxa": interpolar(g["du"].values, g["taxa"].values, du)[0]})
    return pd.DataFrame(regs).sort_values("data").reset_index(drop=True) if regs else pd.DataFrame()
