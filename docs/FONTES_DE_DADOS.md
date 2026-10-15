# Fontes de dados — referência técnica

Anotações para manutenção. Se uma fonte mudar, é aqui que se começa.

## 1. B3 · Taxas de Mercado para Swaps (principal)

- URL: `https://www.b3.com.br/pesquisapregao/download?filelist=TS{AAMMDD}.ex_,`
  (ex.: `TS261013.ex_,` para 13/10/2026). Endpoint vigente desde dez/2025, segundo o pyettj 0.4.2.
- Resposta: ZIP → dentro, um `.ex_` (executável autoextraível) → ZIP interno (procurar `PK\x03\x04`) → `TaxaSwap.txt` (latin-1).
- ZIP vazio (≤ 22 bytes) = dia sem pregão ou arquivo ainda não publicado (sai no fim do dia).
- Layout de largura fixa (posições 0-based):

| Campo | Posição | Exemplo |
|---|---|---|
| código da curva | 21:26 | `PRE  `, `DIC  ` |
| descrição | 26:41 | `DIxPRE` |
| dias corridos | 41:46 | `00365` |
| dias úteis | 46:51 | `00252` |
| sinal | 51 | `+` |
| taxa (7 casas decimais, em %) | 52:66 | `00000141234567` → 14,1234567% |
| vértice F (fixo) / M (móvel) | 66 | `F` |

- Curvas usadas: `PRE` (DI x Pré, nominal) e `DIC` (DI x IPCA, real). Outras: `DOC`, `DCL`, `DIM`…

## 2. ANBIMA · ETTJ (reserva)

- `POST https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp`
- Form: `Idioma=PT`, `Dt_Ref=dd/mm/aaaa`, `saida=xml`.
- XML com tags `PARAMETRO` (Svensson por grupo), `VERTICES` (vértice em DU, IPCA, prefixado, inflação implícita),
  `CIRCULAR`, `ERRO`. O parser lê os atributos de `VERTICES` pelo nome (contém "vert", "pre", "ipca").
- Datas antigas podem não estar disponíveis publicamente.

## 3. B3 · DI1 intradiário

- `GET https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1`
- JSON: `Scty[]` com `symb` (DI1F27), `SctyQtn` (`prvsDayAdjstmntPric`, `opngPric`, `minPric`, `maxPric`, `curPrc`),
  `buyOffer.price`, `sellOffer.price`, `asset.AsstSummry` (`opnCtrcts`, `traddCtrctsQty`, `mtrtyCode`).
- Se o valor vier como PU (> 200), é convertido: taxa = (100.000/PU)^(252/DU) − 1.

## 4. Banco Central

- Selic meta: `https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial=dd/mm/aaaa&dataFinal=dd/mm/aaaa`
- Focus anual: `https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais`
  com `$filter=(Indicador eq 'Selic' or Indicador eq 'IPCA') and baseCalculo eq 0`, `$orderby=Data desc`.

## Convenções

- DU entre data de referência e vencimento: intervalo `[ref, venc)` (o dia de referência conta).
- Vencimento do DI1: 1º dia útil do mês do código (F=jan, G=fev, H=mar, J=abr, K=mai, M=jun, N=jul, Q=ago, U=set, V=out, X=nov, Z=dez).
- Interpolação: flat-forward 252 (log do fator linear em DU). Antes do 1º vértice: taxa constante; depois do último: sem dado.
