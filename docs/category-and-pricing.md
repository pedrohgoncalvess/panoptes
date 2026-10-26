# Categorias, produtos e ofertas

`POST /search-terms` aceita `criteria.match_mode: category` para descobrir varios
modelos, ou `exact_product` para titulo/autor/ISBN. O modo exato continua sendo
o default dos cadastros antigos. Envie [o exemplo de TV de 50 polegadas](examples/tv-50-polegadas.json)
ao cadastro autenticado e depois `POST /search-terms/{public_id}/discover`.

```sh
python -m panoptes_workers.cli discover "tv 50 polegadas" --category television --attributes '{"screen_size_inches":50}' --pages 5 --max-candidates 100
```

O exemplo aceita LG, Samsung e outras marcas, mantendo modelos distintos.
`brands: ["Samsung", "LG"]` restringe fabricantes. Atributos ausentes na busca
nao impedem visitar o detalhe. No detalhe, atributo obrigatorio desconhecido
gera `uncertain`; incompatibilidade gera `rejected`. Acessorios identificados
sao excluidos por padrao. A categoria precisa de evidencia no produto, nao e
inferida apenas do termo digitado.

| Categoria | Atributos normalizados |
| --- | --- |
| television | screen_size_inches, resolution, panel_technology, product_line, refresh_rate_hz, smart, voltage, color |
| refrigerator | capacity_liters, voltage, color, frost_free, door_count |
| book | isbn, edition, format, language, page_count |
| school_supplies | item_type, units_per_pack, material, color, volume_ml, sheet_count |

Chaves, tipos e unidades sao validados por categoria. Dimensoes Decimal aparecem
como strings JSON, como `"50"`; filtros aceitam numero ou string decimal.
Resolucao usa `3840x2160`; voltagem usa `220v`/`bivolt`. Dados nao reconhecidos
permanecem em specifications e no HTML. Novas categorias precisam de contrato,
normalizador, migration de catalogo e fixtures.

## Persistencia

| Tabela | Responsabilidade |
| --- | --- |
| catalog.product | Categoria, marca, modelo e identidade do produto |
| catalog.variant | Configuracao e identificadores da variante |
| catalog.listing | Anuncio da loja, URL e vinculo com o ASIN existente |
| pricing.offer | Oferta por anuncio, vendedor, expedidor e condicao |
| pricing.observation | Precos, moeda, estoque e instante da captura |
| pricing.promotion | Cupom/desconto, codigo, requisitos, validade e ativacao |
| pricing.payment_option | Pix, cartao, parcelamento e condicoes |
| pricing.shipping_quote | Frete observado, CEP e requisitos |

Valores monetarios usam NUMERIC(18,4) e Decimal, expostos como strings JSON.
Cada coleta cria uma observacao sem sobrescrever a anterior; cupons, pagamentos
e frete pertencem a essa observacao. Lista vazia nao reaproveita cupom antigo.
O horario financeiro vem da captura HTML. Preco anunciado, anterior, Pix e
parcela ficam separados. Total parcelado e preco apos cupom nao sao calculados;
texto e requisitos sao preservados. Null significa desconhecido, inclusive
validade e elegibilidade. Esta etapa nao consulta CEPs nem aplica cupons.

Marca/modelo confirmados podem compartilhar produto. Variantes com ISBN/GTIN
explicitos podem compartilhar identidade; sem eles, ficam separadas por loja/ASIN
para evitar unir voltagens/tamanhos/embalagens incertos. Titulo semelhante e
embeddings nao fazem uniao. Contradicoes de marca/modelo ou atributos de um
anuncio conhecido geram falha de identidade e preservam o historico anterior.

scraping.entity continua sendo o UUID de anuncio usado nos endpoints existentes.
As tabelas novas usam UUIDs proprios. Observacoes antigas em JSON sao preservadas;
a migration nao reconstrui valores antigos. Novas tabelas sao preenchidas na
proxima descoberta/atualizacao. JSON original, assets e referencias financeiras
sao gravados na mesma transacao.

## Consultas autenticadas

- `GET /search-terms/{uuid}/products`: resultados com catalog_product_id,
  variant_id, categoria, marca, modelo, atributos e ultima observacao.
- `GET /catalog/products?category=television&brand=Samsung`: produtos e variantes.
- `GET /catalog/products/{uuid}/listings`: anuncios e listing_entity_id para tracking.
- `GET /products/{listing_entity_id}/offers`: ultima observacao por oferta,
  com pagamentos, cupons e frete.
- `GET /offers/{uuid}/observations`: historico financeiro da oferta.
- `GET /products/{listing_entity_id}/observations`: historico completo de capturas.

Listas aceitam limit/offset. is_current indica a oferta vista na captura mais
recente do anuncio; ofertas antigas permanecem consultaveis, sem afirmar
disponibilidade atual.

## Cobertura e validacao

Amazon busca fora do departamento de livros para categorias gerais. Percorre
ate max_pages (1 a 20) e max_candidates (1 a 1000); candidatos distintos incluem
rejeitados. A cobertura depende dos resultados e limites, sem limitar uma marca
a um modelo. As rotinas existentes funcionam com categorias e refresh direto.

amazon-product/1.0.0 extrai a oferta principal visivel. O modelo suporta varias
ofertas, mas o executor ainda nao navega em todos os vendedores. Ha fixtures
sinteticas de TV, geladeira e material escolar em workers/parsers/amazon-product;
elas nao representam precos reais. Regressoes do livro continuam em amazon-book.
Browser e LLM continuam desligados.

Migration 20261004_06_catalog_pricing tem rollback. Testes offline cobrem busca
multimarcas, atributos, precos condicionados, persistencia decimal e API autenticada.
Integracao PostgreSQL e opt-in; Docker nao esta disponivel neste ambiente.


## Composicao de preco e analytics comerciais

Ofertas, historico, detalhes de analytics e consultas de precos retornam
`price_composition`. `advertised_price` e o valor coletado; `price_without_coupon`
so e preenchido com evidencia explicita. `list_price` continua sendo referencia
riscada e nao e convertido em preco sem cupom. A inclusao de cupom no preco e
triestado (`price_includes_coupon`: true, false ou null).

Cada `coupon_scenarios` avalia um unico cupom, sem acumular descontos, Pix ou
cashback. `savings`, `price_with_coupon` e `total_with_shipping` sao simulacoes
condicionais. Com inclusao desconhecida, o preco anunciado pode ser usado como
base hipotetica, identificada em `assumptions`; a base confirmada continua null.
Cupom ja incluido sem base explicita, dados ambiguos, expiracao ou compra minima
impedem o calculo. Frete desconhecido ou varias opcoes sem selecao nao viram zero.
Totais com frete usam somente a cotacao e o destino capturados, sem validar checkout.

Os novos campos de evidencia sao persistidos no payload original da captura;
nao exigem migracao e capturas antigas preservam valores desconhecidos. Novas
coletas identificam valores explicitamente marcados como "sem cupom" e "com cupom"
nos blocos comerciais; nao inferem essa relacao de um preco riscado.

`price_dashboard.commerce` agrega cupons, cobertura de frete e precos anunciados
por loja/moeda sobre a ultima observacao de cada oferta dentro do periodo.
`coupon_terms` lista codigos, valores/percentuais, minimo, teto, ativacao, validade
e numero de ofertas com cada condicao. Expiracao e avaliada no momento da consulta.
Medias com/sem cupons comparam grupos de ofertas, nao economia realizada. Frete
medio considera a cotacao principal com valor conhecido, incluindo zero; valores
sujeitos ao endereco continuam condicionais. Todos os filtros do dashboard se aplicam.
