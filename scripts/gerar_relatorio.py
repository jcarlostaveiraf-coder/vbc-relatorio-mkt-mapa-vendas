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
    "?intrarregiao=UF&formato=application/vnd.geo+json&qualidade=intermediaria"
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
                "dDataEmissaoDe": inicio.strftime("%d/%m/%Y"),
                "dDataEmissaoAte": hoje.strftime("%d/%m/%Y"),
            }],
        }
        r = requests.post("https://app.omie.com.br/api/v1/produtos/nfe/", json=payload, timeout=30)
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


def filtrar_notas(notas):
    """Retorna um DataFrame linha-a-linha: uf, cliente, valor, data. Base para todos os insights."""
    linhas = []
    for nf in notas:
        compl = nf.get("compl", {})
        if compl.get("dCan"):
            continue
        cfop = str(nf.get("det", [{}])[0].get("prod", {}).get("cfop", ""))
        if cfop not in CFOPS_VENDA:
            continue
        dest = nf.get("dest", {})
        ide = nf.get("ide", {})
        linhas.append({
            "uf": dest.get("UF", ""),
            "cliente": dest.get("xNome", "Não identificado"),
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
def gerar_mapa(df_uf, caminho="mapa_vendas.png"):
    malha = gpd.read_file(MALHA_IBGE_URL)
    df_uf = df_uf.copy()
    df_uf["codarea"] = df_uf["uf"].map(CODIGOS_UF)
    malha = malha.merge(df_uf, on="codarea", how="left")
    malha["valor"] = malha["valor"].fillna(0)

    fig, ax = plt.subplots(figsize=(7, 7))
    malha.plot(column="valor", cmap="Blues", linewidth=0.6, edgecolor="white",
               legend=True, ax=ax, missing_kwds={"color": "#f1f5f9"})
    ax.set_axis_off()
    ax.set_title("Vendas por estado - acumulado do mês", fontsize=13, loc="left")
    plt.savefig(caminho, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return caminho


def gerar_grafico_abc(top, caminho="curva_abc.png"):
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.barh(top["cliente"], top["valor"], color="#0c447c")
    ax.invert_yaxis()
    ax.set_title("Top 5 clientes do mês", fontsize=12, loc="left")
    ax.set_xlabel("R$")
    plt.tight_layout()
    plt.savefig(caminho, dpi=150)
    plt.close(fig)
    return caminho


def gerar_grafico_regional(por_regiao, caminho="regional.png"):
    fig, ax = plt.subplots(figsize=(6, 2.2))
    cores = ["#0c447c" if r == "Sudeste" else "#b0c6db" for r in por_regiao.index]
    ax.barh(por_regiao.index, por_regiao.values, color=cores)
    ax.set_title("Faturamento por região", fontsize=12, loc="left")
    ax.set_xlabel("R$")
    plt.tight_layout()
    plt.savefig(caminho, dpi=150)
    plt.close(fig)
    return caminho


def gerar_grafico_evolucao(cumsum, caminho="evolucao.png"):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(cumsum.index, cumsum.values, color="#0c447c", linewidth=2)
    ax.fill_between(cumsum.index, cumsum.values, color="#0c447c", alpha=0.08)
    ax.set_title("Faturamento acumulado no mês", fontsize=12, loc="left")
    ax.set_ylabel("R$ acumulado")
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(caminho, dpi=150)
    plt.close(fig)
    return caminho


# ---------- 4. E-mail ----------
def montar_html(total, periodo_str, ticket_uf, sem_venda, pct_top5, pct_sudeste):
    linhas_ticket = "".join(
        f"<tr><td style='padding:4px 12px;'>{r.uf}</td>"
        f"<td style='padding:4px 12px;text-align:right;'>R$ {r.ticket_medio:,.2f}</td>"
        f"<td style='padding:4px 12px;text-align:right;color:#888;'>{int(r.count)} notas</td></tr>"
        for r in ticket_uf.itertuples()
    )
    sem_venda_str = ", ".join(sem_venda) if sem_venda else "nenhum — todos os estados com histórico compraram este mês"

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#111;max-width:600px;">
      <h2>Relatório semanal de vendas por estado</h2>
      <p style="color:#555;">Período: {periodo_str}</p>
      <p><b>Total faturado:</b> R$ {total:,.2f}</p>

      <img src="cid:mapa_vendas" style="max-width:480px;display:block;margin:16px 0;" />

      <img src="cid:curva_abc" style="max-width:480px;display:block;margin:16px 0;" />
      <p style="font-size:13px;color:#555;">Os 5 maiores clientes respondem por {pct_top5:.1f}% do faturamento do mês.</p>

      <img src="cid:regional" style="max-width:480px;display:block;margin:16px 0;" />
      <p style="font-size:13px;color:#555;">Sudeste concentra {pct_sudeste:.1f}% do faturamento do mês.</p>

      <img src="cid:evolucao" style="max-width:480px;display:block;margin:16px 0;" />

      <hr style="border:none;border-top:1px solid #eee;margin:24px 0;" />

      <p style="font-size:13px;font-weight:bold;">Ticket médio por UF</p>
      <table style="border-collapse:collapse;font-size:13px;">
        <tr><th style="text-align:left;padding:4px 12px;">UF</th><th style="text-align:right;padding:4px 12px;">Ticket médio</th><th></th></tr>
        {linhas_ticket}
      </table>

      <p style="font-size:13px;font-weight:bold;margin-top:16px;">Estados sem venda este mês</p>
      <p style="font-size:13px;color:#555;">{sem_venda_str}</p>
    </body></html>
    """


def enviar_email(html, imagens):
    # imagens: dict {content_id: caminho_arquivo}
    msg = MIMEMultipart("related")
    msg["Subject"] = f"Relatório semanal de vendas por estado - {datetime.now().strftime('%d/%m/%Y')}"
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(DESTINATARIOS)
    msg.attach(MIMEText(html, "html"))

    for cid, caminho in imagens.items():
        with open(caminho, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-ID", f"<{cid}>")
            msg.attach(img)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, DESTINATARIOS, msg.as_string())


# ---------- Main ----------
if __name__ == "__main__":
    hoje = datetime.now()
    inicio = hoje.replace(day=1)
    periodo_str = f"{inicio.strftime('%d/%m/%Y')} a {hoje.strftime('%d/%m/%Y')} (acumulado do mês)"

    notas = buscar_nfe_mes()
    df = filtrar_notas(notas)

    if df.empty:
        print("Nenhuma venda encontrada no mês. E-mail não enviado.")
    else:
        df_uf = agregar_por_uf(df)
        total = df_uf["valor"].sum()

        top5, pct_top5 = curva_abc(df)
        ticket_uf = ticket_medio_por_uf(df)
        sem_venda = estados_sem_venda(df_uf)
        por_regiao, pct_sudeste = concentracao_regional(df_uf)
        cumsum = evolucao_acumulada(df)

        imagens = {
            "mapa_vendas": gerar_mapa(df_uf),
            "curva_abc": gerar_grafico_abc(top5),
            "regional": gerar_grafico_regional(por_regiao),
            "evolucao": gerar_grafico_evolucao(cumsum),
        }

        html = montar_html(total, periodo_str, ticket_uf, sem_venda, pct_top5, pct_sudeste)
        enviar_email(html, imagens)
        print("Relatório enviado com sucesso.")
