# Autenticacao e rotinas

O backend cria ou atualiza o superusuário somente quando `SUPERUSER_NAME`,
`SUPERUSER_EMAIL` e `SUPERUSER_PASSWORD` estão definidos e não vazios no ambiente.
O `.env` local e o `.env.example` incluem nome `admin`, e-mail `admin@panoptes.com`
e senha `admin` como valores de desenvolvimento. Compose repassa esses valores
sem defaults próprios: se qualquer variável estiver ausente ou vazia, o backend
não cria nem atualiza o superusuário. Usuários existentes são preservados.
Para executar fora do Compose, carregue o arquivo com `uv run --env-file .env`.
O e-mail é normalizado; o hash Argon2 é mantido quando a senha já corresponde.
Alterar a senha configurada revoga as sessões antigas desse usuário.
`JWT_SECRET` deve ter pelo menos 32 bytes. Compose e `.env.example` fornecem
um valor de desenvolvimento. Os workers acessam o banco internamente e a CLI
usa login para enviar comandos ao backend.

## Login e sessao

`POST /auth/login`:

```json
{"email":"admin@panoptes.com","password":"admin"}
```

A resposta tem `access_token`, `refresh_token`, `token_type: "bearer"` e
`expires_in` de até 7200 segundos e `refresh_expires_in` com o prazo restante da sessão. Envie `Authorization: Bearer <access_token>` em todas as
operacoes, inclusive contratos, assets, rotinas e `/openapi.json`.

`POST /auth/refresh` recebe `{"refresh_token":"<refresh_token>"}` e retorna um
novo par. O access token dura 2 horas e a sessao dura 10 horas a partir do
login. O refresh token e rotacionado atomicamente sob lock; apenas seu hash
fica no banco. Reutilizar um refresh antigo revoga a sessao inteira. O cliente
deve serializar renovacoes concorrentes e substituir ambos os tokens.

`GET /auth/me` retorna public_id, email e nome. `POST /auth/logout` revoga a
sessao, invalidando access e refresh tokens. Cada chamada autenticada verifica
tambem o estado da sessao e do usuario no banco. Login, refresh (que exige seu
proprio token) e sondas `/health/live` e `/health/ready` ficam publicos.

## Navegador e credenciais MCP

O login fica em `/`; `/login` redireciona para `/`. As páginas protegidas validam
`/auth/me` no servidor antes de renderizar e voltam a `/` quando a sessão expira.
Os tokens ficam em cookies HttpOnly, SameSite Strict e Secure em HTTPS. O refresh
dura 10 horas a partir do login; a rotação não estende esse prazo.

Usuários autenticados gerenciam suas chaves em `/administrator/mcp-keys` e na API:
`GET/POST /auth/mcp-keys`, `DELETE /auth/mcp-keys/{uuid}`. A chave JWT usa audiência
exclusiva e prefixo `pmcp_`, vincula-se ao emissor e é retornada apenas na criação.
Somente seu SHA256 é persistido. Cada chamada verifica usuário ativo, assinatura,
expiração, revogação e permissões atuais. Uma chave MCP não pode emitir outras.

A criação aceita `name`, `admin`, `routine_ids`, `permissions` e `expiration`:
`1w`, `2w`, `1m`, `6m`, `1y`, `never` ou `custom` com `expires_at` ISO 8601 e fuso.
Meses e anos seguem o calendário, ajustando o último dia quando necessário.
Somente usuários administradores emitem MCP admin; esse modo ignora permissões,
limites e seleções de rotina. Perder o papel admin invalida essas chaves.

`permissions` contém `create_routines`, `manage_routines`, `create_extractions`,
`view_extractions`, `create_alerts`, `max_routines` (null = ilimitado) e `sites`
(Amazon, Mercado Livre, KaBuM, Pichau e Terabyte). O padrão nega tudo.
A cota conta rotinas existentes criadas pela chave; excluir uma libera a vaga.
A verificação e a criação usam a mesma transação com lock da chave.

Rotinas selecionadas e as criadas pela chave definem o escopo. Termos cadastrados
pela própria chave também permitem consultar suas extrações avulsas. Listagens
aplicam os filtros antes da paginação. Recursos de outras rotinas retornam 403.
Buscas de produtos e `/analytics/prices` exigem `term_id` autorizado. Consultas
globais de catálogo, analytics, logs e dados administrativos exigem MCP admin.
Alertas de chaves restritas exigem rotinas explícitas autorizadas; só a própria
chave pode gerenciá-los. A entrega revalida credenciais e rotinas; se a chave
expirar, for revogada ou perder acesso, os envios são cancelados e o alerta pausado.

