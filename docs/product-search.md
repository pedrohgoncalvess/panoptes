# Pesquisa de produtos

Os filtros de produto de Preços, Detail e Analytics de extrações aceitam pesquisa
por nome, categoria e descrição. A pesquisa combina correspondência textual e
similaridade semântica, preservando os filtros de termo e origem e o produto
selecionado. Até 100 resultados são apresentados por relevância.

O backend gera embeddings pelo OpenRouter com o agente `product_embedding`,
definido em `agents/metadata.yaml`. Configure `OPENROUTER_API_KEY` no backend.
O modelo padrão é `openai/text-embedding-3-small` com 1536 dimensões. Prompts,
modelos e parâmetros são sincronizados com `ai.agent` na inicialização.

O backend indexa produtos existentes e verifica alterações a cada 30 segundos.
Um hash evita recalcular documentos sem mudanças. A versão do índice inclui
modelo, dimensões e versão do agente; altere a versão ao mudar a configuração.
Documentos longos são divididos em trechos de até 1800 caracteres, enviados em
batches de até 64 e agregados em um vetor médio normalizado. Nomes, categorias,
marca e descrição são enviados; cookies e informações de autenticação não entram
nos documentos. Cada batch e consulta tem interação auditada e JSON enviado
assincronamente ao S3. Falhas de indexação geram nova tentativa em 30 segundos.

A migração `20261018_11_ai_runtime` permite dimensões variáveis em pgvector.
O índice HNSW de dimensão fixa é removido; a busca usa comparação exata com filtro
por versão, evitando mistura de espaços vetoriais. Catálogos grandes podem exigir
índices parciais por modelo/dimensões após medir o desempenho.

`GET /analytics/prices/products?q=...` aceita os filtros `term_id`, `site` e
`selected`. O último preserva a opção selecionada mesmo que não corresponda à
nova pesquisa; ele não permite ultrapassar o escopo dos outros filtros.
Sem `q`, a API mantém a listagem completa anterior. Com `q`, correspondências
textuais têm prioridade e as demais precisam ter similaridade de pelo menos
0,25; essa medida é um ranking, não uma probabilidade de acerto.
