# Extração de hardware em cinco fontes

Fontes disponíveis em `/sources`, na seleção de rotinas e no worker:

| ID | Loja | Identidade do produto |
| --- | --- | --- |
| `amazon_br` | Amazon Brasil | ASIN |
| `mercado_livre_br` | Mercado Livre | MLB de anúncio/catálogo |
| `kabum_br` | KaBuM! | código numérico de `/produto/` |
| `pichau_br` | Pichau | slug canônico; SKU do fabricante permanece nos dados do produto |
| `terabyte_br` | TerabyteShop | código numérico de `/produto/` |

Cada fonte usa o fluxo existente de descoberta, validação, refresh direto,
captura de HTML, imagens e observações. Os manifests ficam em
`workers/parsers/{loja}-product`. Nenhuma migration ou novo serviço é necessário.
Amazon e Mercado Livre continuam com as conexões autenticadas existentes.
As novas lojas usam captura por navegador quando `BROWSER_SERVICE_URL` e
`BROWSER_SERVICE_TOKEN` estão configurados; o serviço requer Chromium instalado.
Pichau e Terabyte usam modo com janela e sessão reutilizável por padrão, com
conexão manual e extensão disponíveis. Veja [conexões](browser-connections.md#pichau-e-terabyte).
Sem serviço de navegador, o worker usa HTTP. CAPTCHA e verificação de conta
interrompem a coleta e são diagnosticados; o coletor não resolve desafios.

## Comportamento conservador

- A identidade da URL final e do canonical deve corresponder ao produto pedido.
  Um redirecionamento de produto para categoria não vira uma observação válida.
- Dados estruturados são associados ao produto antes de usar uma oferta.
  Arrays de vendedores e `AggregateOffer` não fornecem um preço arbitrário.
- Na KaBuM!, os dados vêm de `pageProps.product`, conferindo seu ID.
  A busca aceita tanto objetos como JSON serializado de categorias redirecionadas.
- A Pichau usa o bloco do produto e a área principal da busca. Histórico de
  navegação e recomendações não fornecem candidatos nem preços ao produto atual.
- Os preços à vista, totais no cartão e valores de parcelas ficam separados.
  Totais calculados de parcelas são identificados como derivados; centavos de
  arredondamento não substituem o total explicitamente anunciado.
- Produtos indisponíveis preservam os preços observados e registram
  `availability=out_of_stock` naquela coleta. Na Pichau, kits com “a partir de”
  guardam o valor atual em `price`, o anterior riscado em `list_price` e a
  condição “a partir de” na opção de pagamento Pix.
  Campos sem evidência permanecem desconhecidos. Estoque em atualização na
  Pichau permanece desconhecido até confirmação.
- A validação de hardware aceita o modelo dentro do título da loja, preserva
  Ti/Super/XT e sufixos de CPU, e rejeita PCs completos/acessórios para consultas
  de componentes. NV2 e NV3, capacidades diferentes e Ryzen 5500/5600/5600X não
  são intercambiáveis. Buscas sem critérios de livro não usam `stripbooks`.
- URLs de páginas, redirects, paginação e imagens mantêm allowlists por fonte.
  Pichau e Terabyte reutilizam o contexto e o estado criptografado da fonte.
  Formulários de login e desafios não são enviados ao armazenamento de capturas.
  O contexto público da KaBuM! permanece temporário.

## Reproduzir os testes públicos

```sh
uv run --all-packages python -m panoptes_workers.probe --output artifacts/hardware-probe
```

Por padrão testa `rtx 3070`, `ssd kingston nv2 1tb`, `ssd kingston nv3 1tb`
e `ryzen 5 5600`. Usa no máximo um candidato aprovado por termo, mais um produto
de referência de cada nova loja. Há limitação de intervalo por fonte e timeout.
`--sites`, `--terms`, `--max-products`, `--interval` e `--timeout` ajustam a matriz.
O probe usa HTTP público, sem banco, LLM, credenciais ou alteração de rotinas.
Salva HTML, hash, status, URL final, duração, candidatos aprovados/rejeitados,
resultado de parsing e avisos em `report.json`. `parsed` significa que a página
foi reconhecida, não que todos os campos estejam disponíveis; confira `warnings`.
O processo termina após registrar as falhas, sem retentar desafios em loop.

Para enfileirar uma extração normal:

```sh
uv run --all-packages python -m panoptes_workers.cli discover "rtx 3070" --site kabum_br
```

Também é possível criar o termo por API com `site` e usar
`POST /search-terms/{id}/discover-sources` com `{"sites":"all"}` ou uma lista.

## Resultado observado em 18/10/2026, horário de São Paulo

A matriz final está em `artifacts/hardware-probe-20261018-validated/report.json`:

| Fonte | Requisições | Páginas interpretadas | Bloqueios |
| --- | ---: | ---: | ---: |
| Amazon | 8 | 8 | 0 |
| Mercado Livre | 4 | 0 | 4: verificação de conta, inclusive HTTP 200 |
| KaBuM! | 7 | 7 | 0 |
| Pichau | 5 | 0 | 5: HTTP 403/desafio |
| Terabyte | 5 | 0 | 5: HTTP 403/desafio |

Foram obtidos produtos de GPU, SSD e CPU. Na Amazon, um SSD NV2 não mostrou
preço e o Ryzen não confirmou estoque: esses campos ficaram desconhecidos.
Na KaBuM!, buscas redirecionadas retornaram também modelos diferentes, filtrados
antes de abrir os produtos. A RTX 3070 Asus esgotada tinha R$ 15.999,90 no JSON
residual: o preço foi suprimido. A busca da Pichau misturava histórico de GPU
na busca de SSD antes da delimitação da área principal; há regressão específica.

Separadamente, páginas públicas foram abertas no navegador interativo:
RTX 3070 e SSD na Pichau e na Terabyte, além de buscas de SSD. Seus blocos
sanitizados estão nas fixtures, com resultados esperados. O replay está em
`artifacts/hardware-probe-20261018-validated/rendered-replay.json`.
O teste posterior com Chromium real do backend recebeu desafios no modo sem
janela. Com janela, as duas lojas foram coletadas sem login nem CAPTCHA manual:
**oito páginas HTTP 200**, incluindo buscas, GPU, SSD e leitura depois de restaurar
o contexto criptografado. Relatório: `artifacts/backend-browser-final/report.json`.
Na Pichau: RTX 3070 por R$ 2.199,99 e SSD A400 480GB por R$ 569,99. Na Terabyte:
RTX 3070 indisponível (preço suprimido pela regra vigente naquele teste,
posteriormente removida) e SSD NV3 500GB por R$ 729,90.
O modo com janela é agora o padrão. Desafios futuros exigem interação manual.

Os testes offline exercitam também redirects para outro produto, canonical
divergente, moedas ausentes, ofertas agregadas, placeholders, CAPTCHA com status
200, atualização pendente, preço de recomendações, identidade de modelos e
fechamento/isolamento do contexto público. Não foi executada integração real
com PostgreSQL/MinIO nesta alteração.

Validação final: 574 testes passaram e 11 foram pulados pelos requisitos de
integração/ambiente; Ruff passou e o frontend apresentou zero erros e avisos
no `svelte-check`.
