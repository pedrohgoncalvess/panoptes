# Servidor com PostgreSQL compartilhado

O override `compose.server.yaml` conecta migrations, backend e workers ao
PostgreSQL existente na rede externa `dokploy-network`. O servico PostgreSQL
local fica em um profile separado. MinIO e sessoes usam volumes do Panoptes.

No servidor, o checkout fica em `/home/pedro/Desktop/projects/panoptes`, ao lado
do Gork. A configuracao privada fica no `.env`, fora do Git. Ela define:

- `POSTGRES_USER=panoptes`, `POSTGRES_DB=panoptes` e uma senha exclusiva.
- `DATABASE_NETWORK=dokploy-network` e o hostname Docker `postgres`.
- `FRONTEND_BIND_HOST`, `FRONTEND_PORT` e `FRONTEND_ORIGIN` para o acesso web.
- `S3_BIND_HOST`, `S3_PORT`, `MINIO_CONSOLE_PORT` e `S3_PUBLIC_ENDPOINT_URL`.
- Credenciais MinIO, chaves JWT/browser e OpenRouter quando configurado.
- `BROWSER_SERVICE_URL=http://backend:8000` para coletas com sessoes.

Ao migrar usuarios, deixe `SUPERUSER_NAME`, `SUPERUSER_EMAIL` e
`SUPERUSER_PASSWORD` vazios para preservar suas senhas existentes.

```sh
git pull --ff-only
docker compose -f compose.yaml -f compose.server.yaml config --quiet
docker compose -f compose.yaml -f compose.server.yaml up --build -d
docker compose -f compose.yaml -f compose.server.yaml ps
curl --fail http://127.0.0.1:9876/health/ready
```

O banco deve ser provisionado pelo administrador do PostgreSQL. A role
`panoptes` tem LOGIN, sem SUPERUSER, CREATEDB, CREATEROLE, REPLICATION ou
BYPASSRLS. Ela possui seu banco e os schemas da aplicacao, incluindo `public`;
pgvector e instalado pelo administrador no schema `extensions`. O acesso
PUBLIC ao banco e ao schema `public` e revogado. Regras especificas em
`pg_hba.conf` permitem essa role no banco `panoptes` e rejeitam conexoes aos
demais bancos, preservando as regras dos outros usuarios.

A migracao de 26/10/2026 inclui dump completo, usuarios/hashes, historico de
migrations, arquivos MinIO e sessoes de navegador criptografadas. A chave
`BROWSER_SESSION_KEY` deve acompanhar as sessoes. A origem usava PostgreSQL 17
e o destino usa PostgreSQL 16: o restore remove apenas `transaction_timeout`
e diretivas de cliente `restrict/unrestrict`, indisponiveis nessa versao.
O pgvector existente no destino e provisionado antes do restore. Dados e
objetos da aplicacao sao restaurados em uma transacao sob a role `panoptes`.

Os backups privados e contagens de verificacao ficam fora do checkout em
`/home/pedro/Desktop/projects/panoptes-migration-20261026`, com acesso restrito.
Antes de uma nova migracao, pare os produtores de escrita, tire um dump
consistente e copie tambem os volumes de arquivos e sessoes. Valide contagens,
autenticacao, acesso aos arquivos e isolamento da role antes de iniciar workers.
