# Relatório semanal de vendas por estado — VBC Grupo

Envia, toda segunda-feira às 08h (horário de Brasília), um e-mail para os
gestores com a análise de vendas do mês corrente até a data do envio.

## O que o e-mail traz

**Blocos visuais:**
- Mapa coroplético de faturamento por UF
- Curva ABC: top 5 clientes e % que representam do faturamento do mês
- Concentração regional: Sudeste x demais regiões
- Evolução acumulada do faturamento, dia a dia, no mês

**Tabela compacta (rodapé, sem gráfico):**
- Ticket médio por UF
- Estados sem venda no mês

## Como funciona

1. `scripts/gerar_relatorio.py` consulta a Omie (`ListarNF` no módulo
   `produtos/nfconsultar/`) e traz as notas emitidas desde o dia 1º do mês
2. Filtra canceladas e mantém só CFOPs de venda: `5101, 5102, 6101, 6102, 7101, 7102`
3. Gera 4 imagens (mapa + 3 gráficos) via geopandas/matplotlib
4. Monta o e-mail em HTML com as imagens embutidas (`Content-ID`)
5. Envia via Gmail SMTP

O workflow que orquestra tudo isso é `.github/workflows/relatorio-semanal.yml`,
agendado por cron e também disparável manualmente pela aba **Actions → Run workflow**.

## Secrets necessários

Cadastrados em **Settings → Secrets and variables → Actions**:

| Secret | Descrição |
|---|---|
| `OMIE_APP_KEY` | Chave de app da Omie (mesma do bot diário de NF-e) |
| `OMIE_APP_SECRET` | Segredo de app da Omie |
| `GMAIL_USER` | E-mail remetente |
| `GMAIL_APP_PASSWORD` | App Password do Gmail (não é a senha normal da conta) |
| `DESTINATARIOS` | Lista de e-mails separados por vírgula. **Nunca colocar e-mails direto no código** — o repositório é público |

## Rodar manualmente (fora do cron)

Aba **Actions** → selecionar o workflow → **Run workflow**.

## Histórico de problemas já resolvidos

Ver `HANDOFF.md` para o registro completo dos erros já enfrentados e corrigidos
(endpoint errado da Omie, corrupção de aspas no copiar/colar, nome de método
incorreto). Útil caso um erro parecido volte a aparecer.
