import io, json, logging, os, re, zipfile, requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# ==============================================================================
# ENVIRONMENT CONFIGURATION
# ==============================================================================

load_dotenv()


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

COLLECTED_DATA_FOLDER = "database"

CURRENT_YEAR = datetime.today().year

os.makedirs(COLLECTED_DATA_FOLDER, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ==============================================================================
# URL BUILDER FOR SANTA CATARINA
# ==============================================================================

def build_sc_url(base_url: str, year: int) -> str:
    """
    Replace the year tokens in Santa Catarina API URLs.

    The SC portal uses query params like:
        anomesinifiltro[]=202601  (January of the year)
        anomesfimfiltro[]=202612  (December of the year)

    This function finds any 4-digit year embedded in those 6-digit
    tokens and replaces them with the requested year.

    Args:
        base_url (str): Original URL from .env.
        year (int): Target year.

    Returns:
        str: URL with the correct year tokens.
    """
    if not base_url:
        return None

    def replace_year_in_token(match):
        token = match.group(0)          # e.g. "202601"
        month = token[4:]               # e.g. "01"
        return f"{year}{month}"

    # Match any 6-digit sequence that looks like YYYYmm (month 01-12)
    return re.sub(r"\d{4}(0[1-9]|1[0-2])", replace_year_in_token, base_url)


# ==============================================================================
# VALIDATION AND UTILITY FUNCTIONS
# ==============================================================================

def validate_dataframe(
    dataframe: pd.DataFrame,
    expected_columns: list,
    context: str
) -> bool:
    """
    Validate DataFrame structure and required columns.

    Args:
        dataframe (pd.DataFrame): DataFrame to validate.
        expected_columns (list): Required columns.
        context (str): Validation context.

    Returns:
        bool: Validation result.
    """
    if dataframe is None or dataframe.empty:
        logging.error("[%s] Empty dataset received.", context)
        return False

    missing_columns = [
        column for column in expected_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        logging.error(
            "[%s] Missing columns: %s",
            context,
            missing_columns
        )
        logging.error(
            "[%s] Available columns: %s",
            context,
            list(dataframe.columns)
        )
        return False

    logging.info(
        "[%s] %s rows successfully validated.",
        context,
        len(dataframe)
    )

    return True


def save_json_file(file_name: str, data: list) -> None:
    """
    Save processed data into a JSON file.

    Args:
        file_name (str): Output filename (without .json).
        data (list): Data to save.
    """
    file_path = os.path.join(
        COLLECTED_DATA_FOLDER,
        f"{file_name}.json"
    )

    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(
            data,
            json_file,
            ensure_ascii=False,
            indent=4
        )

    logging.info("JSON saved: %s", file_path)


def extract_csv_from_zip(response_content: bytes) -> pd.DataFrame:
    """
    Extract the first CSV file from ZIP content.

    Args:
        response_content (bytes): ZIP binary content.

    Returns:
        pd.DataFrame: Extracted DataFrame.
    """
    zip_file = zipfile.ZipFile(io.BytesIO(response_content))

    csv_name = [
        file_name for file_name in zip_file.namelist()
        if file_name.endswith(".csv")
    ][0]

    with zip_file.open(csv_name) as csv_file:
        dataframe = pd.read_csv(
            csv_file,
            sep=";",
            encoding="latin-1",
            decimal=","
        )
    return dataframe


def load_csv_from_url(url: str) -> pd.DataFrame:
    """
    Load CSV directly from URL.

    Args:
        url (str): CSV file URL.

    Returns:
        pd.DataFrame: Loaded DataFrame.
    """
    response = requests.get(
        url,
        stream=True,
        timeout=120
    )

    response.raise_for_status()

    return pd.read_csv(
        io.BytesIO(response.content),
        sep=";",
        encoding="latin-1",
        decimal=","
    )


def parse_currency_value(value) -> float:
    """
    Parse Brazilian currency values into float.

    Args:
        value: Currency value (str or numeric).

    Returns:
        float: Parsed value.
    """
    try:
        if isinstance(value, str):
            return float(
                value.replace(".", "").replace(",", ".")
            )
        return float(value)
    except Exception:
        return 0.0


# ==============================================================================
# REVENUE EXTRACTION
# ==============================================================================

def collect_revenues(year: int = None) -> None:
    """
    Collect and process revenue datasets for a given year.

    Args:
        year (int): Target year. Defaults to current year.
    """
    if year is None:
        year = CURRENT_YEAR

    # --------------------------------------------------------------------------
    # BRAZIL
    # --------------------------------------------------------------------------

    logging.info("Processing Brazilian revenues (%s)", year)

    brazil_url = (
        f"https://portaldatransparencia.gov.br/"
        f"download-de-dados/receitas/{year}"
    )

    try:
        response = requests.get(
            brazil_url,
            headers=HEADERS,
            stream=True,
            timeout=120
        )
        response.raise_for_status()

        dataframe = extract_csv_from_zip(response.content)

        selected_columns = [
            "CATEGORIA ECONÔMICA",
            "ORIGEM RECEITA",
            "VALOR REALIZADO"
        ]

        if validate_dataframe(dataframe, selected_columns, "Brazil Revenues"):
            grouped_dataframe = (
                dataframe[selected_columns]
                .groupby(["CATEGORIA ECONÔMICA", "ORIGEM RECEITA"])
                ["VALOR REALIZADO"]
                .sum()
                .reset_index()
            )

            save_json_file(
                f"receitas_BR_{year}",
                grouped_dataframe.to_dict(orient="records")
            )

    except Exception as error:
        logging.exception(
            "Brazil revenues extraction failed (%s): %s", year, error
        )

    # --------------------------------------------------------------------------
    # SANTA CATARINA
    # --------------------------------------------------------------------------

    logging.info("Processing Santa Catarina revenues (%s)", year)

    santa_catarina_url = build_sc_url(
        os.getenv("URL_RECEITAS_SC"), year
    )

    try:
        dataframe = load_csv_from_url(santa_catarina_url)

        selected_columns = [
            "nmcategoria",
            "nmorigem",
            "vlreceitarealizadaliquida"
        ]

        if validate_dataframe(
            dataframe, selected_columns, "Santa Catarina Revenues"
        ):
            grouped_dataframe = (
                dataframe[selected_columns]
                .groupby(["nmcategoria", "nmorigem"])
                ["vlreceitarealizadaliquida"]
                .sum()
                .reset_index()
            )

            grouped_dataframe = grouped_dataframe.sort_values(
                by="vlreceitarealizadaliquida", ascending=False
            )

            save_json_file(
                f"receitas_SC_{year}",
                grouped_dataframe.to_dict(orient="records")
            )

    except Exception as error:
        logging.exception(
            "Santa Catarina revenues extraction failed (%s): %s", year, error
        )


# ==============================================================================
# EXPENSE EXTRACTION
# ==============================================================================

def collect_expenses_by_area(year: int = None) -> None:
    """
    Collect and process expense datasets for a given year.

    Args:
        year (int): Target year. Defaults to current year.
    """
    if year is None:
        year = CURRENT_YEAR

    # --------------------------------------------------------------------------
    # BRAZIL
    # --------------------------------------------------------------------------

    logging.info("Processing Brazilian expenses (%s)", year)

    brazil_url = (
        f"https://portaldatransparencia.gov.br/"
        f"download-de-dados/orcamento-despesa/{year}"
    )

    try:
        response = requests.get(
            brazil_url,
            headers=HEADERS,
            stream=True,
            timeout=120
        )
        response.raise_for_status()

        dataframe = extract_csv_from_zip(response.content)

        selected_columns = [
            "CÓDIGO FUNÇÃO",
            "NOME FUNÇÃO",
            "ORÇAMENTO REALIZADO (R$)"
        ]

        if validate_dataframe(dataframe, selected_columns, "Brazil Expenses"):
            grouped_dataframe = (
                dataframe[selected_columns]
                .groupby(["CÓDIGO FUNÇÃO", "NOME FUNÇÃO"])
                ["ORÇAMENTO REALIZADO (R$)"]
                .sum()
                .reset_index()
            )

            grouped_dataframe.columns = [
                "functionCode",
                "functionName",
                "paidAmount"
            ]

            output_data = [
                {
                    "funcao": row["functionName"],
                    "codigoFuncao": str(row["functionCode"]),
                    "pago": row["paidAmount"]
                }
                for _, row in grouped_dataframe.iterrows()
            ]

            save_json_file(f"despesas_BR_{year}", output_data)

    except Exception as error:
        logging.exception(
            "Brazil expenses extraction failed (%s): %s", year, error
        )

    # --------------------------------------------------------------------------
    # SANTA CATARINA
    # --------------------------------------------------------------------------

    logging.info("Processing Santa Catarina expenses (%s)", year)

    santa_catarina_url = build_sc_url(
        os.getenv("URL_DESPESAS_SC"), year
    )

    try:
        dataframe = load_csv_from_url(santa_catarina_url)

        selected_columns = ["descricao", "codigo", "vlpago"]

        if validate_dataframe(
            dataframe, selected_columns, "Santa Catarina Expenses"
        ):
            grouped_dataframe = (
                dataframe[selected_columns]
                .groupby(["descricao", "codigo"])
                ["vlpago"]
                .sum()
                .reset_index()
            )

            grouped_dataframe = grouped_dataframe.sort_values(
                by="vlpago", ascending=False
            )

            save_json_file(
                f"despesas_SC_{year}",
                grouped_dataframe.to_dict(orient="records")
            )

    except Exception as error:
        logging.exception(
            "Santa Catarina expenses extraction failed (%s): %s", year, error
        )


# ==============================================================================
# INVESTMENT EXTRACTION
# ==============================================================================

def collect_investments(year: int = None) -> None:
    """
    Collect and process investment datasets for a given year.

    Args:
        year (int): Target year. Defaults to current year.
    """
    if year is None:
        year = CURRENT_YEAR

    # --------------------------------------------------------------------------
    # BRAZIL
    # --------------------------------------------------------------------------

    logging.info("Processing Brazilian investments (%s)", year)

    brazil_url = (
        f"https://portaldatransparencia.gov.br/"
        f"download-de-dados/orcamento-despesa/{year}"
    )

    try:
        response = requests.get(
            brazil_url,
            headers=HEADERS,
            stream=True,
            timeout=120
        )
        response.raise_for_status()

        dataframe = extract_csv_from_zip(response.content)
        selected_columns = [
            "CÓDIGO FUNÇÃO",
            "NOME FUNÇÃO",
            "CÓDIGO GRUPO DE DESPESA",
            "ORÇAMENTO REALIZADO (R$)"
        ]

        if validate_dataframe(
            dataframe, selected_columns, "Brazil Investments"
        ):
            # Força a conversão para numérico. O que não for número vira NaN.
            coluna_numerica = pd.to_numeric(dataframe["CÓDIGO GRUPO DE DESPESA"], errors='coerce')

            # Filtra pelo número 4 (podem ser floats ou ints, então usamos igualdade matemática)
            investment_dataframe = dataframe[coluna_numerica == 4].copy()

            grouped_dataframe = (
                investment_dataframe
                .groupby(["CÓDIGO FUNÇÃO", "NOME FUNÇÃO"])
                ["ORÇAMENTO REALIZADO (R$)"]
                .sum()
                .reset_index()
            )

            grouped_dataframe.columns = [
                "codigo_funcao",
                "nome_funcao",
                "valor_realizado"
            ]
            save_json_file(
                f"investimentos_BR_{year}",
                grouped_dataframe.to_dict(orient="records")
            )

    except Exception as error:
        logging.exception(
            "Brazil investments extraction failed (%s): %s", year, error
        )

    # --------------------------------------------------------------------------
    # SANTA CATARINA
    # --------------------------------------------------------------------------

    logging.info("Processing Santa Catarina investments (%s)", year)

    santa_catarina_url = build_sc_url(
        os.getenv("URL_INVESTI_SC"), year
    )

    try:
        dataframe = load_csv_from_url(santa_catarina_url)

        selected_columns = [
            "nmfuncao",
            "cdfuncao",
            "vlpago",
            "cdgruponaturezadespesa"
        ]

        if validate_dataframe(
            dataframe, selected_columns, "Santa Catarina Investments"
        ):
            investment_dataframe = dataframe[
                dataframe["cdgruponaturezadespesa"] == 44
            ].copy()

            grouped_dataframe = (
                investment_dataframe
                .groupby(["cdfuncao", "nmfuncao"])
                ["vlpago"]
                .sum()
                .reset_index()
            )

            grouped_dataframe.columns = [
                "codigo_funcao",
                "nome_funcao",
                "valor_realizado"
            ]

            save_json_file(
                f"investimentos_SC_{year}",
                grouped_dataframe.to_dict(orient="records")
            )

    except Exception as error:
        logging.exception(
            "Santa Catarina investments extraction failed (%s): %s",
            year,
            error
        )


# ==============================================================================
# CHART UTILITIES
# ==============================================================================

def format_compact_currency(value: float) -> str:
    """
    Format large monetary values into compact Brazilian notation.

    Args:
        value (float): Numeric value.

    Returns:
        str: Formatted string (e.g. "R$ 1,23 Tri").
    """
    if value >= 1_000_000_000_000:
        return f"R$ {value / 1_000_000_000_000:.2f} Tri"
    if value >= 1_000_000_000:
        return f"R$ {value / 1_000_000_000:.2f} Bi"
    if value >= 1_000_000:
        return f"R$ {value / 1_000_000:.2f} Mi"
    return f"R$ {value:,.2f}"


def process_chart_data(
    data: list,
    name_key: str,
    value_key: str
):
    """
    Process and rank chart data, grouping the tail into "Outros".

    Args:
        data (list): Raw dataset.
        name_key (str): Label field name.
        value_key (str): Value field name.

    Returns:
        tuple: (labels list, values list, total float)
    """
    processed_data = []
    total_amount = 0

    for item in data:
        name = item.get(name_key, "N/A")
        value = parse_currency_value(item.get(value_key, 0))
        processed_data.append({"name": name, "value": value})
        total_amount += value

    processed_data.sort(key=lambda item: item["value"], reverse=True)

    top_items = processed_data[:7]
    remaining_items = processed_data[7:]

    if remaining_items:
        other_sum = sum(item["value"] for item in remaining_items)
        top_items.append({"name": "Outros", "value": other_sum})

    labels = [item["name"] for item in top_items]
    values = [item["value"] for item in top_items]

    return labels, values, total_amount


def process_rank_data(
    aggregated_dictionary: dict,
    limit: int = 8
):
    """
    Process ranking tables and chart data from an aggregated dict.

    Args:
        aggregated_dictionary (dict): {name: value} mapping.
        limit (int): Number of top items before grouping into "Outros".

    Returns:
        tuple: (labels list, values list, table list of dicts)
    """
    sorted_items = sorted(
        aggregated_dictionary.items(),
        key=lambda item: item[1],
        reverse=True
    )

    top_items = sorted_items[:limit]

    if len(sorted_items) > limit:
        other_sum = sum(value for _, value in sorted_items[limit:])
        top_items.append(("Outros", other_sum))

    labels = [key for key, _ in top_items]
    values = [value for _, value in top_items]

    table_data = [
        {
            "funcao": key,
            "valor": value,
            "valor_formatado": (
                f"R$ {value:,.2f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
        }
        for key, value in top_items
    ]

    return labels, values, table_data


# ==============================================================================
# AVAILABLE YEARS UTILITY
# ==============================================================================

def get_available_years(prefix: str) -> list[int]:
    """
    Scan collected_data/ and return sorted years for a given prefix.

    Example: prefix="receitas_BR" returns [2022, 2023, 2024, 2025]

    Args:
        prefix (str): File prefix to search for.

    Returns:
        list[int]: Sorted list of available years (ascending).
    """
    years = []

    if not os.path.exists(COLLECTED_DATA_FOLDER):
        return years

    for file_name in os.listdir(COLLECTED_DATA_FOLDER):
        if file_name.startswith(prefix) and file_name.endswith(".json"):
            # Extract year from pattern like "receitas_BR_2023.json"
            parts = file_name.replace(".json", "").split("_")
            candidate = parts[-1]
            if candidate.isdigit() and len(candidate) == 4:
                years.append(int(candidate))

    return sorted(years)