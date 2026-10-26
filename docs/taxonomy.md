# Taxonomia de produtos

O agente `taxonomy_normalizer` classifica produtos canônicos, usando o mesmo
gateway auditado do OpenRouter e `google/gemini-2.5-flash-lite`. Recebe nome,
identidade, evidências de origem, taxonomia completa e política de crescimento.
Classificação e identidade são independentes: mudar uma categoria não mistura
capacidades ou gerações que o normalizador de produtos separou.

A migração 15 cria categorias iniciais Livros, Hardware, Eletrônicos,
Eletrodomésticos e Material escolar. Não há subcategorias predefinidas. O agente
pode criá-las quando houver uma lacuna real, priorizando reaproveitamento e nomes
estáveis em português. Cada produto aceita várias categorias e subcategorias;
escolher uma subcategoria também vincula sua categoria principal. Subcategorias
de pais diferentes podem ter o mesmo nome.

Metas iniciais: **20 categorias e 200 subcategorias**, configuráveis no painel
Administrador. Contagens incluem inativos, evitando contornar a estabilização
por desativação. Ao atingir a meta de um nível, novas criações exigem exceção
explícita, confiança mínima de 0,97 e justificativa específica de pelo menos
40 caracteres. Abaixo das metas, o prompt também prioriza encaixar nas existentes.
Desmarcar “Permitir criação pelo agente” impede toda criação automática, mas
preserva classificação nos nós existentes. Criação manual ignora as metas.

O painel **Administrador → Categorias e subcategorias dos produtos** permite:

- Criar, renomear, descrever e desativar categorias e subcategorias.
- Alterar metas ou suspender criações automáticas.
- Buscar produtos, selecionar múltiplos vínculos e salvar correções manuais.
- Reenviar um produto ao agente para liberar explicitamente a proteção manual.

IDs e vínculos permanecem estáveis ao renomear. O pai de um nó existente é
estável: para reorganizar, crie a subcategoria no destino e ajuste os vínculos.
Desativados permanecem no histórico, mas não são oferecidos para novas atribuições.
Essas classificações de produtos são independentes das categorias que configuram
critérios e sugestões de novas extrações.

A fila `catalog.taxonomy_task` recebe cada produto canônico novo; a migração
também enfileira os existentes. Produtos reutilizados não são reclassificados a
cada atualização de preço ou nova loja. Confiança abaixo de 0,9 e propostas
incompatíveis com as metas ficam `needs_review`, com a justificativa no painel.
Falhas são repetidas até cinco vezes com backoff. O worker valida IDs, parentesco,
estado ativo e evidências literais; revalida a taxonomia sob bloqueio antes de
gravar, evitando duplicatas entre workers concorrentes. Uma correção manual
invalida a reserva do agente, inclusive se ele já estiver inferindo. Reclassificação
explícita mantém os vínculos anteriores até a nova classificação ser aprovada.

Ativação: aplicar migrações e reiniciar backend (sincroniza o catálogo de agentes)
e worker contínuo com `OPENROUTER_API_KEY`. `TAXONOMY_NORMALIZER_ENABLED=false`
pausa a fila. Não há chamada paga no modo de extração `--once`. A auditoria
existente registra prompt, resposta, tokens e custo informado pelo provedor.

API autenticada: `GET /catalog/taxonomy` e
`GET /catalog/canonical-products/{id}/taxonomy`. Administração:
`POST /admin/taxonomy`, `PUT /admin/taxonomy/{id}`,
`PUT /admin/taxonomy/policy`, `GET /admin/taxonomy/products`,
`PUT /admin/taxonomy/products/{id}` e
`POST /admin/taxonomy/products/{id}/reclassify`.
