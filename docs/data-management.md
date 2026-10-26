# Dados de extração

A aba `/data` apresenta resultados em tabelas, sem gráficos ou indicadores.
Cada linha representa um produto em uma fonte/página, com busca textual,
filtro por fonte, filtro por execução e paginação. O seletor oferece as últimas
100 execuções; o link **Dados** em **Extrações** também permite abrir execuções
mais antigas. Ao filtrar uma execução, preço e data são os daquela execução.
**Ver dados** abre o histórico completo da página e uma tabela dos campos de cada
coleta, incluindo os dados comerciais estruturados.

A grade usa linhas compactas, colunas com divisórias, cabeçalho fixo e miniaturas.
Textos extensos são abreviados na célula e podem ser lidos ao passar o mouse;
os dados completos continuam disponíveis no histórico.

O filtro de preço em reais aceita **maior que**, **igual a**, **menor que** e
**entre** (limites inclusivos). Ele considera o preço anunciado da última coleta
da página, ou da execução escolhida, e não aplica cupons nem condições de pagamento.
Páginas sem preço não entram em filtros de preço; outras moedas não são misturadas.

Há uma checkbox em cada linha e uma no cabeçalho para marcar/desmarcar todos.
**Marcar todos** inclui todos os resultados dos filtros aplicados, além da página
visível. Desmarcar uma linha retira somente aquela página da seleção. As seleções
individuais são mantidas ao paginar e são limpas ao aplicar novos filtros.
A barra de ações informa a quantidade e oferece **Excluir das extrações**
(mantém o histórico) e **Excluir todos os dados**. Ambas exigem confirmação.
Os filtros usados na seleção permanecem os aplicados na tabela, mesmo se os
inputs forem editados antes de clicar em Aplicar filtros.

As ações por página são:

- **Interromper coleta**: mantém o histórico e desabilita o acompanhamento.
  Também bloqueia a redescoberta da mesma chave de produto naquela fonte,
  inclusive em buscas diferentes, e bloqueia atualizações pendentes.
- **Excluir dados**: interrompe a coleta e remove observações, preços, ofertas,
  vínculos, validações, registros de busca semântica, jobs, capturas e auditorias
  vinculadas. Variantes e produtos são removidos apenas quando nenhuma outra
  página os utiliza. A confirmação explica que o alcance inclui outras buscas
  da mesma página. A exclusão é transacional.

O registro mínimo em `scraping.excluded_page` sobrevive à exclusão para impedir
que os dados retornem em novas buscas. A identidade é `(site, source_key)`;
o mesmo produto em outra fonte continua disponível. Os registros operacionais
de descobertas e as definições de buscas/rotinas são preservados, com o produto
removido dos resumos dessas execuções.

O backend retorna 409 se houver uma execução em andamento na fonte ao excluir
definitivamente. Interromper continua permitido durante a execução; o worker
verifica o bloqueio antes da leitura da página e novamente antes de persistir.
Uma coleta já iniciada pode terminar a leitura, mas não recria o produto.

Arquivos sem outras referências são colocados em `scraping.asset_deletion`
na mesma transação. O backend os remove do S3/MinIO em segundo plano a cada
10 segundos, com novas tentativas em caso de indisponibilidade. Arquivos
compartilhados são preservados. Upload e limpeza usam a mesma trava por objeto.

## API e atualização

- `GET /data?q=...&site=...&request_id=...&limit=25&offset=0`
- Preço: `price_operator=gt|eq|lt|between`, `price`, `price_to` (somente entre)
  e `currency` (padrão `BRL`). Os valores são comparados como decimais.
- `POST /data/bulk`: `action=exclude|purge`, `expected_count` e uma seleção:
  `ids`, ou `all_matching=true`, `filters` e `excluded_ids` opcionais. A operação
  usa uma única transação. Se a quantidade mudou, retorna 409 sem aplicar a ação.
- `DELETE /data/{entity_public_id}`: interromper mantendo dados.
- `DELETE /data/{entity_public_id}?purge=true`: excluir dados da página.

Todos exigem autenticação. `request_id` é UUID; `limit` aceita de 1 a 100.
Antes de iniciar o backend e os workers atualizados, aplique a migration
`20261019_12_data_management` usando o serviço de migrations habitual. Ela cria
as tabelas de bloqueio e limpeza, com rollback correspondente.

Os testes de persistência em `tests/test_product_persistence.py` cobrem as
ações, o bloqueio após exclusão e a preservação de produtos compartilhados.
Podem ser executados com `TEST_WORKFLOW_DATABASE_URL` em um banco de testes
com todas as migrations aplicadas; as transações são revertidas ao final.
