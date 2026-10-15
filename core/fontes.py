"""
Obtenção de dados públicos (sem chave de API, sem custo).

FONTES
------
1) B3 · Arquivo "Taxas de Mercado para Swaps" (TaxaSwap) — PRINCIPAL
   https://www.b3.com.br/pesquisapregao/download?filelist=TS{AAMMDD}.ex_,
   Curvas referenciais da B3 calculadas a partir dos AJUSTES DIÁRIOS dos futuros:
     PRE = DI x Pré (construída com os ajustes do DI1, vértices em dias úteis)
     DIC = DI x IPCA (cupom de IPCA → curva real)
   Layout de largura fixa (manual B3): [21:26] código, [41:46] dias corridos,
   [46:51] dias úteis, [51] sinal, [52:66] taxa (7 casas decimais), [66] vértice F/M.
   (Método de captura baseado na biblioteca open source pyettj, de Rafael Rodrigues.)

2) ANBIMA · ETTJ (Prefixada, IPCA e inflação implícita) — RESERVA / COMPARAÇÃO
   POST https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp  (saida=xml)
   A ANBIMA pode limitar datas antigas; nesse caso o app segue só com a B3.

3) B3 · Cotações intradiárias do DI1 (atraso ~15 min) — ABA "AO VIVO"
   https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1

4) Banco Central · SGS (Selic meta, série 432) e Focus (expectativas anuais)
   https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados
   https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais

CACHE
-----
Cada data baixada é gravada em disco (Parquet) em CACHE_DIR. Datas passadas
não mudam, então ficam em cache permanente; datas recentes expiram após
TTL_RECENTE_HORAS para pegar republicações da B3.
"""
from __future__ import annotations

import io
import os
import time
import warnings
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd
import requests

from .calendario import MESES_CODIGO, dias_uteis, dia_util_anterior, eh_dia_util, vencimento_di1

