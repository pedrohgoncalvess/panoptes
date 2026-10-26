# Servidor com PostgreSQL e Silo compartilhados

O arquivo de producao `compose.server.yaml` e independente: execute-o sozinho,
sem combinar com `compose.yaml`. Ele reaproveita via `extends` apenas migrations,
backend, workers e frontend. PostgreSQL e MinIO nao fazem parte da configuracao
de producao. O `compose.yaml` continua incluindo PostgreSQL para desenvolvimento.
Migrations, backend e workers usam o PostgreSQL existente na rede externa
`dokploy-network`. Backend e workers acessam o Silo existente
pelo hostname `s3`, na mesma rede. Apenas as sessoes usam um volume do Panoptes;
o projeto nao inicia MinIO nem um inicializador de volume de armazenamento.

No servidor, o checkout fica em `/home/pedro/Desktop/projects/panoptes`, ao lado
do Gork. A configuracao privada fica no `.env`, fora do Git. Ela define:

- `POSTGRES_USER=panoptes`, `POSTGRES_DB=panoptes` e uma senha exclusiva.
- `DATABASE_NETWORK=dokploy-network` e o hostname Docker `postgres`.
- `FRONTEND_BIND_HOST`, `FRONTEND_PORT` e `FRONTEND_ORIGIN` para o acesso web.
- `S3_ENDPOINT_URL=http://s3:9000` e `S3_BUCKET=panoptes`.
- `S3_PUBLIC_ENDPOINT_URL=http://100.83.108.118:9000` para downloads assinados.
- `S3_ACCESS_KEY=panoptes` e `S3_SECRET_KEY` exclusiva, fora do Git.
- Chaves JWT/browser e OpenRouter quando configurado.
- `BROWSER_SERVICE_URL=http://backend:8000` para coletas com sessoes.

Ao migrar usuarios, deixe `SUPERUSER_NAME`, `SUPERUSER_EMAIL` e
`SUPERUSER_PASSWORD` vazios para preservar suas senhas existentes.

```sh
git pull --ff-only
docker compose -f compose.server.yaml config --quiet
docker compose -f compose.server.yaml up --build -d
docker compose -f compose.server.yaml ps
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
O armazenamento foi transferido do MinIO dedicado para o bucket `panoptes` do
Silo compartilhado. A credencial IAM `panoptes` recebe a policy
[`panoptes-bucket-full-access`](../deploy/s3/panoptes-policy.json), com `s3:*`
somente em `arn:aws:s3:::panoptes` e `arn:aws:s3:::panoptes/*`, e negacao
explicita para outros recursos S3. Ela nao recebe permissoes administrativas.
O bucket permanece privado; downloads usam URLs assinadas. Nao ha mudancas
nas bibliotecas S3 da aplicacao.

Para provisionar essa policy como administrador do Silo, depois de criar o
bucket e a credencial com uma senha exclusiva:

```sh
mc admin policy create silo panoptes-bucket-full-access deploy/s3/panoptes-policy.json
mc admin policy attach silo panoptes-bucket-full-access --user panoptes
```

Antes de uma nova migracao, pare os produtores de escrita, tire um dump
consistente e copie tambem os objetos S3 e o volume de sessoes. Valide contagens,
autenticacao, acesso aos arquivos e isolamento da role antes de iniciar workers.
