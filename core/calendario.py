"""
Calendário de dias úteis brasileiro (padrão ANBIMA / B3).

Regras dos feriados nacionais usados pela ANBIMA na contagem de dias úteis (DU/252):
  fixos  : 01/01, 21/04, 01/05, 07/09, 12/10, 02/11, 15/11, 20/11 (desde 2024), 25/12
  móveis : Carnaval (segunda e terça), Sexta-feira Santa e Corpus Christi (base: Páscoa)

O cálculo é feito por regra (sem download), então funciona offline e para qualquer ano.
Se precisar incluir um feriado extraordinário, adicione a data em FERIADOS_EXTRAS.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np

# Feriados pontuais/extraordinários (ex.: decretos). Formato: date(AAAA, M, D)
FERIADOS_EXTRAS: set[date] = set()


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=None)
def feriados_do_ano(ano: int) -> frozenset[date]:
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)]
    if ano >= 2024:  # Dia da Consciência Negra virou feriado nacional (Lei 14.759/2023)
        fixos.append((11, 20))
    fer = {date(ano, m, d) for m, d in fixos}
    p = _pascoa(ano)
    fer |= {p - timedelta(days=48), p - timedelta(days=47),  # Carnaval
            p - timedelta(days=2),                           # Sexta-feira Santa
            p + timedelta(days=60)}                          # Corpus Christi
    fer |= {x for x in FERIADOS_EXTRAS if x.year == ano}
    return frozenset(fer)


def eh_dia_util(d: date) -> bool:
    return d.weekday() < 5 and d not in feriados_do_ano(d.year)


def dia_util_anterior(d: date, incluir_hoje: bool = True) -> date:
    """Último dia útil <= d (ou < d se incluir_hoje=False)."""
    if not incluir_hoje:
        d -= timedelta(days=1)
    while not eh_dia_util(d):
        d -= timedelta(days=1)
    return d


def proximo_dia_util(d: date) -> date:
    while not eh_dia_util(d):
        d += timedelta(days=1)
    return d


def somar_dias_uteis(d: date, n: int) -> date:
    """Avança (n>0) ou recua (n<0) n dias úteis a partir de d."""
    passo = 1 if n >= 0 else -1
    restante = abs(n)
    while restante:
        d += timedelta(days=passo)
        if eh_dia_util(d):
            restante -= 1
    return d


def _feriados_np(ano_ini: int, ano_fim: int) -> np.ndarray:
    fer = set()
    for a in range(ano_ini, ano_fim + 1):
        fer |= feriados_do_ano(a)
    return np.array(sorted(fer), dtype="datetime64[D]")


def dias_uteis(inicio: date, fim: date) -> int:
    """
    Nº de dias úteis no intervalo [inicio, fim) — convenção B3 para DI1:
    o próprio dia de referência conta, o dia do vencimento não.
    """
    if fim <= inicio:
        return 0
    fer = _feriados_np(inicio.year, fim.year)
    return int(np.busday_count(np.datetime64(inicio), np.datetime64(fim), holidays=fer))


# Letras de vencimento dos contratos futuros da B3
MESES_CODIGO = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
CODIGO_MES = {v: k for k, v in MESES_CODIGO.items()}
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def vencimento_di1(ano: int, mes: int) -> date:
    """DI1 vence no 1º dia útil do mês de vencimento."""
    return proximo_dia_util(date(ano, mes, 1))


def codigo_di1(ano: int, mes: int) -> str:
    return f"DI1{CODIGO_MES[mes]}{ano % 100:02d}"


def rotulo_vencimento(ano: int, mes: int) -> str:
    return f"{MESES_PT[mes - 1]}/{ano % 100:02d}"
