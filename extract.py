import requests, os, json, zipfile, io, time
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime
#--------configs
load_dotenv()
API_KEY = os.getenv('KEY_PORTAL_DA_TRANSPARENCIA')

if API_KEY:
    HEADERS = {'chave-api-dados': API_KEY}
else:
    print("!!! ERRO: SEM CHAVE API NO .ENV !!!")

pasta_dados_coletados = 'collected_data'

ANO_CSV = datetime.today().year
DATA_INI = f'01/01/{ANO_CSV}'
DATA_FIM = datetime.today().strftime("%d/%m/%Y")

if not os.path.exists(pasta_dados_coletados):
    os.makedirs(pasta_dados_coletados)

#--------local utils

def salvar_json(nome_arquivo, dados):
    caminho = os.path.join(pasta_dados_coletados, f"{nome_arquivo}.json")
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)
    print(f"   [V] JSON Salvo: {caminho}")


def requisitar_api(endpoint, params):
    base_url = "https://api.portaldatransparencia.gov.br/api-de-dados"
    url = f"{base_url}{endpoint}"

    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        #print(f"   > URL FINAL GERADA: {r.url}")
        # ----------------------

        if r.status_code == 200:
            return r.json()
        else:
            print(f"   [X] ERRO {r.status_code}: {r.text[:200]}...")
            return []
    except Exception as e:
        print(f"   [X] ERRO CONEXÃO: {e}")
        return []

