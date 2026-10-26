# Panoptes

Monorepo Python para scraping nao comercial, com descoberta por termo e
acompanhamento historico de produtos, com executores para Amazon Brasil, Mercado Livre,
KaBuM!, Pichau e TerabyteShop. Veja [extração de hardware e testes reais](docs/hardware-extraction.md).
Veja [selecao de fontes e contrato v1.2](docs/multi-source-workflow.md).
Veja [servidor MCP e ferramentas de consulta/coleta](docs/mcp.md) para conectar agentes.
Veja [alertas e webhooks](docs/alerts.md) para configurar eventos por rotina e regras de preço pela interface ou pelo MCP.
Veja [busca, descrição e classificação de produtos](docs/product-profiles.md) para o novo fluxo de mapeamento.
Veja [conexões por navegador autenticado](docs/browser-connections.md) para fazer
login manual e reutilizar sessões criptografadas nas coletas.

| Diretorio | Responsabilidade |
| --- | --- |
| `backend/src/panoptes_backend` | API async para termos, requisicoes, produtos, historico e tracking |
| `workers/src/panoptes_workers` | Descoberta e refresh async, fila PostgreSQL e parsers Amazon |
| `migrations` | Servico separado que aplica migrations Yoyo e encerra |
| `packages/contracts` | Contratos Pydantic versionados e orquestracao de camadas |
| `packages/database` | Factory SQLAlchemy/asyncpg, pools e unidade de trabalho |
| `packages/storage` | Cliente S3/MinIO async para HTMLs e imagens privados |
| `workers/parsers` | Manifests, HTMLs sanitizados/sinteticos e resultados esperados |
| `agents` | Prompts e schemas separados de navegacao, extracao e manutencao |

## Executar

Para usar o PostgreSQL Docker existente no servidor, veja
[implantacao no servidor](docs/server-deployment.md).

Requisitos: Python 3.12+, uv, Docker Compose e um servico S3 compativel externo
com bucket `panoptes` e credencial restrita a ele. Configure `S3_ENDPOINT_URL`,
`S3_PUBLIC_ENDPOINT_URL`, `S3_ACCESS_KEY` e `S3_SECRET_KEY` no `.env` antes de subir.

```sh
uv sync --all-packages
docker compose up --build -d
docker compose exec workers python -m panoptes_workers.cli --api-url http://backend:8000 discover "Database Internals" --authors "Alex Petrov"
```

Copie `.env.example` para `.env` para personalizar a configuracao. Compose usa
PostgreSQL 17 com pgvector, backend, migrations e workers. O armazenamento S3
e externo; no servidor ele usa o Silo compartilhado, servico Docker `s3`.
Migrations aguardam PostgreSQL saudavel; backend/workers aguardam migrations
bem-sucedidas. Os processos Python rodam sem privilegios.

API: `http://localhost:8000`. O endpoint publico S3 deve ser acessivel pelo navegador.
Todas as operacoes de negocio e `/openapi.json` exigem JWT. Login e renovacao
por refresh token, assim como `/health/live` e `/health/ready`, sao as excecoes.
Na inicializacao, o backend cria ou atualiza o superusuario somente se
`SUPERUSER_NAME`, `SUPERUSER_EMAIL` e `SUPERUSER_PASSWORD` estiverem todos
preenchidos no ambiente. O `.env` e o `.env.example` incluem `admin`,
`admin@panoptes.com` e `admin` como defaults locais; sem essa configuracao,
nenhum superusuario e criado ou atualizado. A senha usa hash Argon2.
A CLI usa `PANOPTES_EMAIL` e `PANOPTES_PASSWORD` para autenticar.
Veja [autenticacao e rotinas](docs/auth-and-routines.md) para configurar agendas
antes do frontend.
As credenciais postgres/postgres sao defaults locais. As credenciais S3 devem
ser provisionadas no servico externo, com acesso apenas ao bucket configurado.
URLs de banco com caracteres reservados no usuario/senha exigem percent-encoding.
As portas publicadas sao configuraveis via POSTGRES_PORT (5432) e BACKEND_PORT
(8000); valores ausentes ou vazios usam esses defaults. As portas internas e
conexoes entre containers permanecem fixas. `S3_PUBLIC_ENDPOINT_URL` configura
o endereco dos downloads assinados. Workers e migrations nao possuem servidores
de rede. Para processos fora do Docker,
ajuste tambem as URLs locais/--api-url quando mudar uma porta.
O frontend faz parte do Compose, na porta FRONTEND_PORT (3000). No Windows,
execute `npm run dev` em frontend: o Vite le o `.env` da raiz e acessa o backend
por BACKEND_HOST/BACKEND_PORT; o container usa o DNS backend:8000. A porta
FRONTEND_DEV_PORT (5173) permite executar ambos juntos.
Veja [execucao do frontend](frontend/README.md).

O backend cadastra o termo e enfileira uma requisicao. O worker visita a busca,
valida candidatos, entra nos aprovados e confirma a identidade. Cada ASIN e um
produto separado, associado a um ou varios termos. Os produtos aprovados ganham
atualizacao direta por link nas agendas de Rotinas, sem repetir a busca, preservando
observacoes anteriores de preco, estoque, cupons, promocoes e demais metadados.
HTMLs e imagens sao enviados ao S3; PostgreSQL guarda metadados e referencias.

Veja o [fluxo Amazon e comandos completos](docs/amazon-workflow.md), o
[contrato base de extracao](docs/extraction-contract.md) e o
[exemplo de configuracao do livro](docs/examples/database-internals.json).

## API

