import json, os,threading, time
from datetime import datetime

import extract as extractor
from flask import Flask, jsonify, render_template, request

# ==============================================================================
# FLASK APPLICATION
# ==============================================================================

app = Flask(__name__)


# ==============================================================================
# JINJA2 CUSTOM FILTER
# ==============================================================================

@app.template_filter("format_brl")
def format_brl_filter(value):
    """
    Jinja2 filter: format a float as Brazilian currency string.

    Usage in templates: {{ item.valor | format_brl }}

    Args:
        value: Numeric value (int, float, or str).

    Returns:
        str: e.g. "R$ 1.234.567,89"
    """
    try:
        v = float(value)
        formatted = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"
    except (TypeError, ValueError):
        return "R$ 0,00"


# ==============================================================================
# GLOBAL TEMPLATE CONTEXT
# ==============================================================================

@app.context_processor
def inject_globals():
    """Make shared variables globally available to all templates."""
    return {
        "current_year": extractor.CURRENT_YEAR
    }


# ==============================================================================
# JSON LOADER (multi-year aware)
# ==============================================================================

def load_json(file_prefix: str, year: int):
    """
    Load a collected JSON file for a specific prefix and year.

    Args:
        file_prefix (str): e.g. "receitas_BR"
        year (int): Target year.

    Returns:
        tuple:
            - list: Loaded data (empty list on failure)
            - str: Last update timestamp or status message
    """
    base_directory = os.path.dirname(os.path.abspath(__file__))
    file_name = f"{file_prefix}_{year}.json"
    file_path = os.path.join(base_directory, "database", file_name)

    try:
        if not os.path.exists(file_path):
            return [], "Aguardando extração..."

        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)

        timestamp = os.path.getmtime(file_path)
        formatted_timestamp = datetime.fromtimestamp(timestamp).strftime(
            "%d/%m/%Y às %H:%M"
        )
        return data, formatted_timestamp

    except Exception as error:
        print(f"Error loading {file_name}: {error}")
        return [], "Erro ao carregar arquivo"


# ==============================================================================
# YEAR RESOLUTION HELPER
# ==============================================================================

def resolve_year(request_args) -> int:
    """
    Extract and validate the 'ano' query parameter.
    Falls back to CURRENT_YEAR if missing or invalid.
    """
    try:
        year = int(request_args.get("ano", extractor.CURRENT_YEAR))
        if 2014 <= year <= extractor.CURRENT_YEAR:
            return year
    except (ValueError, TypeError):
        pass
    return extractor.CURRENT_YEAR


# ==============================================================================
# HOME AND ABOUT ROUTES
# ==============================================================================

@app.route("/")
def home():
    """Render landing page."""
    return render_template("index.html")


@app.route("/sobre")
def about():
    """Render about page."""
    return render_template("about.html")


# ==============================================================================
# API — AVAILABLE YEARS
# ==============================================================================

@app.route("/api/anos/<tipo>")
def available_years(tipo: str):
    """
    Return the list of years for which collected data exists.

    Example:
        GET /api/anos/receitas  →  {"anos": [2022, 2023, 2024, 2025]}
    """
    valid_tipos = {
        "receitas":      ("receitas_BR",      "receitas_SC"),
        "despesas":      ("despesas_BR",      "despesas_SC"),
        "investimentos": ("investimentos_BR",  "investimentos_SC"),
    }

    if tipo not in valid_tipos:
        return jsonify({"error": "Tipo inválido."}), 400

    prefix_br, prefix_sc = valid_tipos[tipo]
    years_br = set(extractor.get_available_years(prefix_br))
    years_sc = set(extractor.get_available_years(prefix_sc))
    available = sorted(years_br | years_sc, reverse=True)

    return jsonify({"anos": available})


# ==============================================================================
# API — CHART DATA (AJAX endpoints)
# ==============================================================================

@app.route("/api/receitas")
def api_receitas():
    """Return revenues chart data for a given year as JSON."""
    year = resolve_year(request.args)

    brazil_data, update_date = load_json("receitas_BR", year)
    santa_catarina_data, _ = load_json("receitas_SC", year)

    labels_br, values_br, total_br = extractor.process_chart_data(
        brazil_data, "ORIGEM RECEITA", "VALOR REALIZADO"
    )
    labels_sc, values_sc, total_sc = extractor.process_chart_data(
        santa_catarina_data, "nmorigem", "vlreceitarealizadaliquida"
    )

    return jsonify({
        "ano": year,
        "data_atualizacao": update_date,
        "br": {
            "labels": labels_br, "values": values_br,
            "total_txt": extractor.format_compact_currency(total_br),
            "total": total_br, "tabela": brazil_data[:10]
        },
        "sc": {
            "labels": labels_sc, "values": values_sc,
            "total_txt": extractor.format_compact_currency(total_sc),
            "total": total_sc, "tabela": santa_catarina_data[:10]
        },
        "esfera": [total_br, total_sc]
    })


