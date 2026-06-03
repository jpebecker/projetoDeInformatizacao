"""
extract.py — VizGov
====================
ETL pipeline for Brazilian public fiscal data via the SICONFI REST API
(National Treasury — Tesouro Nacional).

Standalone usage (populate the local database):
    python extract.py                               # current year, all entities
    python extract.py --anos 2023 2024              # specific years, all entities
    python extract.py --ufs BR SC SP                # specific entities, current year
    python extract.py --all --start 2015            # full backfill from 2015
    python extract.py --ufs BR --anos 2024 --force  # force re-collection
    python extract.py --list-ufs                    # list available entities

Output JSON format:
    database/UF/receitas_YYYY.json → [{"ORIGEM RECEITA": "...", "VALOR REALIZADO": 123.45}, ...]
    database/UF/despesas_YYYY.json → [{"funcao": "...", "valor": 123.45}, ...]
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime

import pandas as pd
import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SICONFI_URL  = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
DATABASE_DIR = "database"
CURRENT_YEAR = datetime.today().year
THROTTLE     = 1.0   # seconds between API requests
TIMEOUT      = 90    # request timeout in seconds

# ─────────────────────────────────────────────────────────────────────────────
# ENTITIES  (state abbreviation → IBGE code)
# ─────────────────────────────────────────────────────────────────────────────

ENTES: dict[str, int] = {
    "BR": 1,
    "AC": 12, "AL": 27, "AP": 16, "AM": 13, "BA": 29,
    "CE": 23, "DF": 53, "ES": 32, "GO": 52, "MA": 21,
    "MT": 51, "MS": 50, "MG": 31, "PA": 15, "PB": 25,
    "PR": 41, "PE": 26, "PI": 22, "RJ": 33, "RN": 24,
    "RS": 43, "RO": 11, "RR": 14, "SC": 42, "SP": 35,
    "SE": 28, "TO": 17,
}

# ─────────────────────────────────────────────────────────────────────────────
# OFFICIAL BUDGET FUNCTIONS  (Ministerial Order MOG nº 42/1999)
# Names are reproduced exactly as returned by the SICONFI API in the "conta" field.
# ─────────────────────────────────────────────────────────────────────────────

FUNCOES_ORCAMENTARIAS: dict[str, str] = {
    "Legislativa":           "01",
    "Judiciária":            "02",
    "Essencial à Justiça":   "03",
    "Administração":         "04",
    "Defesa Nacional":       "05",
    "Segurança Pública":     "06",
    "Relações Exteriores":   "07",
    "Assistência Social":    "08",
    "Previdência Social":    "09",
    "Saúde":                 "10",
    "Trabalho":              "11",
    "Educação":              "12",
    "Cultura":               "13",
    "Direitos da Cidadania": "14",
    "Urbanismo":             "15",
    "Habitação":             "16",
    "Saneamento":            "17",
    "Gestão Ambiental":      "18",
    "Ciência e Tecnologia":  "19",
    "Agricultura":           "20",
    "Organização Agrária":   "21",
    "Indústria":             "22",
    "Comércio e Serviços":   "23",
    "Comunicações":          "24",
    "Energia":               "25",
    "Transporte":            "26",
    "Desporto e Lazer":      "27",
    "Encargos Especiais":    "28",
}

_FUNCAO_NOMES = set(FUNCOES_ORCAMENTARIAS.keys())

# ─────────────────────────────────────────────────────────────────────────────
# REVENUE ACCOUNT CODES  (Annex 03 — direct subcategories of CURRENT REVENUES)
#
# cod_conta values to INCLUDE (gross current revenue categories):
#   ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB → Taxes and Levies
#   RREO3ReceitaDeContribuicoes                          → Social Contributions
#   RREO3ReceitaPatrimonial                              → Asset Income
#   RREO3ReceitaAgropecuaria                             → Agricultural Revenue
#   RREO3ReceitaIndustrial                               → Industrial Revenue
#   RREO3ReceitaDeServicos                               → Service Revenue
#   RREO3TransferenciasCorrentes                         → Current Transfers
#   RREO3OutrasReceitasCorrentes                         → Other Current Revenues
#
# cod_conta values EXCLUDED (aggregates, deductions, and net figures):
#   ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB → CURRENT REVENUES (I) — grand total
#   ReceitasCorrentesAClassificar                        → unclassified / negative
#   DeducoesDaReceitaCorrenteLiquida                     → DEDUCTIONS (II) — header
#   children of deductions (Contrib*, Compensacao*, etc.)
#   RREO3ReceitaCorrenteLiquida                          → Net Current Revenue = I − II
# ─────────────────────────────────────────────────────────────────────────────

_RECEITA_COD_INCLUIR = {
    "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB",
    "RREO3ReceitaDeContribuicoes",
    "RREO3ReceitaPatrimonial",
    "RREO3ReceitaAgropecuaria",
    "RREO3ReceitaIndustrial",
    "RREO3ReceitaDeServicos",
    "RREO3TransferenciasCorrentes",
    "RREO3OutrasReceitasCorrentes",
}

# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def setup() -> None:
    os.makedirs(DATABASE_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

# ─────────────────────────────────────────────────────────────────────────────
# PATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _uf_dir(uf: str) -> str:
    path = os.path.join(DATABASE_DIR, uf.upper())
    os.makedirs(path, exist_ok=True)
    return path

def _json_path(tipo: str, uf: str, year: int) -> str:
    return os.path.join(_uf_dir(uf), f"{tipo}_{year}.json")

def file_exists(tipo: str, uf: str, year: int) -> bool:
    return os.path.exists(_json_path(tipo, uf, year))

def get_available_years(tipo: str, uf: str) -> list[int]:
    """Return sorted list of years for which a local JSON file exists."""
    folder = os.path.join(DATABASE_DIR, uf.upper())
    if not os.path.exists(folder):
        return []
    years = []
    prefix = f"{tipo}_"
    for f in os.listdir(folder):
        if f.startswith(prefix) and f.endswith(".json"):
            y = f[len(prefix):-5]
            if y.isdigit() and len(y) == 4:
                years.append(int(y))
    return sorted(years)

def _save(tipo: str, uf: str, year: int, data: list) -> None:
    path = _json_path(tipo, uf, year)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logging.info("Saved: %s  (%d records)", path, len(data))

# ─────────────────────────────────────────────────────────────────────────────
# BIMESTER RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def _bimestres(year: int) -> list[int]:
    """
    Return the ordered list of bimesters to attempt for a given year.

    Past years always use bimester 6 (full annual report).
    For the current year, start from the bimester immediately before the
    running one and cascade downward — published data typically lags one
    bimester behind the calendar.
    """
    if year < CURRENT_YEAR:
        return [6]
    current_bimester = (datetime.today().month - 1) // 2 + 1
    best = max(1, current_bimester - 1)
    return list(range(best, 0, -1))

# ─────────────────────────────────────────────────────────────────────────────
# SICONFI API ACCESS
# ─────────────────────────────────────────────────────────────────────────────

def _fetch(id_ente: int, year: int, bimestre: int, anexo: str) -> pd.DataFrame:
    """
    Fetch a single RREO annex from the SICONFI API with up to 3 retries.
    Returns an empty DataFrame if all attempts fail or the response is empty.
    """
    params = {
        "an_exercicio":          year,
        "nr_periodo":            bimestre,
        "co_tipo_demonstrativo": "RREO",
        "no_anexo":              anexo,
        "id_ente":               id_ente,
    }
    for attempt in range(1, 4):
        try:
            r = requests.get(SICONFI_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            items = r.json().get("items", [])
            if items:
                return pd.DataFrame(items)
            return pd.DataFrame()
        except Exception as e:
            logging.warning("Attempt %d/3 failed (%s b%s): %s", attempt, anexo, bimestre, e)
            if attempt < 3:
                time.sleep(2 ** attempt)
    return pd.DataFrame()

def _fetch_melhor_bimestre(id_ente: int, year: int, anexo: str) -> tuple[pd.DataFrame, int | None]:
    """
    Try each candidate bimester in order and return the first successful result.
    Returns (DataFrame, bimester_used) or (empty DataFrame, None) if all fail.
    """
    for b in _bimestres(year):
        df = _fetch(id_ente, year, b, anexo)
        if not df.empty:
            return df, b
    return pd.DataFrame(), None

# ─────────────────────────────────────────────────────────────────────────────
# REVENUE COLLECTION  —  RREO Annex 03
# Output: [{"ORIGEM RECEITA": "...", "VALOR REALIZADO": 123.45}, ...]
#
# Why NOT to use "TOTAL (ÚLTIMOS 12 MESES)":
#   That column is a rolling 12-month window ending at the last month of the
#   bimester (MR). For bimester 2/2026 it covers May/2025–Apr/2026, not the
#   year-to-date Jan–Apr/2026 — producing values nearly identical to a full
#   prior year.
#
# Correct approach: sum only the monthly <MR-N>...<MR> columns that cover
#   the months elapsed in the current fiscal year:
#     bimester 1 → <MR-1>, <MR>                   (2 months: Jan–Feb)
#     bimester 2 → <MR-3>, <MR-2>, <MR-1>, <MR>  (4 months: Jan–Apr)
#     bimester 3 → <MR-5>...<MR>                  (6 months: Jan–Jun)
#     bimester 4 → <MR-7>...<MR>                  (8 months: Jan–Aug)
#     bimester 5 → <MR-9>...<MR>                  (10 months: Jan–Oct)
#     bimester 6 → <MR-11>...<MR>                 (12 months: Jan–Dec)
#   At bimester 6 the result is identical to the TOTAL column, but the
#   method is correct and consistent across all bimesters.
# ─────────────────────────────────────────────────────────────────────────────

def _mr_cols(bimestre: int) -> list[str]:
    """Return the <MR-N> column names that cover the fiscal year up to the given bimester."""
    n = bimestre * 2  # number of months elapsed in the fiscal year
    cols = [f"<MR-{i}>" for i in range(n - 1, 0, -1)]
    cols.append("<MR>")
    return cols


def _collect_receitas(uf: str, year: int) -> bool:
    id_ente = ENTES.get(uf.upper())
    if id_ente is None:
        logging.error("Unknown entity: %s", uf)
        return False

    df, bim = _fetch_melhor_bimestre(id_ente, year, "RREO-Anexo 03")
    if df.empty:
        logging.warning("Revenues %s/%s | no data returned by API", uf, year)
        return False

    if not {"coluna", "cod_conta", "conta", "valor"}.issubset(df.columns):
        logging.warning("Revenues %s/%s | unexpected columns: %s", uf, year, df.columns.tolist())
        return False

    # Select only the monthly columns that correspond to the fiscal year to date
    cols_ytd = _mr_cols(bim)
    cols_presentes = [c for c in cols_ytd if c in df["coluna"].values]

    if not cols_presentes:
        logging.warning(
            "Revenues %s/%s | no monthly columns found (expected: %s, available: %s)",
            uf, year, cols_ytd, df["coluna"].unique().tolist()
        )
        return False

    if len(cols_presentes) < len(cols_ytd):
        logging.warning(
            "Revenues %s/%s | partial columns: %d/%d months available",
            uf, year, len(cols_presentes), len(cols_ytd)
        )

    # Filter to revenue categories and YTD columns
    df_ytd = df[
        df["coluna"].isin(cols_presentes) &
        df["cod_conta"].isin(_RECEITA_COD_INCLUIR)
    ].copy()
    df_ytd["valor"] = pd.to_numeric(df_ytd["valor"], errors="coerce").fillna(0.0)

    if df_ytd.empty:
        logging.warning("Revenues %s/%s | no rows after filtering", uf, year)
        return False

    # Sum monthly values per category (each category appears once per <MR> column)
    grouped = (
        df_ytd.groupby("conta")["valor"]
        .sum()
        .reset_index()
        .query("valor > 0")
        .sort_values("valor", ascending=False)
    )

    if grouped.empty:
        logging.warning("Revenues %s/%s | zero total after aggregation", uf, year)
        return False

    output = [
        {
            "ORIGEM RECEITA":  row["conta"],
            "VALOR REALIZADO": round(row["valor"], 2),
        }
        for _, row in grouped.iterrows()
    ]

    _save("receitas", uf, year, output)
    total = sum(r["VALOR REALIZADO"] for r in output)
    logging.info(
        "Revenues %s/%s | bimester=%s | columns=%s | %d categories | %s",
        uf, year, bim, cols_presentes, len(output), format_currency(total)
    )
    return True

# ─────────────────────────────────────────────────────────────────────────────
# EXPENDITURE COLLECTION  —  RREO Annex 02
# Output: [{"funcao": "...", "valor": 123.45}, ...]
# ─────────────────────────────────────────────────────────────────────────────

# Accepted column names for settled expenditures (naming varied in earlier API versions)
_DESPESA_COLS = [
    "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)",
    "Até o Bimestre (d)",
]


def _collect_despesas(uf: str, year: int) -> bool:
    id_ente = ENTES.get(uf.upper())
    if id_ente is None:
        logging.error("Unknown entity: %s", uf)
        return False

    df, bim = _fetch_melhor_bimestre(id_ente, year, "RREO-Anexo 02")
    if df.empty:
        logging.warning("Expenditures %s/%s | no data returned by API", uf, year)
        return False

    if not {"rotulo", "coluna", "conta", "valor"}.issubset(df.columns):
        logging.warning("Expenditures %s/%s | unexpected columns: %s", uf, year, df.columns.tolist())
        return False

    # Early fiscal years (2015–2016) or responses with no "rotulo" field use a
    # relaxed filter; all other years restrict to non-intra-budgetary rows only.
    if year in (2015, 2016) or df["rotulo"].isna().all():
        df_col = df[df["coluna"].isin(_DESPESA_COLS)].copy()
    else:
        mask = (
            df["rotulo"].str.contains("Exceto Intra", na=False, case=False)
            & (df["coluna"] == _DESPESA_COLS[0])
        )
        df_col = df[mask].copy()

    if df_col.empty:
        logging.warning("Expenditures %s/%s | no rows after label + column filter", uf, year)
        return False

    df_col["valor"] = pd.to_numeric(df_col["valor"], errors="coerce").fillna(0.0)

    # Keep only the 28 official budget functions; discard sub-functions and totals
    df_funcoes = df_col[
        df_col["conta"].isin(_FUNCAO_NOMES) &
        (df_col["valor"] > 0)
    ]

    if df_funcoes.empty:
        logging.warning("Expenditures %s/%s | no budget functions found after filtering", uf, year)
        return False

    # Keys must match exactly what despesa.html and the AJAX endpoint expect
    output = [
        {
            "funcao": row["conta"],
            "valor":  round(row["valor"], 2),
        }
        for _, row in df_funcoes.sort_values("valor", ascending=False).iterrows()
    ]

    _save("despesas", uf, year, output)
    total = sum(r["valor"] for r in output)
    logging.info("Expenditures %s/%s | bimester=%s | %d functions | %s",
                 uf, year, bim, len(output), format_currency(total))
    return True

# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API  (imported by main.py)
# ─────────────────────────────────────────────────────────────────────────────

def collect(ufs: list[str] = None, years: list[int] = None, force: bool = False) -> None:
    """
    Collect revenues and expenditures for the given entities and years.
    Skips files that already exist unless force=True.
    """
    if ufs is None:
        ufs = list(ENTES.keys())
    if years is None:
        years = [CURRENT_YEAR]

    for year in years:
        for uf in ufs:
            for tipo, fn in [
                ("receitas", _collect_receitas),
                ("despesas", _collect_despesas),
            ]:
                if not force and file_exists(tipo, uf, year):
                    logging.info("Already exists: %s %s/%s — skipping", tipo, uf, year)
                    continue
                fn(uf, year)
                time.sleep(THROTTLE)

# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY UTILITIES  (imported by main.py)
# ─────────────────────────────────────────────────────────────────────────────

def format_currency(value: float) -> str:
    """Format a numeric value as a compact BRL string (Tri / Bi / Mi)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "R$ 0,00"
    if v >= 1_000_000_000_000:
        return f"R$ {v / 1_000_000_000_000:.2f} Tri"
    if v >= 1_000_000_000:
        return f"R$ {v / 1_000_000_000:.2f} Bi"
    if v >= 1_000_000:
        return f"R$ {v / 1_000_000:.2f} Mi"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def parse_value(v) -> float:
    """Safely coerce any numeric or string representation to float."""
    try:
        if isinstance(v, (int, float)):
            return float(v)
        return float(str(v).replace(".", "").replace(",", "."))
    except Exception:
        return 0.0

