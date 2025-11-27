from flask import Flask, render_template
from datetime import datetime
import extract as ex
import os, json,threading,time

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/apresentacao')
def apresente():
    return render_template('presentation.html')


@app.route('/receitas')
def receitas():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'collected_data')
    arquivo_br = os.path.join(data_dir, 'receitas_BR_2025.json')
    arquivo_sc = os.path.join(data_dir, 'receitas_SC_2025.json')

    dados_br = []
    dados_sc = []
    data_atualizacao = "Data desconhecida"

    # BR
    try:
        with open(arquivo_br, 'r', encoding='utf-8') as f:
            dados_br = json.load(f)
        timestamp = os.path.getmtime(arquivo_br)
        data_obj = datetime.fromtimestamp(timestamp)
        data_atualizacao = data_obj.strftime('%d/%m/%Y às %H:%M')
    except FileNotFoundError:
        pass

    # SC
    try:
        with open(arquivo_sc, 'r', encoding='utf-8') as f:
            dados_sc = json.load(f)
    except FileNotFoundError:
        pass

    labels_br, values_br, total_br = ex.processar_dados_grafico(dados_br, "ORIGEM RECEITA", "VALOR REALIZADO")
    labels_sc, values_sc, total_sc = ex.processar_dados_grafico(dados_sc, "nmorigem", "vlreceitarealizadaliquida")

    values_esfera = [total_br, total_sc]

    return render_template(
        'receita.html',
        labels_br=labels_br,
        values_br=values_br,
        total_br_txt=ex.formatar_moeda_abreviada(total_br),

        labels_sc=labels_sc,
        values_sc=values_sc,
        total_sc_txt=ex.formatar_moeda_abreviada(total_sc),

        values_esfera=values_esfera,
        # Alterado aqui: enviamos as duas listas separadamente
        lista_dados_br=dados_br,
        lista_dados_sc=dados_sc,
        data_atualizacao=data_atualizacao
    )


@app.route('/despesas')
def despesas():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'collected_data')
    arquivo_br = os.path.join(data_dir, 'despesas_BR_2025.json')
    arquivo_sc = os.path.join(data_dir, 'despesas_SC_2025.json')

    dados_br = []
    dados_sc = []
    data_atualizacao = "Data desconhecida"

    # BR
    try:
        with open(arquivo_br, 'r', encoding='utf-8') as f:
            dados_br = json.load(f)
        timestamp = os.path.getmtime(arquivo_br)
        data_atualizacao = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y às %H:%M')
    except FileNotFoundError:
        pass

    # SC
    try:
        with open(arquivo_sc, 'r', encoding='utf-8') as f:
            dados_sc = json.load(f)
    except FileNotFoundError:
        pass

    # =========================================================================
    # 1. PROCESSAMENTO BRASIL (Agregação + Limpeza)
    # =========================================================================
    agregado_br = {}
    total_br = 0.0

    for item in dados_br:
        funcao = item.get('funcao', 'Outros')
        valor_str = item.get('pago', '0,00')

        try:
            if isinstance(valor_str, str):
                valor_float = float(valor_str.replace('.', '').replace(',', '.'))
            else:
                valor_float = float(valor_str)
        except ValueError:
            valor_float = 0.0

        # Soma
        if funcao in agregado_br:
            agregado_br[funcao] += valor_float
        else:
            agregado_br[funcao] = valor_float

        total_br += valor_float

    # rankeamento
    labels_br, values_br, lista_tabela_br = ex.processar_rank(agregado_br, limite=9)

    # =========================================================================
    # 2. PROCESSAMENTO SANTA CATARINA (Agregação + Limpeza)
    # =========================================================================
    agregado_sc = {}
    total_sc = 0.0

    for item in dados_sc:
        funcao = item.get('nmfuncao', 'Outros')
        valor = item.get('vlpago', 0.0)

        if isinstance(valor, str):
            valor = float(valor.replace(',', '.'))

        if funcao in agregado_sc:
            agregado_sc[funcao] += valor
        else:
            agregado_sc[funcao] = valor

        total_sc += valor

    labels_sc, values_sc, lista_tabela_sc = ex.processar_rank(agregado_sc, limite=9)

    values_esfera = [total_br, total_sc]

    return render_template(
        'despesa.html',
        # Brasil
        labels_br=labels_br,
        values_br=values_br,
        total_br_txt=ex.formatar_moeda_abreviada(total_br),
        lista_dados_br=lista_tabela_br,

        # Santa Catarina
        labels_sc=labels_sc,
        values_sc=values_sc,
        total_sc_txt=ex.formatar_moeda_abreviada(total_sc),
        lista_dados_sc=lista_tabela_sc,

        values_esfera=values_esfera,
        data_atualizacao=data_atualizacao
    )