| Endpoint | Uso |
| --- | --- |
| `POST /auth/login`, `POST /auth/refresh` | Obter JWT e renovar com rotacao |
| `GET /auth/me`, `POST /auth/logout` | Usuario autenticado e revogacao da sessao |
| `POST /routines`, `GET /routines` | Criar e listar agendas de extracao |
| `GET/PUT/DELETE /routines/{uuid}` | Consultar, configurar ou remover agenda |
| `POST /search-terms` | Cadastrar termo e criterios de identidade |
| `POST /search-terms/{uuid}/discover` | Enfileirar descoberta |
| `GET /search-terms/{uuid}/products` | Produtos agrupados, com ultima observacao |
| `GET /products/{uuid}/observations` | Historico paginado |
| `POST /products/{uuid}/refresh` | Atualizar diretamente pelo link |
| `PATCH /products/{uuid}/tracking` | Alterar intervalo/ativacao |
| `GET /scrape-requests/{uuid}` | Estado e resumo da execucao |
| `GET /contracts/{name}` | Exportar JSON Schema |
| `GET /assets/{uuid}/url` | URL privada temporaria para HTML/imagem |

IDs internos nunca aparecem nas respostas. Precos/custos sao Decimal e strings
no JSON. Campos ausentes permanecem desconhecidos. Captcha ou bloqueio HTTP
encerra o fluxo e preserva o HTML. A classificação semântica usa OpenRouter quando configurado; os preços vêm dos parsers.
O frontend SvelteKit em `frontend` oferece login, dashboard, analytics, rotinas
e extracoes. Veja [frontend e sessao](docs/frontend.md) para executar e validar.
Buscas por categoria e a separacao de catalogo/ofertas estao documentadas em
[categorias e precos](docs/category-and-pricing.md), com um
[exemplo de TV de 50 polegadas](docs/examples/tv-50-polegadas.json).

## Desenvolvimento e validacao

```sh
uv run --all-packages python -B scripts/run_tests.py
uv run --all-packages ruff check packages backend/src workers/src migrations/src tests
```

O runner mantem os temporarios dentro do workspace e aceita argumentos do pytest,
por exemplo `uv run --all-packages python -B scripts/run_tests.py -q`.
O runner em scripts/run_tests.py limpa caches do projeto ao terminar, inclusive
quando ha falhas. Para limpar separadamente: `python -B scripts/clean_caches.py`.
Ele preserva .venv, node_modules e diretorios privados de ferramentas.
Testes offline cobrem parsers, validacao de candidatos, uploads, descoberta,
refresh, recuperacao de requisicoes e contratos HTTP. A busca e uma pagina de
produto reais foram lidas em 04/10/2026; ha fixture sanitizada desse produto.
Docker/PostgreSQL/MinIO reais nao foram executados neste ambiente.
Integracao e opt-in: `RUN_INTEGRATION_TESTS=true` e `TEST_DATABASE_URL` apontando
para um banco PostgreSQL vazio e descartavel com pgvector disponivel.

Cada processo tem um pool async proprio, configurado por DB_POOL_MIN/DB_POOL_MAX.
Pool size define capacidade mantida, nao conexoes pre-abertas. Cada tarefa usa sua
sessao. A unidade de trabalho confirma uma vez no sucesso e desfaz no erro;
repositorios nao executam commit. Yoyo e sincrono, isolado em servico separado.
A taxa de requests da Amazon e limitada por processo; escalabilidade por host
exige um limitador distribuido antes de multiplicar replicas para a mesma loja.

## Migrations e compatibilidade

As migrations anteriores mantem IDs, agora em `migrations/sql`, com rollback
separado no formato Yoyo. Em bancos ja migrados, confira historico/checksums e
localizacao das tabelas Yoyo: o runner novo usa o schema `migration`. Nenhum banco
existente foi migrado neste ambiente. A nova migration adiciona termos, targets,
requisicoes, validacoes, associacoes e assets sem reescrever migrations anteriores.

O schema scraping guarda rotinas/parsers versionados, capturas, jobs, tentativas,
entidades/observacoes, embeddings e a view html_cost. A extensao vector fica em
extensions e permanece no rollback por ser compartilhada. Custos OpenRouter usam
NUMERIC(24,16), evitando arredondar chamadas pequenas para zero. Busca semantica e
fallback comercial usam OpenRouter e registram cada chamada em `ai.interaction`,
com entrega assincrona do JSON completo ao S3 por uma outbox persistente.
Ledger/reservas de orcamento e reconciliacao continuam interfaces futuras.

As imagens de build usam versoes fixas e `uv.lock --frozen`. O catalogo de agentes
fica em `agents/metadata.yaml`, com prompts Markdown e JSON Schemas opcionais.
O backend faz upsert de agentes na inicializacao e sincroniza capacidades e
precos dos modelos no inicio e a cada hora. Consulte [agents/README.md](agents/README.md).
Os entry points em `backend/agents_module` e `backend/openrouter_module` delegam
ao pacote compartilhado `panoptes-ai`; o workspace usa o lockfile da raiz.

## Extensão de sessões

A extensão Chrome/Edge em [`extensions/session-bridge`](extensions/session-bridge/README.md)
envia ao Panoptes a sessão da aba em que você já está autenticado no Mercado Livre
ou na Amazon Brasil. Instale a pasta pelo modo do desenvolvedor e mantenha uma
aba do Panoptes autenticada como administrador no mesmo perfil. A importação
valida o login no backend antes de substituir a sessão criptografada existente.
Veja o README da extensão para instalação, uso e limitações.

## Logs de extrações

A tela **Logs de extrações** acompanha etapas ao vivo por SSE, com histórico
persistido e filtros por execução, fonte e nível. Use **Ver logs** na lista de
extrações para investigar uma falha. Veja [a documentação](docs/extraction-logs.md)
para detalhes dos eventos e da API autenticada.
