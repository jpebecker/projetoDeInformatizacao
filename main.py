"""
main.py — VizGov
================
Flask application: server-side rendered pages and AJAX endpoints.

To populate the database before starting the server:
    python extract.py --all --start 2015

To run the server:
    python main.py
"""

import json
import os
import threading
from datetime import datetime

import extract
from flask import Flask, jsonify, render_template, request

# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

UFS_DISPONIVEIS = sorted(extract.ENTES.keys())

# ─────────────────────────────────────────────────────────────────────────────
# JINJA2 FILTERS
# ─────────────────────────────────────────────────────────────────────────────

@app.template_filter("format_brl")
def format_brl_filter(value):
    """Format a float as a BRL currency string: R$ 1.234.567,89"""
    try:
        v = float(value)
        return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"

# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL JINJA2 CONTEXT
# ─────────────────────────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return {"current_year": extract.CURRENT_YEAR}

# ─────────────────────────────────────────────────────────────────────────────
# LOCAL DATABASE READER
# ─────────────────────────────────────────────────────────────────────────────

def _load_json(tipo: str, uf: str, year: int) -> tuple[list, str]:
    """
    Load a local JSON file for the given data type, entity, and year.
    Returns (data, formatted_timestamp).
    """
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "database", uf.upper(), f"{tipo}_{year}.json"
    )
    try:
        if not os.path.exists(path):
            return [], "Pending collection..."
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d/%m/%Y às %H:%M")
        return data, ts
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return [], "Failed to load"

# ─────────────────────────────────────────────────────────────────────────────
# REQUEST HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _year(args) -> int:
    """Parse and validate the 'ano' query parameter; fall back to the current year."""
    try:
        y = int(args.get("ano", extract.CURRENT_YEAR))
        if 2015 <= y <= extract.CURRENT_YEAR:
            return y
    except (ValueError, TypeError):
        pass
    return extract.CURRENT_YEAR

def _uf(args) -> str:
    """Parse and validate the 'uf' query parameter; fall back to 'BR'."""
    uf = args.get("uf", "BR").upper()
    return uf if uf in extract.ENTES else "BR"

# ─────────────────────────────────────────────────────────────────────────────
# BASE ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/sobre")
def about():
    return render_template("about.html")

# ─────────────────────────────────────────────────────────────────────────────
# API — AVAILABLE YEARS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/anos/<tipo>")
def api_anos(tipo: str):
    if tipo not in ("receitas", "despesas"):
        return jsonify({"error": "Invalid type"}), 400
    anos: set[int] = set()
    for uf in UFS_DISPONIVEIS:
        anos |= set(extract.get_available_years(tipo, uf))
    return jsonify({"anos": sorted(anos, reverse=True)})

# ─────────────────────────────────────────────────────────────────────────────
# API — CHOROPLETH MAP
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/mapa/<tipo>")
def api_mapa(tipo: str):
    if tipo not in ("receitas", "despesas"):
        return jsonify({"error": "Invalid type"}), 400

    if request.args.get("ano"):
        year = _year(request.args)
    else:
        # Default to the most recent year available in the database
        anos: set[int] = set()
        for uf in UFS_DISPONIVEIS:
            anos |= set(extract.get_available_years(tipo, uf))
        year = max(anos) if anos else extract.CURRENT_YEAR

    fn_total = extract.total_receitas if tipo == "receitas" else extract.total_despesas
    result = {}
    for uf in UFS_DISPONIVEIS:
        if uf == "BR":
            continue  # federal aggregate is excluded from the state-level map
        data, _ = _load_json(tipo, uf, year)
        t = fn_total(data)
        if t > 0:
            result[uf] = round(t, 2)

    return jsonify({"ano": year, "tipo": tipo, "data": result})

# ─────────────────────────────────────────────────────────────────────────────
# API — REVENUES
# Response shape expected by receita.html (JS fetchData):
#   { ano, uf, data_atualizacao,
#     uf_data: { labels, values, total, total_txt, tabela },
#     total_br, total_br_txt }
#
# tabela items: {"ORIGEM RECEITA": "...", "VALOR REALIZADO": 123.45}
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/receitas")
def api_receitas():
    year        = _year(request.args)
    uf          = _uf(request.args)
    uf_data, ts = _load_json("receitas", uf,   year)
    br_data, _  = _load_json("receitas", "BR", year)

    labels, values, total_uf = extract.chart_receitas(uf_data)
    total_br = extract.total_receitas(br_data)

    return jsonify({
        "ano":              year,
        "uf":               uf,
        "data_atualizacao": ts,
        "uf_data": {
            "labels":    labels,
            "values":    values,
            "total":     total_uf,
            "total_txt": extract.format_currency(total_uf),
            "tabela":    uf_data,  # keys: "ORIGEM RECEITA", "VALOR REALIZADO"
        },
        "total_br":     total_br,
        "total_br_txt": extract.format_currency(total_br),
    })

