# Normalização de produtos entre marketplaces

O agente `product_normalizer` usa `google/gemini-2.5-flash-lite` via gateway
OpenRouter auditado. Interpreta título, descrição, marca/modelo, identificadores
e especificações. Seu resultado estruturado define a identidade de comparação:
categoria, marca, modelo e atributos materiais. O nome de exibição não é chave.
Uma identidade existente é reutilizada por hash desses campos; caso contrário,
cria-se um produto canônico. A comparação textual acontece apenas após a IA
normalizar semanticamente a identidade, nunca entre títulos brutos.

Kindle preto 16 GB e Kindle azul 16 GB, da mesma linha e geração, compartilham
o produto canônico. Kindle 32 GB, Paperwhite ou outra geração permanecem separados.
O prompt também preserva RAM, armazenamento, voltagem, tamanho, quantidade,
kits, condição e edição/idioma/formato de livros quando aplicável. Cor é ignorada.
O agente deve converter unidades e usar chaves estáveis de atributos. Como toda
extração por LLM, pode separar equivalentes caso produza grafias diferentes;
não há fusão aproximada que contorne diferenças nos atributos.

Cada atributo cita evidência literal da captura. Confiança abaixo de 0,9 ou
especificações essenciais ausentes deixam o anúncio `uncertain`, sem grupo.
Falhas têm até cinco tentativas com backoff. Reservas expiram após cinco minutos;
tokens de reserva impedem uma resposta antiga de sobrescrever uma nova captura.
O resultado e motivo ficam em `catalog.product_normalization`; tokens e custo
ficam na auditoria existente de `ai.interaction`.

A migração 13 enfileira anúncios já cadastrados usando a última observação.
Novas capturas enfileiram na mesma transação da persistência. Preços e imagens
não alteram o hash de entrada e não geram nova inferência. Mudanças de identidade
removem o vínculo anterior enquanto a nova evidência aguarda processamento.
As tabelas originais de variantes, anúncios e ofertas continuam como proveniência.

Para ativar, aplique as migrações, configure `OPENROUTER_API_KEY`, reinicie o
backend (sincroniza `agents/metadata.yaml`) e o worker contínuo. O modo `--once`
de extração não executa a fila de normalização. Sem chave, a fila aguarda.
`PRODUCT_NORMALIZER_ENABLED=false` pausa o processamento sem perder entradas.
Uma captura com novos dados reabre inclusive entradas incertas ou esgotadas.

API autenticada:

- `GET /catalog/canonical-products`: nomes, identidades, quantidade e marketplaces.
- `GET /catalog/canonical-products/{public_id}/listings`: anúncios do mesmo grupo,
  IDs de entidade para consultar ofertas e justificativas da normalização.
- `GET /analytics/prices/dashboard?canonical_product_id={public_id}` e
  `GET /analytics/detail?canonical_product_id={public_id}`: recortam a análise a
  todos os anúncios confirmados do grupo, sem limite de paginação nos IDs.
  Esse filtro pode ser combinado com período, marketplace e busca.

Não calcule médias por nome, termo de busca ou pelo produto legado: use o ID
canônico e mantenha moedas/condições comerciais separadas. Anúncios pendentes,
incertos e com falha não pertencem a um grupo de comparação.

Modelo e preços de referência: [OpenRouter Gemini 2.5 Flash Lite](https://openrouter.ai/google/gemini-2.5-flash-lite).
Na consulta de 19/10/2026, US$ 0,10 por milhão de tokens de entrada e US$ 0,40 de
saída. O custo real de cada chamada é registrado pelo gateway quando informado.
