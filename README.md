# 📈 Curva de Juros Brasil · DI / ETTJ

Dashboard interativo (Streamlit + Plotly) para acompanhar **abertura e fechamento da curva de juros brasileira**,
comparando a curva atual com 1 mês, 3 meses, 6 meses, 1 ano, 2 anos atrás e qualquer data livre.

100% gratuito: dados públicos (B3, ANBIMA, Banco Central), sem chave de API, hospedagem grátis.

## O que o dashboard mostra

| Aba | Conteúdo |
|---|---|
| **Curvas** | Curvas sobrepostas (atual × períodos), hover com taxa e Δ em bps vs atual, linha da Selic meta, e **leitura automática do movimento** (abriu/fechou no curto e no longo, bull/bear steepener/flattener, **rotação** e **inversão** em destaque) |
| **Variação (bps)** | Barras por vértice com faixas curto / intermediário / longo + **heatmap** vértice × período (🟥 abertura, 🟩 fechamento) |
| **Inclinação** | Spreads 2A−1A, 5A−2A, 10A−2A, 10A−5A por período e evolução histórica |
| **Tabela** | Contratos DI1 (jan/27, 28, 29, 30, 32, 35, 40…) e prazos constantes, com taxas e Δ por período |
| **Real × Nominal** | Curva prefixada × IPCA+ e inflação implícita (breakeven) nos mesmos períodos |
| **Histórico** | Evolução de qualquer contrato (ex.: DI1F29) ou prazo constante nos últimos 6m–3 anos, com Selic meta |
| **Selic & Focus** | Forwards anuais implícitos na curva × mediana do Focus para a Selic |
| **Ao vivo** | DI1 intradiário da B3 (ajuste anterior × abertura × último, atraso ~15 min) |
| **Exportar** | CSVs (separador `;`, vírgula decimal — abre direto no Excel) |

Na barra lateral você escolhe a data de referência, quais períodos comparar, a convenção de datas (mesmo dia ou
fim do mês), uma data livre, vértices (contratos fixos ou prazos constantes), eixo X, janela e frequência do histórico.
O tema claro/escuro segue o sistema e pode ser trocado em **⋮ › Settings › Theme**.

## Fontes de dados

| Dado | Fonte | Observação |
|---|---|---|
| Curva **DI x Pré** (nominal) e **DI x IPCA** (real) | B3 – arquivo *Taxas de Mercado para Swaps* (`TS{AAMMDD}.ex_`, Pesquisa por Pregão) | Construída a partir dos **ajustes diários do DI1**. Histórico de anos. |
| ETTJ prefixada/IPCA (reserva) | ANBIMA – `est-termo/CZ-down.asp` | Usada automaticamente se a B3 falhar |
| DI1 intradiário | B3 – `cotacao.b3.com.br` | Atraso de ~15 min; pode não responder fora do Brasil |
| Selic meta | BCB – SGS série 432 | |
| Focus | BCB – API Olinda `ExpectativasMercadoAnuais` | Mediana mais recente |

**Taxa de um contrato** (ex.: DI1F29) em cada data = curva daquela data interpolada em *flat-forward 252* nos dias úteis
até o vencimento (1º dia útil do mês). **Dias úteis** pelo calendário nacional ANBIMA (`core/calendario.py`).
Mais detalhes em [`docs/FONTES_DE_DADOS.md`](docs/FONTES_DE_DADOS.md).

## Estrutura

```
curva-juros-br/
├── app.py                 # interface Streamlit (abas, barra lateral, KPIs)
├── core/
│   ├── fontes.py          # downloads B3/ANBIMA/BCB + cache em disco (Parquet)
│   ├── analise.py         # interpolação, vértices, spreads, rotação, forwards
│   ├── graficos.py        # figuras Plotly (cores das séries em CORES)
│   └── calendario.py      # dias úteis / feriados ANBIMA, vencimentos DI1
├── docs/FONTES_DE_DADOS.md
├── .streamlit/config.toml # tema claro/escuro
├── requirements.txt
└── Dockerfile             # só para Hugging Face Spaces
```

