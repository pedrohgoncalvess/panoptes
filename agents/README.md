# Agentes internos da plataforma

`metadata.yaml` é a fonte de configuração dos agentes Panoptes. Cada entrada
define `model` com o ID do OpenRouter, `prompt` relativo a esta pasta e, se
necessário, `structured_output` apontando para um JSON Schema. O schema é opcional.
`settings` contém parâmetros de inferência; `version` identifica a configuração.
`structured_output_strict: false` permite schemas de domínio com propriedades
opcionais ou mapas abertos; o gateway sempre valida o retorno pelo JSON Schema.
Não colocar credenciais, cookies ou tokens nos prompts/metadata.

Na inicialização, o backend lê e valida os arquivos, cria os modelos referenciados
e faz upsert de `ai.agent` por slug, incluindo prompt e schema. Erros nos arquivos
impedem a inicialização. Alterações são aplicadas no próximo início; o catálogo é
versionável junto com o código. Agentes removidos do YAML não são apagados do banco,
preservando o histórico. `AGENTS_CATALOG` permite selecionar outro catálogo.

O prompt de embeddings documenta a finalidade e é auditado; o endpoint de
embeddings recebe somente `input`, sem mensagem de sistema. Para trocar esse
modelo, altere o YAML e incremente `version`; a busca reindexa os documentos e
filtra pelo espaço vetorial correspondente ao agente/modelo/dimensões/versão.

Para chamar qualquer agente use `panoptes_ai.client.OpenRouter.invoke(slug,
content, context=...)`. O gateway resolve modelo, prompt e schema no banco,
persiste a interação antes da chamada e valida respostas estruturadas. Passos e
tentativas devem chamar o gateway separadamente. HTML é dado não confiável.
O executor continua responsável por validar navegação e aprovar reparos.

`ai.model` armazena modalidades de entrada e saída em arrays, arquitetura,
parâmetros suportados, contexto, limites, defaults e metadados completos.
Assim, imagem/áudio/texto/embedding são capacidades independentes e extensíveis.
O catálogo OpenRouter é consultado com `output_modalities=all` no início e a cada
3600 segundos (`OPENROUTER_SYNC_INTERVAL_SECONDS`). Apenas modelos cadastrados
são atualizados. `ai.model_price` mantém histórico quando o objeto de preços muda,
com valores decimais em USD na unidade fornecida pela API (tokens por unidade,
não por milhão). O JSON completo preserva preços multimodais e faixas futuras.
Preço de catálogo não é custo faturado: a interação usa `usage.cost` quando
informado; custo ausente fica desconhecido.

`ai.interaction` registra modelo solicitado, agente, versão/hash do prompt,
contexto, tokens, resposta, status, latência e custo. O contexto inclui IDs de
extração/captura quando disponíveis. A resposta completa inclui o modelo efetivo
retornado pelo roteamento, vinculado por `model_id`; `requested_model_id` preserva
o modelo configurado. Capturas são ligadas por FK a `html_snapshot_id` e
`scrape_request_id`; `job_id` é opcional no enriquecimento anterior ao job.
`ai.audit_outbox` guarda o JSON duravelmente na mesma
transação de finalização; uma tarefa assíncrona envia para
`s3://<bucket>/ai/interactions/<public_id>.json` e preenche bucket/chave/hash na
interação. Falhas no S3 geram retentativas com backoff, inclusive após reinício;
uploads usam chave determinística. Cabeçalhos de autenticação não entram no JSON.

Sincronização manual: `uv run python -m panoptes_ai.sync agents` e
`uv run python -m panoptes_ai.sync models`. São rotinas determinísticas e não
consomem tokens de inferência para carregar os arquivos no banco.

Operação: configure `OPENROUTER_API_KEY`, aplique migrações e reinicie backend e
workers. Sem chave, o fallback comercial fica desativado e a indexação semântica
aguarda configuração. Não há fallback de inferência fora do OpenRouter.

Referências da API: [catálogo, modalidades e preços](https://openrouter.ai/docs/guides/overview/models)
e [embeddings](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request).