Aplicar a migration `20261024_17_mcp_keys` antes de subir a nova versão da API.

## Rotinas de extracao

Cadastre primeiro o termo e seus criterios em `/search-terms`, ou use a CLI de
descoberta. Depois, envie `POST /routines`:

```json
{
  "name": "Database Internals - acompanhamento",
  "search_term_id": "<UUID retornado pelo cadastro do termo>",
  "mode": "refresh",
  "sites": ["terabyte", "kabum"],
  "enabled": true,
  "schedule": {
    "kind": "fixed",
    "timezone": "America/Sao_Paulo",
    "times": ["08:00", "13:00", "20:00"]
  }
}
```

`sites` seleciona os marketplaces da rotina. As opções permitidas são as fontes
da primeira extração do mesmo termo e configuração (mesmo lote/correlation_id).
É obrigatório manter pelo menos uma selecionada; fontes ausentes nessa extração
ficam indisponíveis. A seleção também pode ser alterada no `PUT /routines/{uuid}`.
`GET /search-terms/{uuid}/routine-sources` consulta as opções disponíveis.
Uma única rotina enfileira descoberta ou atualização em todas as fontes escolhidas.
A migration `20261019_14_routine_sources` preserva o marketplace das rotinas existentes.

`mode: discover` visita a busca, valida candidatos e extrai detalhes dos livros
aprovados. `mode: refresh` enfileira atualizacoes diretas de todos os produtos
associados ao termo que tenham tracking ativo. Use duas rotinas quando quiser
redescobrir ocasionalmente e atualizar ofertas com maior frequencia. Uma rotina
de refresh precisa que a descoberta tenha encontrado produtos para executar
atualizacoes; ela nao repete a busca.

Alternativas para o campo `schedule`:

```json
{"kind":"random_daily","timezone":"America/Sao_Paulo","times_per_day":4}
```

```json
{"kind":"interval","timezone":"America/Sao_Paulo","interval_minutes":30}
```

Horarios fixos aceitam HH:MM distintos. Aleatorios usam minutos distintos ao
longo de todo o dia local (1 a 1440), com sequencia deterministica por rotina,
data e configuracao: reiniciar nao sorteia novamente. Intervalos comecam a
contar do cadastro/edicao; atrasos do scheduler preservam a cadencia.
Fusos sao nomes IANA. Horarios inexistentes na transicao de horario de verao
sao ignorados; horarios repetidos executam apenas a primeira ocorrencia.

`GET /routines` e `GET /routines/{uuid}` mostram agenda e `next_run_at` UTC.
`PUT /routines/{uuid}` recebe name, schedule e enabled, recalcula a proxima
execucao e permite pausar com enabled=false. `DELETE` remove a configuracao.
Pausar ou remover nao cancela requisicoes ja enfileiradas.

Enquanto existir uma rotina de refresh para um termo, o intervalo legado dos
targets desse termo fica substituido pela agenda, inclusive quando pausada.
Remover todas essas rotinas retoma o intervalo legado. Um produto associado
a varios termos pode receber atualizacoes por cada agenda; requisicoes ativas
para o mesmo produto sao coalescidas pela fila.

O scheduler roda a cada 5 segundos em tarefa async separada da extracao. Cada
replica usa `FOR UPDATE SKIP LOCKED` e a mesma transacao para enfileirar e avancar
o prazo. Depois de uma interrupcao, enfileira uma execucao vencida e avanca para
a proxima futura; nao reproduz todo o periodo offline. Os horarios indicam
enfileiramento; o inicio real depende da disponibilidade dos workers.

## Validacao

Testes offline verificam JWT, expiracao, autenticacao obrigatoria, rotacao,
replay, seed do admin, fuso, transicao de horario de verao, sorteio estavel e
avanco da agenda. A migration `20261004_05_auth_schedules` tem rollback e integra
a suite PostgreSQL opt-in. Docker nao esta disponivel no ambiente de implementacao,
portanto execucao real com PostgreSQL/MinIO ainda precisa desse teste de integracao.
