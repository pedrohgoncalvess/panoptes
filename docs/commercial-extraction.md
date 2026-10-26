# Condições comerciais e histórico

Amazon Brasil e Mercado Livre usam primeiro os parsers do produto e um enriquecedor determinístico de blocos comerciais. Capturas do navegador local, do Docker e HTTP passam pelo mesmo enriquecedor, depois da validação da identidade do produto. Conteúdo ausente ou carregado apenas após interação continua desconhecido: nenhum modelo consegue recuperar informações que não apareceram na captura.

São conservados preço anunciado, preço anterior/lista, moeda, vendedor, condição, disponibilidade, estoque exato ou limite inferior, unidades por pacote, limites de compra, pagamentos, cupons, descontos, frete e texto do prazo de entrega. Características, identificadores, avaliações e imagens continuam no histórico do produto. Quantidade escolhida no seletor de compra não é tratada como estoque ou unidades por pacote.

Cada pagamento tem método, preço total, número e valor das parcelas, indicação de juros, condições e origem. O total calculado pelas parcelas tem `total_is_derived=true`; diferenças de arredondamento ou parcela final exigem conferir a condição anunciada. Cupons têm código, percentual/valor explícito, compra mínima, teto de desconto e necessidade de ativação. Cashback e benefícios sem valor claramente reconhecido permanecem como promoções com seu texto, sem reduzir o preço. Frete condicionado a assinatura ou compra mínima não vira frete zero incondicional. Datas relativas permanecem em `delivery_text`, sem inventar uma data absoluta.

## OpenRouter opcional

No `.env`, configure `OPENROUTER_API_KEY` e defina o modelo do agente `commerce` em `agents/metadata.yaml` (padrão `google/gemini-2.5-flash-lite`). `COMMERCE_LLM_ENABLED=false` desativa o fallback. Recrie backend e worker para sincronizar e aplicar a configuração:

```sh
docker compose up -d --build backend workers
```

O fallback faz no máximo uma chamada por produto, apenas se houver trechos comerciais não interpretados. Envia até 12.000 caracteres dos blocos selecionados, limita a resposta a 1.800 tokens, usa temperatura zero e `response_format=json_schema` estrito com `provider.require_parameters=true`. Não envia o HTML completo, cookies ou credenciais; trechos com CEP ou indicação explícita de endereço são excluídos. Pagamentos, promoções e fretes interpretados por IA ficam marcados com `extraction_method=openrouter`. O relatório conserva modelo, tokens, status, trechos não resolvidos e evidências.

As respostas passam por validação de contrato, referência ao fragmento e correspondência literal da evidência. Valores monetários e percentuais precisam aparecer no trecho. O modelo não substitui valores determinísticos conhecidos. Timeout, recusa do provedor ou resposta inválida preservam a extração anterior. Structured output garante estrutura, não a verdade semântica: resultados de IA precisam ser tratados como interpretações, mesmo com evidência.

## Banco e análise

`pricing.observation` preserva cada captura com a data original e vínculo a `scraping.observation` / `scraping.job` / `scraping.html_snapshot` no S3. `pricing.payment_option`, `pricing.promotion` e `pricing.shipping_quote` guardam valores em `NUMERIC(18,4)`; opções de frete adicionais ficam no JSONB tipado `shipping_options`. Evidências ficam em `commercial_extraction`. Produtos sem categoria reconhecida recebem uma identidade conservadora de categoria `other`, por site e anúncio, para também conservarem histórico de ofertas.

A view `pricing.payment_history` permite consultar séries por produto, variante, site, método, vendedor, moeda e destino. Inclui preço anunciado, total por pagamento, parcelas e preço por unidade quando o tamanho do pacote está explícito. Exemplo:

```sql
SELECT site, source_key, observed_at, method, total_price_vl,
       installment_qt, installment_price_vl, total_is_derived,
       currency, units_per_pack, unit_price_vl,
       destination_postal_code, shipping_price_vl, conditions
FROM pricing.payment_history
WHERE method = 'pix' AND currency = 'BRL'
ORDER BY observed_at DESC;
```

Compare somente produtos/variantes equivalentes, mesma moeda e contexto de frete e elegibilidade. Não some frete desconhecido como zero nem aplique cupons automaticamente. Anúncios sem identificador suficiente continuam separados entre sites.

`GET /products/{entity_id}/offers`, `GET /offers/{offer_id}/observations` e `GET /analytics/prices` incluem as condições. A tela **Analytics → Preços** mostra pagamentos, cupons, frete, quantidades e evidências na coleta atual e nas últimas 30 observações. A API paginada de observações permite consultar o restante do histórico.

Para preencher ofertas ausentes em coletas anteriores usando somente os HTMLs preservados, sem visitar lojas nem chamar IA:

```sh
docker compose exec workers python -m panoptes_workers.backfill_commerce --limit 100
```

O comando é idempotente: processa apenas observações ainda sem relatório comercial, complementa ofertas existentes e conserva os payloads originais, o preço anunciado e a data da captura. O relatório registra a versão do enriquecedor e as evidências utilizadas.