@app.route('/investimentos')
def invest():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'collected_data')
    arquivo_br = os.path.join(data_dir, 'investimentos_BR_2025.json')
    arquivo_sc = os.path.join(data_dir, 'investimentos_SC_2025.json')

    dados_br = []
    dados_sc = []
    data_atualizacao = "Data desconhecida"

    #Brasil
    try:
        with open(arquivo_br, 'r', encoding='utf-8') as f:
            dados_br = json.load(f)
        timestamp = os.path.getmtime(arquivo_br)
        data_atualizacao = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y às %H:%M')
    except FileNotFoundError:
        pass

    #santa Catarina
    try:
        with open(arquivo_sc, 'r', encoding='utf-8') as f:
            dados_sc = json.load(f)
    except FileNotFoundError:
        pass

    def processar_investimentos(lista_dados):
        agregado = {}
        total_geral = 0.0

        for item in lista_dados:
            nome = item.get('nome_funcao', 'Não informado')
            valor = item.get('valor_realizado', 0.0)

            if isinstance(valor, str):
                try:
                    valor = float(valor.replace('.', '').replace(',', '.'))  # Adaptação comum BR
                except ValueError:
                    valor = 0.0

            agregado[nome] = agregado.get(nome, 0.0) + valor
            total_geral += valor

        sorted_items = sorted(agregado.items(), key=lambda x: x[1], reverse=True)

        top_limit = 9 #itens antes de 'outros'
        labels = []
        values = []
        tabela_completa = []

        for k, v in sorted_items:
            tabela_completa.append({'nome': k, 'valor': v})

        outros_val = 0.0
        for i, (k, v) in enumerate(sorted_items):
            if i < top_limit:
                labels.append(k)
                values.append(v)
            else:
                outros_val += v

        if outros_val > 0:
            labels.append("Outras Funções")
            values.append(outros_val)

        return labels, values, total_geral, tabela_completa

    # Processamento
    labels_br, values_br, total_br, lista_tabela_br = processar_investimentos(dados_br)
    labels_sc, values_sc, total_sc, lista_tabela_sc = processar_investimentos(dados_sc)

    values_esfera = [total_br, total_sc]

    return render_template(
        'invest.html',
        # Brasil
        labels_br=labels_br,
        values_br=values_br,
        total_br_txt=ex.formatar_moeda_abreviada(total_br),
        lista_tabela_br=lista_tabela_br,

        # Santa Catarina
        labels_sc=labels_sc,
        values_sc=values_sc,
        total_sc_txt=ex.formatar_moeda_abreviada(total_sc),
        lista_tabela_sc=lista_tabela_sc,

        values_esfera=values_esfera,
        data_atualizacao=data_atualizacao
    )

@app.route('/sobre-nos')
def sobre():
    return render_template('about.html')

def coletar_dados_simultaneos(): #MULTI THREADING DAS FUNÇõES DE COLETA
    start = time.time()

    t1 = threading.Thread(target=ex.coletar_investimentos)
    t2 = threading.Thread(target=ex.coletar_receitas)
    t3 = threading.Thread(target=ex.coletar_despesas_por_areas_BR)

    t1.start()
    t2.start()
    t3.start()
    t1.join()
    t2.join()
    t3.join()

    end = time.time()
    print(f"--- [FIM] Todas as coletas finalizaram em {end - start:.2f} segundos ---")

if __name__ == '__main__':
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        coletar_dados_simultaneos()
        pass

    app.run(debug=True)