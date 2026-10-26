# Amazon Brasil: descoberta e acompanhamento por termo

Descoberta: busca → validação preliminar → visita somente aos candidatos
aprovados → confirmação de identidade → cadastro e primeira observação.
Atualização: visita direta ao `/dp/{ASIN}` → confirmação → nova observação.
Não se repete a busca para atualizar um produto.

## Executar Database Internals

```sh
docker compose up --build -d
docker compose exec workers python -m panoptes_workers.cli --api-url http://backend:8000 discover "Database Internals" --authors "Alex Petrov"
```

A CLI retorna `search_term.public_id` e `request.public_id`; o worker processa a
fila automaticamente. Consulte status, agrupamento e dispare refresh manual:

```sh
docker compose exec workers python -m panoptes_workers.cli --api-url http://backend:8000 status <request_uuid>
docker compose exec workers python -m panoptes_workers.cli --api-url http://backend:8000 products <search_term_uuid>
docker compose exec workers python -m panoptes_workers.cli --api-url http://backend:8000 refresh <product_uuid>
```

Também há Swagger em `http://localhost:8000/docs`. Exemplo de `POST /search-terms`:

```json
{
  "site": "amazon_br",
  "term": "Database Internals",
  "criteria": {"title": "Database Internals", "authors": ["Alex Petrov"]},
  "max_pages": 1,
  "refresh_interval_seconds": 86400
}
```

`POST /search-terms/{uuid}/discover` enfileira a descoberta. Chamadas repetidas
enquanto existe trabalho ativo retornam a mesma requisição; depois de concluído,
uma chamada nova realiza outra descoberta. O termo/configuração existente é
imutável nesta versão: POST com critérios/intervalo diferentes retorna conflito.
Maiúsculas/espaçamento equivalentes referem-se ao mesmo termo dentro da mesma loja.