## Rodar localmente

Requer Python 3.10+.

```bash
git clone https://github.com/SEU_USUARIO/curva-juros-br.git
cd curva-juros-br
python -m venv .venv
# Windows: .venv\Scripts\activate    |   Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Abre em http://localhost:8501. A primeira carga do histórico baixa ~100 arquivos da B3 (≈1 min); depois fica em
cache na pasta `.cache_curvas/`.

## Publicar grátis

### 1. Criar o repositório no GitHub
1. Entre em https://github.com/new → nome `curva-juros-br` → **Public** → *Create repository*.
2. Envie os arquivos. Pelo navegador: **Add file › Upload files**, arraste todo o conteúdo da pasta
   (incluindo a pasta oculta `.streamlit`) e clique em *Commit changes*. Pelo terminal:
   ```bash
   git init && git add . && git commit -m "Dashboard curva de juros"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/curva-juros-br.git
   git push -u origin main
   ```

### 2. Streamlit Community Cloud (recomendado)
1. Acesse https://share.streamlit.io e entre com a conta do GitHub.
2. **Create app › Deploy a public app from GitHub**.
3. Repositório `SEU_USUARIO/curva-juros-br`, branch `main`, arquivo `app.py`.
4. (Opcional) *Advanced settings* → Python 3.12. Escolha a URL (ex.: `curva-juros.streamlit.app`).
5. **Deploy**. Em 2–3 minutos o app está no ar. Cada `git push` republica automaticamente.

> Apps gratuitos "dormem" após alguns dias sem acesso; basta abrir o link e clicar em *Wake up*.
> O cache em disco é apagado quando o app reinicia — ele se recompõe sozinho.

### 3. Alternativa: Hugging Face Spaces
1. https://huggingface.co/new-space → nome `curva-juros-br` → **SDK: Docker** (template *Blank*) → *Public* → *Create*.
2. Envie todos os arquivos (inclusive o `Dockerfile`) em **Files › Add file › Upload files**, ou faça `git push`
   para o repositório do Space.
3. No topo do `README.md` **do Space**, deixe este cabeçalho (o HF exige):
   ```yaml
   ---
   title: Curva de Juros Brasil
   emoji: 📈
   colorFrom: blue
   colorTo: indigo
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```
4. O build leva alguns minutos; depois o app abre em `https://huggingface.co/spaces/SEU_USUARIO/curva-juros-br`.

## Personalizar

- **Períodos de comparação**: dicionário `PERIODOS` no topo de `app.py` (nome → meses para trás) e `PERIODOS_PADRAO`.
- **Vértices principais**: `contratos_di1(..., principais=True)` em `core/analise.py` (anos à frente: 1, 2, 3, 4, 6, 9, 14).
- **Prazos constantes e spreads**: `PRAZOS_CM` e `SPREADS` em `core/analise.py`.
- **Cores das curvas**: `CORES` em `core/graficos.py`.
- **Feriado extraordinário**: adicione em `FERIADOS_EXTRAS` (`core/calendario.py`).
- **Tempo de cache**: `TTL_CACHE_S` (`app.py`) e `TTL_RECENTE_HORAS` (`core/fontes.py`).

## Tratamento de erros

- Feriado, fim de semana ou arquivo ainda não publicado → usa o **último dia útil com dados**.
- Falha da B3 → tenta a **ANBIMA**; falha de rede → aviso na tela, sem derrubar o app.
- Datas sem pregão ficam marcadas no cache para não serem baixadas de novo.
- **🔄 Atualizar dados** limpa o cache das datas recentes e baixa de novo.

## Aviso
Ferramenta de estudo. Os dados vêm de fontes públicas e podem conter atrasos ou erros; confira nas fontes oficiais
antes de qualquer decisão. Não é recomendação de investimento.

Créditos: método de leitura do arquivo TaxaSwap baseado na biblioteca open source
[pyettj](https://github.com/rafa-rod/pyettj).
