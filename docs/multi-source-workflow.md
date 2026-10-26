# Extração em múltiplas fontes — contrato v1.2

Amazon Brasil (`amazon_br`), Mercado Livre (`mercado_livre_br`), KaBuM! (`kabum_br`),
Pichau (`pichau_br`) e TerabyteShop (`terabyte_br`) usam o mesmo
fluxo de captura, validação, persistência e acompanhamento. O registro em
`panoptes_contracts.sources.SOURCES` define nomes, identificadores nativos,
parsers e hosts permitidos; `panoptes_workers.sources.ADAPTERS` associa as
implementações. Novas lojas devem adicionar definição, adapter, manifest e
fixtures, sem criar outro fluxo de persistência.

Veja [extração de hardware](hardware-extraction.md) para detalhes dos novos
adapters, limitações de transporte e resultados das requisições reais.

## Seleção e compatibilidade

`GET /sources` lista as fontes disponíveis. O frontend permite selecionar uma
fonte ou todas ao iniciar uma extração e ao repetir uma descoberta.

`POST /search-terms/{uuid}/discover-sources` recebe o contrato `SourceSelection`:

```json
{"contract_version": "1.2", "sites": ["mercado_livre_br"]}
```

`{"sites":"all"}` seleciona todas as fontes registradas. A resposta 202 contém
`requests`, cada uma com UUID da execução, status, `site` e `search_term_id`.
Os mesmos termos, critérios, limites e intervalo são copiados para cada fonte.
Termos existentes são reutilizados; configurações incompatíveis retornam 409.
Execuções ativas são deduplicadas. O lote usa uma transação e correlation ID
comuns, mas cada fonte tem execução e diagnóstico próprios.

O endpoint antigo `/discover` continua executando a fonte do termo. Refresh usa
a fonte do produto original. `/scrape-requests` inclui `site` na resposta;
registros sem origem recuperável podem retornar null.

Os contratos de candidatos e tracking validam chave nativa e domínio por fonte.
Payloads antigos sem `site` preservam o padrão Amazon. `ScrapeRequest` aceita
versões 1.1 e 1.2. A seleção de fontes é uma extensão 1.2; os contratos de
entidade, oferta, catálogo e captura continuam compatíveis.

## Mercado Livre

O parser `mercado-livre-product/1.0.1` descobre anúncios públicos, remove parâmetros
de rastreamento e identifica chaves MLB. Valida título e critérios antes da
visita e confirma a identidade na página do produto. JSON-LD referente a outros
produtos e preços agregados de busca não são usados como oferta individual.

O tratamento inclui catálogo, ISBN/autores quando presentes, vendedor, condição,
preço/moeda, disponibilidade, estoque explícito, frete, parcelamento, cupons,
avaliações e imagens. Campos ausentes ficam null; condições de frete/cupom não
são convertidas em desconto garantido. ISBN/GTIN permitem relacionar fontes ao
mesmo catálogo, enquanto anúncios, ofertas e histórico preservam sua origem.

HTMLs e imagens ficam no storage e seus metadados no PostgreSQL. Jobs registram
parser, versão, rotina, captura e evidência. Os hosts de páginas e imagens são
restritos por fonte, incluindo redirecionamentos.

## Diagnóstico

`source_page_fetched` registra fonte, URL, HTTP status, tentativa e referências
da captura. Respostas transitórias 500/502/503/504 recebem tentativas limitadas;
falhas por página podem produzir resultado parcial. CAPTCHA, autenticação,
verificação de conta e respostas de bloqueio produzem `blocked`, com motivo e
captura arquivados. Uma página de verificação HTTP 200 não é sucesso de extração.
O executor HTTP não resolve desafios nem autentica no marketplace.