# ─────────────────────────────────────────────────────────────────────────────
# API — EXPENDITURES
# Response shape expected by despesa.html (JS fetchData):
#   { ano, uf, data_atualizacao,
#     uf_data: { labels, values, total, total_txt, tabela },
#     total_br, total_br_txt }
#
# tabela items: {"funcao": "...", "valor": 123.45}
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/despesas")
def api_despesas():
    year        = _year(request.args)
    uf          = _uf(request.args)
    uf_data, ts = _load_json("despesas", uf,   year)
    br_data, _  = _load_json("despesas", "BR", year)

    labels, values, total_uf = extract.chart_despesas(uf_data)
    total_br = extract.total_despesas(br_data)

    return jsonify({
        "ano":              year,
        "uf":               uf,
        "data_atualizacao": ts,
        "uf_data": {
            "labels":    labels,
            "values":    values,
            "total":     total_uf,
            "total_txt": extract.format_currency(total_uf),
            "tabela":    uf_data,  # keys: "funcao", "valor"
        },
        "total_br":     total_br,
        "total_br_txt": extract.format_currency(total_br),
    })

# ─────────────────────────────────────────────────────────────────────────────
# API — HISTORICAL TIME SERIES
# Response shape: { anos: [...], br: [...], uf: [...], uf_label: "SC" }
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/historico/<tipo>")
def api_historico(tipo: str):
    if tipo not in ("receitas", "despesas"):
        return jsonify({"error": "Invalid type"}), 400

    uf       = _uf(request.args)
    fn_total = extract.total_receitas if tipo == "receitas" else extract.total_despesas

    anos = sorted(
        set(extract.get_available_years(tipo, "BR")) |
        set(extract.get_available_years(tipo, uf))
    )

    br_vals, uf_vals = [], []
    for y in anos:
        d_br, _ = _load_json(tipo, "BR", y)
        d_uf, _ = _load_json(tipo, uf,   y)
        br_vals.append(fn_total(d_br))
        uf_vals.append(fn_total(d_uf))

    return jsonify({"anos": anos, "br": br_vals, "uf": uf_vals, "uf_label": uf})

# ─────────────────────────────────────────────────────────────────────────────
# SERVER-SIDE RENDERED ROUTES
# ─────────────────────────────────────────────────────────────────────────────

def _render_panel(tipo: str, template: str, year: int, uf: str):
    """
    Shared rendering logic for the Revenues and Expenditures panels.
    Loads local JSON, computes chart data and totals, and passes them to the template.
    """
    uf_data, ts = _load_json(tipo, uf,   year)
    br_data, _  = _load_json(tipo, "BR", year)

    if tipo == "receitas":
        labels, values, total_uf = extract.chart_receitas(uf_data)
        total_br = extract.total_receitas(br_data)
    else:
        labels, values, total_uf = extract.chart_despesas(uf_data)
        total_br = extract.total_despesas(br_data)

    anos = sorted(
        set(extract.get_available_years(tipo, "BR")) |
        set(extract.get_available_years(tipo, uf)),
        reverse=True,
    )
    if not anos:
        anos = [extract.CURRENT_YEAR]

    return render_template(
        template,
        ano_selecionado  = year,
        anos_disponiveis = anos,
        uf_selecionada   = uf,
        ufs_disponiveis  = UFS_DISPONIVEIS,
        labels_uf        = labels,
        values_uf        = values,
        total_uf_txt     = extract.format_currency(total_uf),
        total_br         = total_br,
        total_br_txt     = extract.format_currency(total_br),
        lista_dados_uf   = uf_data,
        data_atualizacao = ts,
    )


@app.route("/receitas")
def revenues():
    return _render_panel("receitas", "receita.html", _year(request.args), _uf(request.args))


@app.route("/despesas")
def expenses():
    return _render_panel("despesas", "despesa.html", _year(request.args), _uf(request.args))

# ─────────────────────────────────────────────────────────────────────────────
# STARTUP ETL  (collect missing data for the current year on server start)
# ─────────────────────────────────────────────────────────────────────────────

def _startup_etl() -> None:
    year = extract.CURRENT_YEAR
    missing = [
        uf for uf in UFS_DISPONIVEIS
        if not extract.file_exists("receitas", uf, year)
        or not extract.file_exists("despesas", uf, year)
    ]
    if not missing:
        print(f"[VizGov] Data for {year} is complete — no collection required.")
        return
    print(f"[VizGov] Collecting {year} data in background for: {missing}")
    t = threading.Thread(
        target=extract.collect,
        kwargs={"ufs": missing, "years": [year], "force": False},
        daemon=True,
    )
    t.start()

# ─────────────────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        _startup_etl()
    app.run(debug=True)