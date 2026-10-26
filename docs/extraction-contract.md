# Contrato de extração v1.0

A extensão de seleção e execução em múltiplas fontes v1.2 está em
[multi-source-workflow.md](multi-source-workflow.md).

O fluxo executável de busca/validação/refresh e a extensão de contratos v1.1 estão
descritos em [amazon-workflow.md](amazon-workflow.md). Os contratos v1.0 continuam
disponíveis; termos, candidatos, tracking targets, ofertas e assets são contratos
novos. O executor Amazon usa o parser específico com fallback JSON-LD dentro dele;
browser e execução paga de LLM continuam desativados.

## Fluxo e critérios

Uma rotina possui versão, domínio, tipo de entidade (produto/serviço), seeds,
hosts permitidos, intervalo, limites por host e política de extração. O UUID da
rotina identifica uma revisão persistida. Atualizações de conteúdo criam nova
revisão; jobs já emitidos continuam ligados à revisão original. Ativação pode
ser alterada sem modificar o conteúdo da revisão.

O job fixa UUID, correlation_id, chave de idempotência, rotina/versão,
parser/versão, política e captura. Os valores públicos são UUIDs, convertidos
para IDs internos apenas pelos repositórios. A chave de idempotência deve incluir
rotina, captura e versão do parser. A SHA do HTML identifica bytes iguais;
**não** identifica uma visita: duas capturas iguais continuam sendo eventos distintos.

| Camada | Adapter futuro | Quando seguir para próxima |
| --- | --- | --- |
| `structured_data` | JSON-LD e estado JSON embutido | Dados ausentes ou inválidos |
| `site_parser` | Parser versionado por loja/layout | Campos obrigatórios/evidências ausentes ou baixa confiança |
| `rendered_dom` | Captura browser e parsing do DOM | Renderização insuficiente |
| `llm` | Navegador/extrator via OpenRouter | Último recurso, orçamento e chamadas limitados |

`run_pipeline` é uma orquestração offline com adapters injetados. O contrato permite
selecionar/substituir camadas, exige ordem final de LLM, rejeita duplicatas,
define timeout por camada e propaga cancelamento. Uma camada precisa retornar
entidades válidas, confiança mínima e evidência por **entidade e campo obrigatório**,
vinculada à captura. `blocked` encerra a cadeia. Falha/miss/resultado insuficiente
permitem fallback; esgotamento não produz entidades aprovadas. Erros de adapters
têm motivo genérico, sem expor HTML, credenciais ou stack ao consumidor.

Confiança não substitui evidência. Preço/currency aparecem juntos e valor ausente
é null. O extrator nunca inventa disponibilidade, preço ou descrição. Dados
estruturados têm prioridade, mas precisam dos mesmos critérios de validação.

Um adapter browser que gerar novos bytes deve salvar **nova captura** com
`parent_snapshot_id` e emitir um job derivado. Não pode atribuir evidência do DOM
novo à captura antiga. A interface atual processa uma captura por job; um workflow
futuro coordenará esses jobs para navegação e renderização.

## HTMLs, parsers e atualização por agentes

`HtmlSnapshot` guarda URL original/final, timestamp com timezone, status HTTP,
modo de captura, tamanho, encoding, SHA-256 e URI do artifact. Conteúdo HTML fica
fora das mensagens da fila; o armazenamento futuro precisa validar tamanho/hash
e limitar acesso. Manifests apontam para arquivos relativos ao diretório do parser;
o loader de parsers adicionais deve impedir escape de diretório.

Cada parser tem slug, versão, hosts, tipo de entidade, entrypoint e fixtures.
Uma fixture reúne HTML sanitizado/sintético, resultado esperado e procedência.
Fixtures devem cobrir falhas/layouts, não apenas sucesso. Correções criam versão
nova, passam pelo conjunto completo de regressão e revisão antes da ativação.
O agente de manutenção retorna `ParserRepairProposal`; o runtime nunca executa
automaticamente código proposto por LLM. Capturas reais e tokens/cookies não entram
em fixtures versionadas.

## Agentes OpenRouter e precisão de custo

Os três papéis ficam em `agents` com prompts e output schemas separados:

| Papel | Saída | Responsabilidade |
| --- | --- | --- |
| navigator | `NavigationAction` | Propor um próximo passo dentro dos hosts/limites |
| extractor | `LayerOutcome` | Extrair entidades e evidências do HTML fornecido |
| parser_repair | `ParserRepairProposal` | Propor correção offline com fixtures a verificar |