#==============================================================================
# 1. RECEITAS via processamento de CSV hospedado
#==============================================================================
def coletar_receitas():
    print(f"\n--- 1. PROCESSANDO RECEITAS BRASIL (CSV {ANO_CSV}) ---")
    url = f"https://portaldatransparencia.gov.br/download-de-dados/receitas/{ANO_CSV}" #URL de download do CSV BRASIL
    try:
        print("   > Baixando ZIP...")
        r = requests.get(url, stream=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nome_csv = [n for n in z.namelist() if n.endswith('.csv')][0]
        with z.open(nome_csv) as f:
            header = f.readline().decode('latin-1').strip().upper().split(';')
            cols_limpas = [c.replace('"', '') for c in header]

        print("   > Lendo dados...")
        with z.open(nome_csv) as f:
            df = pd.read_csv(f, sep=';', encoding='latin-1', decimal=',')
            #print(df.columns)
            #colunas desejadas
            cols = ['CATEGORIA ECONÔMICA', 'ORIGEM RECEITA', 'VALOR REALIZADO']
            df = df[cols]

            #Agrupar e Somar
            df_agrupado = df.groupby(['CATEGORIA ECONÔMICA', 'ORIGEM RECEITA'])['VALOR REALIZADO'].sum().reset_index()

            #Converter o DataFrame para lista de dicionário
            dados_dict = df_agrupado.to_dict(orient='records')
            salvar_json(f"receitas_BR_{ANO_CSV}", dados_dict)
    except Exception as e:
        print(f"   [!] Erro Receitas BR: {e}")

    print(f"\n--- 2. PROCESSANDO RECEITAS SC (CSV {ANO_CSV}) ---")
    url_SC = os.getenv("URL_RECEITAS_SC")

    try:
        print("   > Baixando CSV...")
        r = requests.get(url_SC, stream=True)
        df = pd.read_csv(io.BytesIO(r.content), sep=';', encoding='latin-1', decimal=',')
        #colunas desejadas
        cols = ['nmcategoria', 'nmorigem', 'vlreceitarealizadaliquida']
        df = df[cols]
        #agrupar por Categoria e Origem, somando o Valor
        df_agrupado = df.groupby(['nmcategoria', 'nmorigem'])['vlreceitarealizadaliquida'].sum().reset_index()

        df_agrupado = df_agrupado.sort_values(by='vlreceitarealizadaliquida', ascending=False) #ordenando
        #converter para dicionários
        dados_sc = df_agrupado.to_dict(orient='records')
        #salvar
        salvar_json(f"receitas_SC_{ANO_CSV}", dados_sc)

    except Exception as e:
        print(f"   [!] Erro Receitas SC: {e}")

#==============================================================================
# 2. DESPESAS via API
#==============================================================================
def coletar_despesas_por_areas_BR():
    print(f"\n--- 3. PROCESSANDO DESPESAS-BR POR ÁREAS de Atuação ({ANO_CSV}) ---")
    url_invest = f'https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/{ANO_CSV}'

    try:
        print("   > Baixando ZIP...")
        r = requests.get(url_invest, stream=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nome_csv = [n for n in z.namelist() if n.endswith('.csv')][0]

        with z.open(nome_csv) as f:
            header = f.readline().decode('latin-1').strip().upper().split(';')

        print("   > Lendo dados...")
        with z.open(nome_csv) as f:
            df = pd.read_csv(f, sep=';', encoding='latin-1', decimal=',')
            cols_interesse = ['CÓDIGO FUNÇÃO', 'NOME FUNÇÃO', 'ORÇAMENTO REALIZADO (R$)']

            if not all(col in df.columns for col in cols_interesse):
                print("   [!] Erro: Colunas esperadas não encontradas no CSV.")
                print(f"       Colunas disponíveis: {df.columns.tolist()}")
                return

            df = df[cols_interesse]

            #AGRUPAR por Função
            df_agrupado = df.groupby(['CÓDIGO FUNÇÃO', 'NOME FUNÇÃO'])['ORÇAMENTO REALIZADO (R$)'].sum().reset_index()

            #RENOMEAR para o padrão do seu sistema
            df_agrupado.columns = ['codigoFuncao', 'funcao', 'pago_float']

            #do maior para o menor valor
            df_agrupado = df_agrupado.sort_values(by='pago_float', ascending=False)

            dados_saida = []
            for _, row in df_agrupado.iterrows():
                dados_saida.append({
                    "funcao": row['funcao'],
                    "codigoFuncao": str(row['codigoFuncao']),
                    "pago": (row['pago_float']),
                })

            print(f"   > Total de Funções Agrupadas: {len(dados_saida)}")

            salvar_json(f"despesas_BR_{ANO_CSV}", dados_saida)

    except Exception as e:
        print(f"   [!] Erro Despesas BR: {e}")

    # --- PROCESSO 4: MICRO Despesas ---
    print(f"\n--- 4. PROCESSANDO DESPESAS-SC POR ÁREAS de Atuação ({ANO_CSV}) ---")
    url_sc = os.getenv("URL_DESPESAS_SC")

    try:
        print("   > Baixando CSV...")
        r = requests.get(url_sc, stream=True)
        df = pd.read_csv(io.BytesIO(r.content), sep=';', encoding='latin-1', decimal=',')
        #colunas desejadas
        cols = ['nmfuncao', 'cdfuncao', 'vlpago']
        df = df[cols]
        #agrupar por Categoria e Origem, somando o Valor
        df_agrupado = df.groupby(['nmfuncao', 'cdfuncao'])['vlpago'].sum().reset_index()

        df_agrupado = df_agrupado.sort_values(by='vlpago', ascending=False)  # ordenando
        #converter para dicionários
        dados_sc = df_agrupado.to_dict(orient='records')
        #salvar
        salvar_json(f"despesas_SC_{ANO_CSV}", dados_sc)

    except Exception as e:
        print(f"   [!] Erro Despesas SC: {e}")

# ==============================================================================
# 3. INVESTIMENTOS via API
# ==============================================================================
def coletar_investimentos():
    print(f"\n--- 5. PROCESSANDO INVESTIMENTOS NACIONAIS ---")
    # PROCESSO 5: MACRO
    url_invest = f'https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/{ANO_CSV}'

    try:
        print("   > Baixando ZIP...")
        r = requests.get(url_invest, stream=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nome_csv = [n for n in z.namelist() if n.endswith('.csv')][0]

        with z.open(nome_csv) as f:
            header = f.readline().decode('latin-1').strip().upper().split(';')

        print("   > Lendo dados...")
        with z.open(nome_csv) as f:
            df = pd.read_csv(f, sep=';', encoding='latin-1', decimal=',')
            cols = ['CÓDIGO FUNÇÃO', 'NOME FUNÇÃO', 'CÓDIGO GRUPO DE DESPESA', 'ORÇAMENTO REALIZADO (R$)']
            df = df[cols]

            df_investimentos = df[df['CÓDIGO GRUPO DE DESPESA'] == 4].copy()

            df_agrupado = df_investimentos.groupby(['CÓDIGO FUNÇÃO', 'NOME FUNÇÃO'])[
                'ORÇAMENTO REALIZADO (R$)'].sum().reset_index()

            df_agrupado.columns = ['codigo_funcao', 'nome_funcao', 'valor_realizado']

            df_agrupado = df_agrupado.sort_values(by='valor_realizado', ascending=False)

            dados_dict = df_agrupado.to_dict(orient='records')

            print(f"   > Funções agrupadas: {len(dados_dict)}")

            salvar_json(f"investimentos_BR_{ANO_CSV}", dados_dict)

    except Exception as e:
        print(f"   [!] Erro Investimentos BR: {e}")

    # PROCESSO 6: MICRO SC
    print(f"\n--- 6. PROCESSANDO Investimentos-SC POR ÁREAS de Atuação ({ANO_CSV}) ---")
    url_sc = os.getenv("URL_INVESTI_SC")

    try:
        print("   > Baixando CSV...")
        r = requests.get(url_sc, stream=True)
        df = pd.read_csv(io.BytesIO(r.content), sep=';', encoding='latin-1', decimal=',')

        cols = ['nmfuncao', 'cdfuncao', 'vlpago', 'cdgruponaturezadespesa']
        df = df[cols]

        df_investimentos = df[df['cdgruponaturezadespesa'] == 44].copy()
        df_agrupado = df_investimentos.groupby(['cdfuncao', 'nmfuncao'])['vlpago'].sum().reset_index()
        df_agrupado.columns = ['codigo_funcao', 'nome_funcao', 'valor_realizado']

        df_agrupado = df_agrupado.sort_values(by='valor_realizado', ascending=False)
        dados_dict = df_agrupado.to_dict(orient='records')

        print(f"   > Funções agrupadas SC: {len(dados_dict)}")

        salvar_json(f"investimentos_SC_{ANO_CSV}", dados_dict)

    except Exception as e:
        print(f"   [!] Erro Investimentos SC: {e}")

# ==============================================================================
# 4. Outras Funcionalidades
# ==============================================================================

# Função auxiliar para formatar valores grandes
def formatar_moeda_abreviada(valor):
    if valor >= 1_000_000_000_000:
        return f"R$ {valor / 1_000_000_000_000:.2f} Tri"
    elif valor >= 1_000_000_000:
        return f"R$ {valor / 1_000_000_000:.2f} Bi"
    elif valor >= 1_000_000:
        return f"R$ {valor / 1_000_000:.2f} Mi"
    return f"R$ {valor:,.2f}"


# Função genérica para processar dados do gráfico
def processar_dados_grafico(dados, chave_nome, chave_valor):
    lista_temp = []
    total_absoluto = 0

    for item in dados:
        nome = item.get(chave_nome, "N/A")
        valor = item.get(chave_valor, 0)
        lista_temp.append({'nome': nome, 'valor': valor})
        total_absoluto += valor

    lista_temp.sort(key=lambda x: x['valor'], reverse=True)
    top_7 = lista_temp[:7]
    resto = lista_temp[7:]

    if resto:
        soma_outros = sum(item['valor'] for item in resto)
        top_7.append({'nome': 'Outros', 'valor': soma_outros})

    labels = [item['nome'] for item in top_7]
    values = [item['valor'] for item in top_7]

    return labels, values, total_absoluto


# FUNÇÃO AUXILIAR PARA APLICAR RANKEAMENTOs
def processar_rank(dicionario_agregado, limite=8):

    itens_ordenados = sorted(dicionario_agregado.items(), key=lambda x: x[1], reverse=True)

    top_itens = itens_ordenados[:limite]
    resto_itens = itens_ordenados[limite:]

    if resto_itens:
        soma_outros = sum(valor for nome, valor in resto_itens)
        top_itens.append(('Outros', soma_outros))

    labels = [k for k, v in top_itens]
    values = [v for k, v in top_itens]

    lista_tabela = []
    for k, v in top_itens:
        lista_tabela.append({
            'funcao': k,
            'valor': v,
            'valor_formatado': f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        })

    return labels, values, lista_tabela