# ----------------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------------
CACHE_DIR = Path(os.environ.get("CURVA_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache_curvas"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TTL_RECENTE_HORAS = 3          # datas dos últimos dias são rebaixadas após este prazo
DIAS_RECENTES = 4              # o que é considerado "recente" (dias corridos)
TIMEOUT = 40                   # segundos por requisição
MAX_THREADS = 6                # downloads paralelos (seja gentil com os servidores)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

CURVAS_B3 = ("PRE", "DIC")  # nominal e real (IPCA+)


class SemDados(Exception):
    """Data sem publicação (feriado, fim de semana, arquivo ainda não disponível)."""


class FonteIndisponivel(Exception):
    """Falha de rede/servidor — tentar novamente mais tarde."""


# ----------------------------------------------------------------------------
# HTTP com retry e fallback de TLS (alguns servidores da B3 têm cadeia incompleta)
# ----------------------------------------------------------------------------
def _http(method: str, url: str, tentativas: int = 3, **kw) -> requests.Response:
    kw.setdefault("timeout", TIMEOUT)
    headers = {**HEADERS, **kw.pop("headers", {})}
    ultimo: Exception | None = None
    verify = True
    for i in range(tentativas):
        try:
            r = requests.request(method, url, headers=headers, verify=verify, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise FonteIndisponivel(f"HTTP {r.status_code}")
            return r
        except requests.exceptions.SSLError as e:
            ultimo, verify = e, False
            warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        except (requests.exceptions.RequestException, FonteIndisponivel) as e:
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise FonteIndisponivel(f"{url.split('/')[2]}: {ultimo}")


# ----------------------------------------------------------------------------
# Cache em disco
# ----------------------------------------------------------------------------
def _arq(prefixo: str, d: date, ext: str = "parquet") -> Path:
    return CACHE_DIR / f"{prefixo}_{d:%Y%m%d}.{ext}"


def _cache_valido(p: Path, d: date) -> bool:
    if not p.exists():
        return False
    if (date.today() - d).days > DIAS_RECENTES:
        return True
    idade_h = (time.time() - p.stat().st_mtime) / 3600
    return idade_h < TTL_RECENTE_HORAS


def limpar_cache_recente() -> int:
    """Remove do disco os arquivos de datas recentes (usado pelo botão 'Atualizar')."""
    n = 0
    limite = date.today() - timedelta(days=DIAS_RECENTES)
    for p in CACHE_DIR.glob("*_*.*"):
        try:
            d = datetime.strptime(p.stem.split("_")[-1], "%Y%m%d").date()
        except ValueError:
            continue
        if d >= limite:
            p.unlink(missing_ok=True)
            n += 1
    return n


# ----------------------------------------------------------------------------
# 1) B3 TaxaSwap
# ----------------------------------------------------------------------------
def _extrair_taxaswap(raw: bytes) -> str:
    """ZIP externo → .ex_ (executável autoextraível) → ZIP interno → TaxaSwap.txt"""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        nomes = z.namelist()
        if not nomes:
            raise SemDados("arquivo vazio")
        interno = z.read(nomes[0])
    pos = interno.find(b"PK\x03\x04")
    if pos < 0:  # às vezes já vem o .txt direto
        return interno.decode("latin-1")
    with zipfile.ZipFile(io.BytesIO(interno[pos:])) as z2:
        return z2.read(z2.namelist()[0]).decode("latin-1")


def parse_taxaswap(txt: str, curvas: Iterable[str] = CURVAS_B3) -> pd.DataFrame:
    curvas = set(curvas)
    regs = []
    for linha in txt.splitlines():
        if len(linha) < 67:
            continue
        cod = linha[21:26].strip()
        if cod not in curvas:
            continue
        try:
            sinal = -1 if linha[51] == "-" else 1
            regs.append({
                "curva": cod,
                "dc": int(linha[41:46]),
                "du": int(linha[46:51]),
                "taxa": sinal * int(linha[52:66]) / 1e7,   # % a.a.
                "vertice": linha[66],
            })
        except (ValueError, IndexError):
            continue
    df = pd.DataFrame(regs, columns=["curva", "dc", "du", "taxa", "vertice"])
    return df.drop_duplicates(["curva", "du"]).sort_values(["curva", "du"]).reset_index(drop=True)


def baixar_taxaswap(d: date) -> pd.DataFrame:
    url = f"https://www.b3.com.br/pesquisapregao/download?filelist=TS{d:%y%m%d}.ex_,"
    r = _http("GET", url)
    if r.status_code == 404 or len(r.content) <= 22:  # ZIP vazio = 22 bytes
        raise SemDados(f"B3 sem arquivo para {d:%d/%m/%Y}")
    if r.status_code != 200:
        raise FonteIndisponivel(f"B3 HTTP {r.status_code}")
    try:
        df = parse_taxaswap(_extrair_taxaswap(r.content))
    except zipfile.BadZipFile as e:
        raise SemDados(f"B3: arquivo inválido em {d:%d/%m/%Y}") from e
    if df.empty or (df["curva"] == "PRE").sum() < 5:
        raise SemDados(f"B3: curva PRE ausente em {d:%d/%m/%Y}")
    return df


# ----------------------------------------------------------------------------
# 2) ANBIMA ETTJ
# ----------------------------------------------------------------------------
def _num(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace("%", "")
    if not s or s in ("-", "--"):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def baixar_anbima(d: date) -> pd.DataFrame:
    """ETTJ ANBIMA → mesmo formato da B3 (curva PRE e DIC=IPCA), vértices em DU."""
    r = _http("POST", "https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp",
              data={"Idioma": "PT", "Dt_Ref": d.strftime("%d/%m/%Y"), "saida": "xml"},
              headers={"Content-type": "application/x-www-form-urlencoded"})
    if r.status_code != 200 or "<" not in r.text:
        raise SemDados("ANBIMA sem dados")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise SemDados("ANBIMA: resposta não é XML (data indisponível)") from e
    regs = []
    for el in root.iter():
        if el.tag.upper() != "VERTICES":
            continue
        at = {k.lower(): v for k, v in el.attrib.items()}
        du = next((_num(v) for k, v in at.items() if "vert" in k), None)
        pre = next((_num(v) for k, v in at.items() if "pre" in k), None)
        ipca = next((_num(v) for k, v in at.items() if "ipca" in k), None)
        if du is None:
            continue
        if pre is not None:
            regs.append({"curva": "PRE", "dc": None, "du": int(du), "taxa": pre, "vertice": "A"})
        if ipca is not None:
            regs.append({"curva": "DIC", "dc": None, "du": int(du), "taxa": ipca, "vertice": "A"})
    df = pd.DataFrame(regs, columns=["curva", "dc", "du", "taxa", "vertice"])
    if (df["curva"] == "PRE").sum() < 3:
        raise SemDados("ANBIMA sem vértices para a data")
    return df.sort_values(["curva", "du"]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Curva de uma data (com cache e fallback B3 → ANBIMA)
# ----------------------------------------------------------------------------
def curva_do_dia(d: date) -> pd.DataFrame:
    """
    Retorna DataFrame [curva, dc, du, taxa, vertice, fonte, data] para a data d.
    Lança SemDados (feriado/sem publicação) ou FonteIndisponivel (rede).
    """
    if not eh_dia_util(d):
        raise SemDados(f"{d:%d/%m/%Y} não é dia útil")
    if d > date.today():
        raise SemDados("data futura")

    p, p_nd = _arq("curva", d), _arq("curva", d, "nodata")
    if _cache_valido(p, d):
        return pd.read_parquet(p)
    if _cache_valido(p_nd, d):
        raise SemDados(p_nd.read_text(encoding="utf-8") or "sem dados")

    erros = []
    for nome, func in (("B3", baixar_taxaswap), ("ANBIMA", baixar_anbima)):
        try:
            df = func(d)
            df["fonte"], df["data"] = nome, pd.Timestamp(d)
            df.to_parquet(p, index=False)
            p_nd.unlink(missing_ok=True)
            return df
        except SemDados as e:
            erros.append(("nodata", f"{nome}: {e}"))
        except FonteIndisponivel as e:
            erros.append(("rede", f"{nome}: {e}"))
    msg = " | ".join(m for _, m in erros)
    # A B3 é a referência de "houve pregão?": se ela respondeu "sem arquivo", é dia sem dados
    if erros[0][0] == "nodata":
        p_nd.write_text(msg, encoding="utf-8")  # evita baixar de novo a mesma data vazia
        raise SemDados(msg)
    raise FonteIndisponivel(msg)


def curva_mais_recente_ate(d: date, max_recuo: int = 7) -> pd.DataFrame:
    """Procura, a partir de d, o último dia útil com curva publicada (recuando até max_recuo dias úteis)."""
    alvo = dia_util_anterior(d)
    ultimo_erro: Exception = SemDados("sem dados")
    for _ in range(max_recuo + 1):
        try:
            return curva_do_dia(alvo)
        except SemDados as e:
            ultimo_erro = e
        # FonteIndisponivel (rede fora) sobe direto: não adianta recuar datas
        alvo = dia_util_anterior(alvo, incluir_hoje=False)
    raise ultimo_erro


def curvas_varias_datas(datas: list[date], progresso: Callable[[float], None] | None = None
                        ) -> tuple[pd.DataFrame, list[str]]:
    """Baixa (em paralelo) as curvas de várias datas. Retorna (df concatenado, lista de avisos)."""
    frames, avisos, feitos = [], [], 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as ex:
        futs = {ex.submit(curva_do_dia, d): d for d in datas}
        for f in as_completed(futs):
            d = futs[f]
            try:
                frames.append(f.result())
            except SemDados:
                pass  # feriado/sem pregão: normal na série histórica
            except Exception as e:  # noqa: BLE001
                avisos.append(f"{d:%d/%m/%Y}: {e}")
            feitos += 1
            if progresso:
                progresso(feitos / len(datas))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return df, avisos


# ----------------------------------------------------------------------------
# 3) DI1 ao vivo (cotação B3, atraso ~15 min)
# ----------------------------------------------------------------------------
def di1_ao_vivo() -> tuple[pd.DataFrame, str]:
    r = _http("GET", "https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1", tentativas=2, timeout=20)
    if r.status_code != 200:
        raise FonteIndisponivel(f"B3 cotação HTTP {r.status_code}")
    j = r.json()
    hoje = date.today()
    regs = []
    for s in j.get("Scty", []) or []:
        sy = (s.get("symb") or "").strip()
        if len(sy) != 6 or not sy.startswith("DI1") or sy[3] not in MESES_CODIGO:
            continue
        try:
            venc = vencimento_di1(2000 + int(sy[4:]), MESES_CODIGO[sy[3]])
        except ValueError:
            continue
        du = dias_uteis(hoje, venc)
        if du <= 0:
            continue
        q = s.get("SctyQtn") or {}
        a = (s.get("asset") or {}).get("AsstSummry") or {}

        def tx(v):
            v = _num(v) if not isinstance(v, (int, float)) else float(v)
            if not v:
                return None
            return (100000 / v) ** (252 / du) * 100 - 100 if v > 200 else v  # PU → taxa

        regs.append({
            "contrato": sy, "vencimento": venc, "du": du,
            "ajuste_anterior": tx(q.get("prvsDayAdjstmntPric")),
            "abertura": tx(q.get("opngPric")), "minima": tx(q.get("minPric")),
            "maxima": tx(q.get("maxPric")), "ultimo": tx(q.get("curPrc")),
            "compra": tx((s.get("buyOffer") or {}).get("price")),
            "venda": tx((s.get("sellOffer") or {}).get("price")),
            "negocios": a.get("traddCtrctsQty"), "contratos_abertos": a.get("opnCtrcts"),
        })
    df = pd.DataFrame(regs).sort_values("vencimento").reset_index(drop=True) if regs else pd.DataFrame()
    return df, (j.get("Msg") or {}).get("dtTm", "")


# ----------------------------------------------------------------------------
# 4) Banco Central: Selic meta e Focus
# ----------------------------------------------------------------------------
def selic_meta(inicio: date, fim: date) -> pd.DataFrame:
    url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json"
           f"&dataInicial={inicio:%d/%m/%Y}&dataFinal={fim:%d/%m/%Y}")
    r = _http("GET", url, tentativas=2, timeout=25)
    if r.status_code != 200:
        raise FonteIndisponivel(f"BCB HTTP {r.status_code}")
    df = pd.DataFrame(r.json())
    df["data"] = pd.to_datetime(df["data"], dayfirst=True)
    df["valor"] = df["valor"].astype(float)
    return df


def focus_anual(indicadores=("Selic", "IPCA")) -> pd.DataFrame:
    """Mediana mais recente do Focus por ano de referência."""
    filtro = " or ".join(f"Indicador eq '{i}'" for i in indicadores)
    url = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
           "ExpectativasMercadoAnuais")
    params = {"$top": "400", "$format": "json", "$orderby": "Data desc",
              "$filter": f"({filtro}) and baseCalculo eq 0",
              "$select": "Indicador,Data,DataReferencia,Mediana,Media,Minimo,Maximo,numeroRespondentes"}
    r = _http("GET", url, params=params, tentativas=2, timeout=30)
    if r.status_code != 200:
        raise FonteIndisponivel(f"Focus HTTP {r.status_code}")
    df = pd.DataFrame(r.json().get("value", []))
    if df.empty:
        raise SemDados("Focus vazio")
    df["Data"] = pd.to_datetime(df["Data"])
    ult = df["Data"].max()
    df = df[df["Data"] == ult].copy()
    df["DataReferencia"] = df["DataReferencia"].astype(int)
    return df.sort_values(["Indicador", "DataReferencia"]).reset_index(drop=True)