@app.route("/api/despesas")
def api_despesas():
    """Return expenses chart data for a given year as JSON."""
    year = resolve_year(request.args)

    brazil_data, update_date = load_json("despesas_BR", year)
    santa_catarina_data, _ = load_json("despesas_SC", year)

    brazil_aggregated = {}
    brazil_total = 0.0
    for item in brazil_data:
        fn = item.get("funcao", "Outros")
        value = extractor.parse_currency_value(item.get("pago", 0))
        brazil_aggregated[fn] = brazil_aggregated.get(fn, 0) + value
        brazil_total += value

    labels_br, values_br, table_br = extractor.process_rank_data(
        brazil_aggregated, limit=9
    )

    sc_aggregated = {}
    sc_total = 0.0
    for item in santa_catarina_data:
        fn = item.get("descricao", "Outros")
        value = extractor.parse_currency_value(item.get("vlpago", 0))
        sc_aggregated[fn] = sc_aggregated.get(fn, 0) + value
        sc_total += value

    labels_sc, values_sc, table_sc = extractor.process_rank_data(
        sc_aggregated, limit=9
    )

    return jsonify({
        "ano": year,
        "data_atualizacao": update_date,
        "br": {
            "labels": labels_br, "values": values_br,
            "total_txt": extractor.format_compact_currency(brazil_total),
            "total": brazil_total, "tabela": table_br
        },
        "sc": {
            "labels": labels_sc, "values": values_sc,
            "total_txt": extractor.format_compact_currency(sc_total),
            "total": sc_total, "tabela": table_sc
        },
        "esfera": [brazil_total, sc_total]
    })


@app.route("/api/investimentos")
def api_investimentos():
    """Return investments chart data for a given year as JSON."""
    year = resolve_year(request.args)

    brazil_data, update_date = load_json("investimentos_BR", year)
    santa_catarina_data, _ = load_json("investimentos_SC", year)

    def process(data_list):
        aggregated = {}
        total = 0.0
        for item in data_list:
            fn = item.get("nome_funcao", "Não informado")
            value = extractor.parse_currency_value(item.get("valor_realizado", 0))
            aggregated[fn] = aggregated.get(fn, 0) + value
            total += value

        sorted_items = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)
        labels = [k for k, _ in sorted_items[:9]]
        values = [v for _, v in sorted_items[:9]]

        if len(sorted_items) > 9:
            labels.append("Outros")
            values.append(sum(v for _, v in sorted_items[9:]))

        table = [{"nome": k, "valor": v} for k, v in sorted_items]
        return labels, values, total, table

    labels_br, values_br, total_br, table_br = process(brazil_data)
    labels_sc, values_sc, total_sc, table_sc = process(santa_catarina_data)

    return jsonify({
        "ano": year,
        "data_atualizacao": update_date,
        "br": {
            "labels": labels_br, "values": values_br,
            "total_txt": extractor.format_compact_currency(total_br),
            "total": total_br, "tabela": table_br
        },
        "sc": {
            "labels": labels_sc, "values": values_sc,
            "total_txt": extractor.format_compact_currency(total_sc),
            "total": total_sc, "tabela": table_sc
        },
        "esfera": [total_br, total_sc]
    })


# ==============================================================================
# API — HISTORICAL TOTALS (trend charts)
# ==============================================================================

@app.route("/api/historico/<tipo>")
def api_historico(tipo: str):
    """
    Return year-over-year totals for trend charts.

    Returns JSON: {"anos": [...], "br": [...], "sc": [...]}
    """
    configs = {
        "receitas":      ("receitas_BR",      "receitas_SC",      "VALOR REALIZADO",  "vlreceitarealizadaliquida"),
        "despesas":      ("despesas_BR",      "despesas_SC",      "pago",             "vlpago"),
        "investimentos": ("investimentos_BR",  "investimentos_SC",  "valor_realizado",  "valor_realizado"),
    }

    if tipo not in configs:
        return jsonify({"error": "Tipo inválido."}), 400

    prefix_br, prefix_sc, key_br, key_sc = configs[tipo]

    all_years = sorted(
        set(extractor.get_available_years(prefix_br))
        | set(extractor.get_available_years(prefix_sc))
    )

    totals_br, totals_sc = [], []

    for year in all_years:
        data_br, _ = load_json(prefix_br, year)
        totals_br.append(sum(
            extractor.parse_currency_value(item.get(key_br, 0)) for item in data_br
        ))

        data_sc, _ = load_json(prefix_sc, year)
        totals_sc.append(sum(
            extractor.parse_currency_value(item.get(key_sc, 0)) for item in data_sc
        ))

    return jsonify({"anos": all_years, "br": totals_br, "sc": totals_sc})


# ==============================================================================
# DASHBOARD PAGE ROUTES (SSR initial load)
# ==============================================================================

