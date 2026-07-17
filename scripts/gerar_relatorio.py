#!/usr/bin/env python3
#
# Relatório semanal de vendas por estado - VBC Grupo
# Envio: toda segunda 08h. Dados: acumulado do mes corrente ate a data do envio.
#
# Blocos do e-mail (topo, com visual):
#   1. Mapa coropletico por UF
#   2. Curva ABC de clientes (top 5 = quanto % do faturamento)
#   3. Concentracao regional (Sudeste x resto do Brasil)
#   4. Evolucao acumulada de vendas dia a dia no mes
#
# Blocos do e-mail (rodape, tabela compacta sem grafico):
#   5. Ticket medio por UF
#   6. Estados sem venda no mes
#
# Secrets esperados no repositorio:
#   OMIE_APP_KEY, OMIE_APP_SECRET, GMAIL_USER, GMAIL_APP_PASSWORD, DESTINATARIOS

import os
import smtplib
import requests
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime

OMIE_APP_KEY = os.environ["OMIE_APP_KEY"]
OMIE_APP_SECRET = os.environ["OMIE_APP_SECRET"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
DESTINATARIOS = [e.strip() for e in os.environ["DESTINATARIOS"].split(",")]

CFOPS_VENDA = {"5101", "5102", "6101", "6102", "7101", "7102"}
MALHA_IBGE_URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo+json&resolucao=2&qualidade=3"
)
CODIGOS_UF = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}
REGIAO_UF = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte", "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste", "PB": "Nordeste",
    "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste", "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}
TODAS_UFS = set(CODIGOS_UF.keys())


# ---------- 1. Coleta na Omie ----------
def buscar_nfe_mes():
    hoje = datetime.now()
    inicio = hoje.replace(day=1)

    notas = []
    pagina = 1
    while True:
        payload = {
            "call": "ListarNF",
            "app_key": OMIE_APP_KEY,
            "app_secret": OMIE_APP_SECRET,
            "param": [{
                "pagina": pagina,
                "registros_por_pagina": 50,
                "apenas_importado_api": "N",
                "dEmiInicial": inicio.strftime("%d/%m/%Y"),
                "dEmiFinal": hoje.strftime("%d/%m/%Y"),
            }],
        }
        r = requests.post("https://app.omie.com.br/api/v1/produtos/nfconsultar/", json=payload, timeout=30)
        if r.status_code != 200:
            print(f"Erro Omie ({r.status_code}): {r.text}")
        r.raise_for_status()
        data = r.json()
        lote = data.get("nfCadastro", [])
        notas.extend(lote)
        if pagina >= data.get("total_de_paginas", 1):
            break
        pagina += 1
    return notas


_cache_uf_cliente = {}


def buscar_uf_cliente(codigo_cliente_omie):
    """Consulta a UF do cliente via ConsultarCliente, com cache (o ListarNF não traz endereço)."""
    if not codigo_cliente_omie:
        return ""
    if codigo_cliente_omie in _cache_uf_cliente:
        return _cache_uf_cliente[codigo_cliente_omie]
    payload = {
        "call": "ConsultarCliente",
        "app_key": OMIE_APP_KEY,
        "app_secret": OMIE_APP_SECRET,
        "param": [{"codigo_cliente_omie": codigo_cliente_omie}],
    }
    try:
        r = requests.post("https://app.omie.com.br/api/v1/geral/clientes/", json=payload, timeout=30)
        r.raise_for_status()
        uf = r.json().get("estado", "")
    except Exception as e:
        print(f"DEBUG - falha ao consultar UF do cliente {codigo_cliente_omie}: {e}")
        uf = ""
    _cache_uf_cliente[codigo_cliente_omie] = uf
    return uf


