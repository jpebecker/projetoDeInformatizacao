# VizGov

> Plataforma de visualização de dados fiscais públicos do Brasil. Receitas e despesas do governo federal e dos 27 estados, com série histórica de 2015 até o ano corrente.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-green)](https://flask.palletsprojects.com/)
[![pandas](https://img.shields.io/badge/pandas-2.0%2B-150458?logo=pandas)](https://pandas.pydata.org/)
[![D3.js](https://img.shields.io/badge/D3.js-7.x-orange)](https://d3js.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-purple)](https://getbootstrap.com/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

---

## Sobre o Projeto

O **VizGov** nasceu como trabalho final da disciplina **CIN7405 — Projeto de Informatização** da Universidade Federal de Santa Catarina (UFSC), com o objetivo de simplificar o acesso a dados fiscais públicos. O projeto original consolidava receitas e despesas de Santa Catarina e do governo federal disponíveis via Portal da Transparência.

Após a entrega acadêmica, o projeto foi reestruturado como portfólio pessoal: a fonte de dados migrou para a **API REST do SICONFI** (Tesouro Nacional), a cobertura foi expandida para todos os 27 estados mais o governo federal, e a interface ganhou visualizações interativas com mapa coroplético, seletor dinâmico de UF e série histórica completa.

---

## Funcionalidades

- **Mapa coroplético interativo** — distribuição de receitas ou despesas por estado, construído com D3.js + TopoJSON
- **Painel de Receitas** — composição por origem, evolução histórica e comparativo UF × federal
- **Painel de Despesas** — distribuição por função orçamentária, série temporal e proporção estadual
- **Seletor de UF customizado** — grid visual com 28 entes, busca por sigla ou nome completo
- **Série histórica 2015–presente** — backfill completo via CLI, sem reprocessar dados já existentes
- **Atualização AJAX** — troca de UF e ano sem reload de página
- **ETL automático no startup** — coleta dados do ano corrente para os entes que ainda não possuem arquivo local

---

## Fonte de Dados

Os dados são coletados exclusivamente via **API REST do SICONFI** (Sistema de Informações Contábeis e Fiscais do Setor Público Brasileiro), mantida pelo Tesouro Nacional. O VizGov não produz nem modifica os dados — apenas os coleta, processa e exibe.

| Endpoint SICONFI | Dados coletados | Coluna utilizada |
|---|---|---|
| `RREO-Anexo 03` | Receitas por origem | Colunas mensais `<MR-N>...<MR>` somadas para o YTD do ano |
| `RREO-Anexo 02` | Despesas liquidadas por função orçamentária | `DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)` |

> **Nota sobre receitas:** a coluna `"TOTAL (ÚLTIMOS 12 MESES)"` do Anexo 03 representa uma janela móvel de 12 meses e não o acumulado do ano corrente. Por isso, o VizGov soma as colunas mensais `<MR-N>...<MR>` correspondentes apenas aos meses do exercício em curso, garantindo um YTD correto para qualquer bimestre.

---

## Estrutura do Projeto

```
vizgov/
├── database/                      # JSONs gerados pelo extract.py
│   ├── BR/
│   │   ├── receitas_2024.json
│   │   └── despesas_2024.json
│   └── SC/ ...                    # Uma subpasta por ente (26 estados + DF + União)
├── templates/
│   ├── base.html                  # Layout base com navbar e footer
│   ├── index.html                 # Página inicial com mapa coroplético
│   ├── receita.html               # Painel de Receitas
│   ├── despesa.html               # Painel de Despesas
│   └── about.html                 # Sobre o projeto
├── extract.py                     # ETL + CLI: coleta SICONFI, processa com pandas, persiste JSON
└── main.py                        # Aplicação Flask — rotas SSR e endpoints AJAX
```

### Formato dos JSONs

Das Receitas
```json
[{"ORIGEM RECEITA": "Contribuições", "VALOR REALIZADO": 1377481271944.0},[]]
```
Das Despesas
```json
[{"funcao": "Previdência Social", "valor": 1046816000000.0},[]]
```

### Fluxo de dados

```
SICONFI API → extract.py (pandas) → database/{UF}/tipo_ano.json
                                              ↓
                                Flask (SSR + AJAX endpoints)
                                              ↓
                           Chart.js · D3.js · Bootstrap 5
```

---

## Instalação

### Pré-requisitos

- Python 3.10+
- pip

### Passos

```bash
# 1. Clonar o repositório
git clone https://github.com/jpebecker/vizgov.git
cd vizgov

# 2. Criar e ativar ambiente virtual
python -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows

# 3. Instalar dependências
pip install flask pandas requests

# 4. Popular o banco de dados histórico
python extract.py --all --start 2015

# 5. Subir o servidor
python main.py
```

A aplicação estará disponível em `http://localhost:5000`. No primeiro startup, o servidor coleta automaticamente os dados do ano corrente para os entes que ainda não possuem arquivo local.

---

## Coleta de Dados (CLI)

Todo o ETL é feito pelo `extract.py`, que também serve como script standalone para backfill e recoleta.

```bash
# Coletar o ano atual para todos os entes
python extract.py

# Coletar anos específicos para todos os entes
python extract.py --anos 2023 2024

# Coletar um subconjunto de entes para o ano atual
python extract.py --ufs BR SC SP RJ

# Backfill completo: todos os entes, de 2015 até o ano atual
python extract.py --all --start 2015

# Backfill a partir de um ano específico
python extract.py --all --start 2020

# Combinar: entes e anos específicos
python extract.py --ufs BR SC --anos 2022 2023 2024

# Forçar recoleta mesmo que o arquivo já exista
python extract.py --ufs BR --anos 2024 --force

# Listar todos os entes disponíveis
python extract.py --list-ufs
```

Arquivos já existentes são ignorados por padrão — a coleta detecta automaticamente o que falta e processa apenas o necessário. O tempo de coleta é de aproximadamente **3 minutos por ano** para todos os 28 entes.

---

## Endpoints da API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Página inicial com mapa coroplético |
| `GET` | `/receitas?uf=SC&ano=2023` | Painel de Receitas (SSR) |
| `GET` | `/despesas?uf=SC&ano=2023` | Painel de Despesas (SSR) |
| `GET` | `/sobre` | Página sobre o projeto |
| `GET` | `/api/receitas?uf=SC&ano=2023` | JSON — dados de receitas para o painel |
| `GET` | `/api/despesas?uf=SC&ano=2023` | JSON — dados de despesas para o painel |
| `GET` | `/api/historico/receitas?uf=SC` | JSON — série temporal de receitas |
| `GET` | `/api/historico/despesas?uf=SC` | JSON — série temporal de despesas |
| `GET` | `/api/mapa/receitas?ano=2023` | JSON — totais por UF para o mapa coroplético |
| `GET` | `/api/mapa/despesas?ano=2023` | JSON — totais por UF para o mapa coroplético |
| `GET` | `/api/anos/receitas` | JSON — anos disponíveis no banco local |
| `GET` | `/api/anos/despesas` | JSON — anos disponíveis no banco local |

---

## Stack

| Camada | Tecnologias |
|---|---|
| Backend | Python 3.10+, Flask |
| ETL | pandas, requests |
| Visualização | Chart.js, D3.js, TopoJSON |
| Frontend | Bootstrap 5, Bootstrap Icons |
| Armazenamento | JSON (filesystem local) |

---

## Autor

**João Pedro Becker Schneider**

Ciência da Informação — UFSC

[GitHub](https://github.com/jpebecker) · [LinkedIn](https://linkedin.com/in/jpebecker) · [jpebecker@gmail.com](mailto:jpebecker@gmail.com)

---

## Limitações

**Granularidade bimestral**

O SICONFI publica dados consolidados por bimestre, não por dia. Para o ano corrente, os dados disponíveis correspondem sempre ao bimestre anterior ao corrente (o bimestre vigente costuma estar em fase de consolidação pelos entes). Isso significa que os dados mais recentes têm uma defasagem de aproximadamente dois meses em relação à execução orçamentária real.

**Padronização vs. atualidade**

O Portal da Transparência oferece dados mais atualizados, mas cada estado mantém seu próprio portal com estrutura e URLs distintas — o que inviabiliza a coleta padronizada em escala. O SICONFI, ao centralizar os dados de todos os entes em um único endpoint REST com estrutura uniforme, permite a cobertura nacional ao custo de uma defasagem bimestral.

---

## Licença

Distribuído sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.