@app.route("/receitas")
def revenues():
    """Render revenues dashboard."""
    year = resolve_year(request.args)
    brazil_data, update_date = load_json("receitas_BR", year)
    santa_catarina_data, _ = load_json("receitas_SC", year)

    labels_br, values_br, total_br = extractor.process_chart_data(
        brazil_data, "ORIGEM RECEITA", "VALOR REALIZADO"
    )
    labels_sc, values_sc, total_sc = extractor.process_chart_data(
        santa_catarina_data, "nmorigem", "vlreceitarealizadaliquida"
    )

    anos_disponiveis = sorted(
        set(extractor.get_available_years("receitas_BR"))
        | set(extractor.get_available_years("receitas_SC")),
        reverse=True
    )

    return render_template(
        "receita.html",
        ano_selecionado=year,
        anos_disponiveis=anos_disponiveis,
        labels_br=labels_br, values_br=values_br,
        total_br_txt=extractor.format_compact_currency(total_br),
        labels_sc=labels_sc, values_sc=values_sc,
        total_sc_txt=extractor.format_compact_currency(total_sc),
        values_esfera=[total_br, total_sc],
        lista_dados_br=brazil_data[:10],
        lista_dados_sc=santa_catarina_data[:10],
        data_atualizacao=update_date
    )


@app.route("/despesas")
def expenses():
    """Render expenses dashboard."""
    year = resolve_year(request.args)
    brazil_data, update_date = load_json("despesas_BR", year)
    santa_catarina_data, _ = load_json("despesas_SC", year)

    brazil_aggregated = {}
    brazil_total = 0.0
    for item in brazil_data:
        fn = item.get("funcao", "Outros")
        value = extractor.parse_currency_value(item.get("pago", 0))
        brazil_aggregated[fn] = brazil_aggregated.get(fn, 0) + value
        brazil_total += value

    labels_br, values_br, brazil_table = extractor.process_rank_data(brazil_aggregated, limit=9)

    sc_aggregated = {}
    sc_total = 0.0
    for item in santa_catarina_data:
        fn = item.get("descricao", "Outros")
        value = extractor.parse_currency_value(item.get("vlpago", 0))
        sc_aggregated[fn] = sc_aggregated.get(fn, 0) + value
        sc_total += value

    labels_sc, values_sc, sc_table = extractor.process_rank_data(sc_aggregated, limit=9)

    anos_disponiveis = sorted(
        set(extractor.get_available_years("despesas_BR"))
        | set(extractor.get_available_years("despesas_SC")),
        reverse=True
    )

    return render_template(
        "despesa.html",
        ano_selecionado=year,
        anos_disponiveis=anos_disponiveis,
        labels_br=labels_br, values_br=values_br,
        total_br_txt=extractor.format_compact_currency(brazil_total),
        lista_dados_br=brazil_table,
        labels_sc=labels_sc, values_sc=values_sc,
        total_sc_txt=extractor.format_compact_currency(sc_total),
        lista_dados_sc=sc_table,
        values_esfera=[brazil_total, sc_total],
        data_atualizacao=update_date
    )


@app.route("/investimentos")
def investments():
    """Render investments dashboard."""
    year = resolve_year(request.args)
    brazil_data, update_date = load_json("investimentos_BR", year)
    santa_catarina_data, _ = load_json("investimentos_SC", year)

    def process(data_list):
        aggregated = {}
        total = 0.0
        for item in data_list:
            fn = item.get("nome_funcao", "Não informado")
            value = extractor.parse_currency_value(item.get("valor_realizado", 0))
            aggregated[fn] = aggregated.get(fn, 0) + value
            total += value
        sorted_items = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)
        labels = [k for k, _ in sorted_items[:9]]
        values = [v for _, v in sorted_items[:9]]
        if len(sorted_items) > 9:
            labels.append("Outros")
            values.append(sum(v for _, v in sorted_items[9:]))
        table = [{"nome": k, "valor": v} for k, v in sorted_items]
        return labels, values, total, table

    labels_br, values_br, total_br, table_br = process(brazil_data)
    labels_sc, values_sc, total_sc, table_sc = process(santa_catarina_data)

    anos_disponiveis = sorted(
        set(extractor.get_available_years("investimentos_BR"))
        | set(extractor.get_available_years("investimentos_SC")),
        reverse=True
    )

    return render_template(
        "invest.html",
        ano_selecionado=year,
        anos_disponiveis=anos_disponiveis,
        labels_br=labels_br, values_br=values_br,
        total_br_txt=extractor.format_compact_currency(total_br),
        lista_tabela_br=table_br,
        labels_sc=labels_sc, values_sc=values_sc,
        total_sc_txt=extractor.format_compact_currency(total_sc),
        lista_tabela_sc=table_sc,
        values_esfera=[total_br, total_sc],
        data_atualizacao=update_date
    )


# ==============================================================================
# PARALLEL ETL — CURRENT YEAR
# ==============================================================================

def run_parallel_extraction() -> None:
    """Execute all ETL processes simultaneously for the current year."""
    print(f"Starting ETL for year {extractor.CURRENT_YEAR}")
    start_time = time.time()

    threads = [
        threading.Thread(target=extractor.collect_revenues,
                         kwargs={"year": extractor.CURRENT_YEAR}),
        threading.Thread(target=extractor.collect_investments,
                         kwargs={"year": extractor.CURRENT_YEAR}),
        threading.Thread(target=extractor.collect_expenses_by_area,
                         kwargs={"year": extractor.CURRENT_YEAR}),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"ETL completed in {time.time() - start_time:.2f}s")


# ==============================================================================
# ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        run_parallel_extraction()

    app.run(debug=True)