def filtrar_notas(notas):
    """Retorna um DataFrame linha-a-linha: uf, cliente, valor, data. Base para todos os insights."""
    linhas = []
    for nf in notas:
        ide = nf.get("ide", {})
        if ide.get("dCan"):
            continue
        cfop = str(nf.get("det", [{}])[0].get("prod", {}).get("CFOP", "")).replace(".", "")
        if cfop not in CFOPS_VENDA:
            continue
        dest_int = nf.get("nfDestInt", {})
        codigo_cliente = dest_int.get("nCodCli")
        linhas.append({
            "uf": buscar_uf_cliente(codigo_cliente),
            "cliente": dest_int.get("cRazao", "Não identificado"),
            "valor": float(nf.get("total", {}).get("ICMSTot", {}).get("vNF", 0)),
            "data": pd.to_datetime(ide.get("dEmi", ""), format="%d/%m/%Y", errors="coerce"),
        })
    return pd.DataFrame(linhas)


# ---------- 2. Insights ----------
def agregar_por_uf(df):
    return df.groupby("uf", as_index=False)["valor"].sum().sort_values("valor", ascending=False)


def curva_abc(df, top_n=5):
    por_cliente = df.groupby("cliente", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
    total = por_cliente["valor"].sum()
    por_cliente["pct"] = por_cliente["valor"] / total * 100
    top = por_cliente.head(top_n)
    pct_top = top["valor"].sum() / total * 100
    return top, pct_top


def ticket_medio_por_uf(df):
    g = df.groupby("uf")["valor"].agg(["sum", "count"]).reset_index()
    g["ticket_medio"] = g["sum"] / g["count"]
    return g.sort_values("ticket_medio", ascending=False)


def estados_sem_venda(df_uf):
    vendidos = set(df_uf["uf"])
    return sorted(TODAS_UFS - vendidos)


def concentracao_regional(df_uf):
    df_r = df_uf.copy()
    df_r["regiao"] = df_r["uf"].map(REGIAO_UF)
    por_regiao = df_r.groupby("regiao")["valor"].sum().sort_values(ascending=False)
    total = por_regiao.sum()
    pct_sudeste = por_regiao.get("Sudeste", 0) / total * 100
    return por_regiao, pct_sudeste


def evolucao_acumulada(df):
    diario = df.groupby(df["data"].dt.date)["valor"].sum().sort_index()
    return diario.cumsum()


# ---------- 3. Gráficos (PNG para embutir no e-mail) ----------
_cache_uf_cliente = {}


def buscar_uf_cliente(codigo_cliente_omie):
    """Consulta a UF do cliente via ConsultarCliente, com cache (o ListarNF não traz endereço)."""
    if not codigo_cliente_omie:
        return ""
    if codigo_cliente_omie in _cache_uf_cliente:
        return _cache_uf_cliente[codigo_cliente_omie]
    payload = {
        "call": "ConsultarCliente",
        "app_key": OMIE_APP_KEY,
        "app_secret": OMIE_APP_SECRET,
        "param": [{"codigo_cliente_omie": codigo_cliente_omie}],
    }
    try:
        r = requests.post("https://app.omie.com.br/api/v1/geral/clientes/", json=payload, timeout=30)
        r.raise_for_status()
        uf = r.json().get("estado", "")
    except Exception as e:
        print(f"DEBUG - falha ao consultar UF do cliente {codigo_cliente_omie}: {e}")
        uf = ""
    _cache_uf_cliente[codigo_cliente_omie] = uf
    return uf


def gerar_mapa(df_uf, caminho="mapa_vendas.png"):
    r = requests.get(MALHA_IBGE_URL, timeout=60)
    r.raise_for_status()
    try:
        geojson_data = r.json()
    except ValueError as e:
        raise RuntimeError(
            f"IBGE nao retornou GeoJSON valido (content-type: {r.headers.get('content-type')}). "
            f"Primeiros 300 chars: {r.text[:300]}"
        ) from e
    malha = gpd.GeoDataFrame.from_features(geojson_data["features"])
    df_uf = df_uf.copy()
    df_uf["codarea"] = df_uf["uf"].map(CODIGOS_UF)
    malha = malha.merge(df_uf, on="codarea", how="left")
    malha["valor"] = malha["valor"].fillna(0)