# Transparece.io

> Projeto de Informatização do Fluxo Financeiro da Administração Pública: Receitas, Despesas e Investimentos.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-green)](https://flask.palletsprojects.com/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-purple)](https://getbootstrap.com/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

## Sobre o Projeto

O **Transparece.io** é uma aplicação web desenvolvida como Trabalho Final da disciplina **CIN7405 - Projeto de Informatização** da Universidade Federal de Santa Catarina (UFSC).

O objetivo principal é simplificar a navegação e o entendimento dos dados disponibilizados pelo [Portal da Transparência do Governo Federal](https://portaldatransparencia.gov.br/). Enquanto o portal oficial possui um vasto volume de dados, a complexidade de navegação pode afastar o cidadão comum. Este projeto propõe uma modelagem que integra o fluxo informacional entre:

1.  **Receitas:** Origem dos recursos arrecadados.
2.  **Despesas:** Onde o dinheiro foi gasto.
3.  **Investimentos:** Aplicação de Despesas em Investimentos (GND-4).

O sistema realiza um comparativo visual entre dados da esfera **Federal (Brasil)** e da esfera **Estadual (Santa Catarina)**.

## Funcionalidades

* **ETL Automatizado:** Scripts em Python (`extract.py`) que baixam, extraem e processam dados CSV diretamente das fontes oficiais e da API do Portal da Transparência.
* **Multithreading:** Coleta de dados simultânea para otimização do tempo de carregamento inicial.
* **Visualização de Dados:** Dashboards interativos utilizando **Chart.js** (Gráficos de Rosca e Pizza).
* **Comparativo Geográfico:** Alternância rápida entre visualização de dados Nacionais e Estaduais (SC).
* **Interface Responsiva:** Design moderno utilizando **Bootstrap 5**.

## Tecnologias Utilizadas

* **Back-end:** Python, Flask.
* **Processamento de Dados:** Pandas, Requests, Zipfile, JSON.
* **Front-end:** HTML5, CSS3, Bootstrap 5, Chart.js.
* **API:** Integração com a API de Dados do Portal da Transparência.