def total_receitas(data: list) -> float:
    """Sum all realised revenue values from a revenues JSON list."""
    return sum(parse_value(r.get("VALOR REALIZADO", 0)) for r in data)

def total_despesas(data: list) -> float:
    """Sum all settled expenditure values from an expenditures JSON list."""
    return sum(parse_value(r.get("valor", 0)) for r in data)

def chart_receitas(data: list) -> tuple[list, list, float]:
    """
    Prepare revenue data for a chart.
    Returns (labels, values, total) — top 7 categories plus an 'Others' bucket.
    """
    items = sorted(
        [{"name": r["ORIGEM RECEITA"], "value": parse_value(r["VALOR REALIZADO"])} for r in data],
        key=lambda x: x["value"], reverse=True
    )
    total = sum(i["value"] for i in items)
    top, rest = items[:7], items[7:]
    if rest:
        top.append({"name": "Outros", "value": sum(i["value"] for i in rest)})
    return [i["name"] for i in top], [i["value"] for i in top], total

def chart_despesas(data: list) -> tuple[list, list, float]:
    """
    Prepare expenditure data for a chart.
    Returns (labels, values, total) — top 8 functions plus an 'Others' bucket.
    """
    items = sorted(
        [{"name": r["funcao"], "value": parse_value(r["valor"])} for r in data],
        key=lambda x: x["value"], reverse=True
    )
    total = sum(i["value"] for i in items)
    top, rest = items[:8], items[8:]
    if rest:
        top.append({"name": "Outros", "value": sum(i["value"] for i in rest)})
    return [i["name"] for i in top], [i["value"] for i in top], total

# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="VizGov — SICONFI fiscal data collection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ufs",      nargs="+", default=["ALL"], metavar="UF")
    parser.add_argument("--anos",     nargs="+", type=int, metavar="ANO")
    parser.add_argument("--start",    type=int,  default=2015)
    parser.add_argument("--all",      action="store_true", help="Collect all years from --start")
    parser.add_argument("--force",    action="store_true", help="Overwrite existing files")
    parser.add_argument("--list-ufs", action="store_true")

    args = parser.parse_args()

    if args.list_ufs:
        for uf, cod in sorted(ENTES.items()):
            flag = " ← Federal government" if uf == "BR" else ""
            print(f"  {uf:>4}  cod_ibge={cod}{flag}")
        return

    # Resolve entities
    ufs_raw = [u.upper() for u in args.ufs]
    if "ALL" in ufs_raw:
        ufs = sorted(ENTES.keys())
    else:
        unknown = [u for u in ufs_raw if u not in ENTES]
        if unknown:
            parser.error(f"Unknown entity/entities: {unknown}")
        ufs = ufs_raw

    # Resolve years
    if args.anos:
        years = args.anos
    elif args.all:
        years = list(range(args.start, CURRENT_YEAR + 1))
    else:
        years = [CURRENT_YEAR]

    setup()
    logging.info("Starting collection | years=%s | entities=%s | force=%s", years, ufs, args.force)
    t0 = time.time()
    collect(ufs=ufs, years=years, force=args.force)
    logging.info("Completed in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()