O catálogo `agents/metadata.yaml` define IDs OpenRouter, prompts Markdown e JSON
Schemas opcionais. O backend sincroniza o catálogo com `ai.agent` ao iniciar.
O gateway `panoptes_ai.client.OpenRouter` aplica prompt/schema e registra todas
as chamadas antes de enviá-las. A busca semântica e o fallback comercial usam
esse gateway; navigator/extractor/parser_repair estão registrados para os seus
adaptadores. O pipeline de contrato offline continua sem executar inferência
paga automaticamente. Consulte `agents/README.md` para catálogo e auditoria.

HTML é entrada não confiável, nunca instrução para o agente. O navigator propõe
ações; executor valida host, redirects, alvo e orçamento antes de qualquer ação.
Cada passo e retry corresponde a uma interação própria, persistida **antes** da
chamada, inclusive falhas/cancelamentos que podem ter sido cobrados pelo provider.
Uma interação pertence a um job e a uma captura; batch de múltiplos HTMLs não
é permitido nessa unidade de contabilização.

`LlmInteraction` inclui versão do agente, modelo/provider, identificador de geração,
hash do prompt, tentativa, tokens, snapshot de preços, custo e estado:

- `unknown`: custo null; não pode ser contado como custo zero.
- `estimated`: estimativa decimal segundo preços armazenados; ainda não definitivo.
- `reported`: custo retornado pelo provider.
- `reconciled`: custo confirmado pelo endpoint de geração OpenRouter.

O custo informado deve incluir componentes cobrados pelo provider, não somente
tokens de entrada/saída. O gateway armazena `usage.cost` quando disponível e
preserva o ID da geração; reconciliação posterior pelo endpoint de geração
continua pendente. Custo ausente permanece desconhecido.
`HtmlCostSummary` e `scraping.html_cost` somam valores conhecidos e expõem quantas
interações ainda têm custo desconhecido/estimado. O total só é completo quando
essas contagens forem zero. O índice único de generation ID impede duplicar cobrança
ao reconciliar a mesma chamada. Atualizar custo substitui o valor da interação;
não insere uma segunda cobrança.

`max_llm_calls` e `max_cost_usd` têm defaults zero. O pipeline offline não executa
chamadas LLM, mesmo que adapters sejam registrados; o fallback comercial e a
busca semântica têm fluxos próprios pelo gateway auditado. `InteractionLedger` define
a fronteira futura: reservar atomicamente um teto por chamada antes de liberar
a execução, contando reservas concorrentes e custos desconhecidos contra o limite.
Se não existir teto verificável, não chamar. Uma reserva precisa sobreviver a crash,
ser reconciliada por generation ID e só ser liberada após confirmar o custo. Não
apresentar esses limites declarativos como um controle financeiro já implementado.

## Persistência e entrega dos jobs

A fila futura deve usar claim com lease, renovar a posse em trabalhos longos e
aceitar complete apenas para o owner atual e lease válida. PostgreSQL permite
claim com `FOR UPDATE SKIP LOCKED`. Retry recupera leases expiradas sem duplicar
observações, cujas chaves são `(entity_id, job_id)`. Entrega é ao menos uma vez;
idempotência deve ser garantida pela persistência.

Rotinas e entidades ficam sob administração do backend, workers dependem dos
contratos e de repositórios próprios. Shared session entre tarefas paralelas é
proibida. A atualização de jobs/observações/interações é uma unidade de trabalho
com commit único; I/O remoto não deve manter transações abertas.

## Evolução

V1 rejeita campos desconhecidos e timestamps sem timezone. Campos opcionais novos
com defaults documentados permitem ao consumidor novo aceitar mensagens antigas,
mas o consumidor antigo rejeita esses campos extras. Atualize consumidores antes
dos produtores ou negocie a versão/projeção da mensagem. Mudanças em significado,
campos obrigatórios ou enumeração exigem revisão da versão do contrato e coordenação
da implantação dos produtores/consumidores. Versionar contrato, parser, rotina e
agente separadamente permite reprocessar capturas históricas e auditar resultados.

Referências: [SQLAlchemy async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
[Yoyo](https://ollycope.com/software/yoyo/latest/),
[OpenRouter generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation),
[Selectolax/Lexbor](https://selectolax.readthedocs.io/en/latest/examples.html).