Alex Petrov foi confirmado na [página da editora](https://www.oreilly.com/library/view/database-internals/9781492040330/).
Não fixamos ISBN por padrão, para admitir edições/formatos diferentes;
`criteria.isbn` é opcional e restringe as edições quando fornecido.

## Identidade e agrupamento

Cada ASIN é um produto independente, inclusive Kindle versus livro físico. Um
termo agrega vários produtos e um produto pode pertencer a vários termos: a
associação é muitos-para-muitos, sem duplicar entidade/histórico. ASINs repetidos
ou patrocinados são deduplicados e seus links ficam canônicos, sem tracking.

O título informado precisa corresponder ao início do título do anúncio, admitindo
subtítulo e pequenas diferenças de grafia. Títulos e autores usam pontuação por
palavra, descrita em [comparação de nomes](name-matching.md); sobrenomes isolados
podem corresponder ao nome completo do autor.
Resumo, workbook, summary e outros termos excluídos rejeitam o candidato. Autor
divergente rejeita quando informado na busca. Autor ausente permite apenas
aprovação preliminar; na página do produto, autor esperado ausente gera
`uncertain` e autor/ISBN divergente gera `rejected`. Rejeitados/incertos não entram
no acompanhamento. As decisões, versão do validador e capturas ficam registradas.
Este validador inicial é determinístico e específico para livros; não usa LLM.

## Observações históricas

Produtos aprovados ganham tracking target, atualizado a cada 24h por padrão.
Capturamos preço/preço de referência, disponibilidade, quantidade explicitamente
informada, vendedor, descrição, autores, ISBNs, especificações, avaliações textuais,
imagens e avisos de cupom/promoção/parcelamento/frete presentes no HTML.

O parser combina DOM e JSON-LD, incluindo preços partidos em reais/centavos.
Valores ausentes ficam null; ausência de preço não implica estoque zerado.
Condições de cupons são guardadas como texto, sem calcular preço efetivo nem
assumir elegibilidade. `promotions: []` significa que nenhum aviso foi extraído
dessa captura, não uma garantia sobre ofertas personalizadas.

`GET /search-terms/{uuid}/products` retorna a observação mais recente por produto;
`GET /products/{uuid}/observations` retorna histórico. Para ajustar acompanhamento:

```text
PATCH /products/{uuid}/tracking
{"enabled": true, "refresh_interval_seconds": 3600}
```

Desativação impede novos agendamentos automáticos; tarefas já enfileiradas e
refresh manual continuam permitidos. `POST /products/{uuid}/refresh` atualiza
diretamente. O primeiro termo que descobrir o ASIN define a configuração inicial
do target; termos adicionais reutilizam esse target e seu histórico.

## MinIO privado

O Compose fixa `minio/minio:RELEASE.2025-04-22T22-12-26Z`. Um initializer curto
ajusta o dono do volume; o servidor roda como UID 10001. Console:
`http://localhost:9001`; API S3: `http://localhost:9000`. Defaults locais:
`minioadmin/minioadmin`, configuráveis em `.env.example`. A versão é licenciada
sob [AGPLv3](https://github.com/minio/minio/blob/RELEASE.2025-04-22T22-12-26Z/LICENSE).

O worker cria o bucket privado `panoptes` ao iniciar. HTMLs (inclusive páginas
bloqueadas) e imagens usam S3 async, SHA-256, tamanho e Content-Type. A chave é
`tipo/primeiros_dois_caracteres_do_hash/hash`: bytes iguais reutilizam o objeto,
mas cada visita tem sua própria captura. A imagem principal usa a maior resolução
anunciada por cada elemento, evitando todas as miniaturas da mesma imagem.

As observações vinculam assets por UUID e URI `s3://`. `GET /assets/{uuid}/url`
gera URL temporária por 5 minutos. `S3_PUBLIC_ENDPOINT_URL` precisa ser acessível
pelo navegador. Cookies/credenciais não são gravados em metadados/logs. O HTML
bruto pode conter identificadores de sessão anônima da loja, por isso permanece
privado e fora dos fixtures versionados. O HTML preserva informação para futuras
extensões do parser, mesmo quando um campo não foi reconhecido.

## Limites e verificação

Até 20 páginas configuráveis e 100 ASINs por descoberta; `truncated: true` indica
resultado incompleto. A fila PostgreSQL usa `SKIP LOCKED`, lease de 120s e renovação
a cada 30s. Só o owner atual pode persistir/finalizar. Produtos já gravados naquela
requisição são reconhecidos ao recuperar trabalho interrompido.

Requisições têm timeout e limite de bytes; redirects validam hosts antes da
próxima leitura. Captcha/401/403/429 gera `blocked`, arquiva o HTML e encerra o
fluxo, sem resolver captcha. HTTP 500/502/503/504 sem CAPTCHA permite até três
tentativas, com espera de 2 e 4 segundos; cada resposta é arquivada. Se persistir,
a execução termina como `failed`, com `reason: amazon_unavailable`.
Produtos indisponíveis registram falha individual e a descoberta continua;
se uma página de busca posterior falhar, o resumo preserva os produtos já
processados, com status `partial` quando houve algum produto concluído.
O resumo disponível no frontend inclui causa, status HTTP, URLs, tentativa e
UUIDs da captura e do asset. Logs JSON `source_page_fetched` e `scrape_finished`
correlacionam requisição, captura e resultado, sem registrar cookies ou credenciais.
Consulte-os com `docker compose logs --tail 100 workers`.
Exceções internas geram `scrape_error`, com `error_id`, localização da falha e
`sqlstate` quando disponível. O resumo referencia o mesmo `error_id`; parâmetros
SQL, valores locais e credenciais não são incluídos no log de exceção.
Falhas por produto ou imagem geram execução parcial.
Captura malsucedida não apaga observações anteriores.

`AMAZON_REQUEST_INTERVAL_SECONDS` (padrão 1,5) limita taxa **por processo**.
Antes de escalar vários workers para a mesma loja, precisamos de limitação
distribuída por host. As páginas são consultadas anonimamente por HTTP: ofertas
dependentes de login, CEP, interação ou browser podem não aparecer. Browser/LLM
continuam fronteiras futuras do contrato, com chamadas pagas desativadas.
O cliente HTTP envia `Accept` para HTML e User-Agent compatível com navegador:
na verificação de 05/10/2026, o User-Agent `Panoptes/0.1` recebeu a página genérica
de erro HTTP 503, enquanto o compatível recebeu HTTP 200 com resultados na mesma
busca e no mesmo container. Isso não garante disponibilidade em futuras visitas.

Verificamos a busca pública e a página do produto `1492040347` em 04/10/2026.
`workers/parsers/amazon-book/product.captured.html` é uma amostra sanitizada para
regressão; seu preço é histórico, não cotação atual. Os testes exercitam descoberta
de dois ASINs, rejeição de outros resultados, refresh direto e uploads com limites
HTTP/S3/DB simulados. Integração com Docker/PostgreSQL/MinIO reais requer verificação
opt-in e ainda não foi executada neste ambiente.
