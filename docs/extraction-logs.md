# Logs de extrações

A tela **Logs de extrações** (`/extraction-logs`) reúne o histórico persistido
e acompanha novas etapas por SSE. Na lista de extrações, **Ver logs** abre
o acompanhamento daquela execução. É possível filtrar fonte, execução e nível,
consultar eventos anteriores e voltar ao acompanhamento ao vivo.

Na tela **Extrações**, **Detalhes** abre um modal com termo de busca, categoria,
preço de referência, produto esperado, autores, marcas, ISBN, termos de categoria
e exclusão, características, observações, limites e intervalo de acompanhamento.
Também mostra o resultado e os critérios confirmados ou não confirmados de cada
produto, com acesso aos logs. O modal fecha pelo botão, por Escape ou pelo overlay
e devolve o foco ao botão de origem.

Os eventos aparecem em cartões com nomes de etapas em português, explicações
das falhas e campos legíveis, incluindo resposta do site, tentativas e duração.
Referências e localização de erros ficam em **Informações para suporte**, sem
exibir JSON na tela.

Nas falhas do parser, **Baixar HTML** permite consultar a captura já preservada
no S3. O evento identifica a página, a versão do leitor e a causa. Veja o
[guia de investigação](parser-investigation.md) para reproduzir e estudar falhas
offline e criar testes de regressão para melhorias futuras.

Os workers registram início, critérios e limites, uso de navegador ou HTTP,
tentativas, status e tamanho da resposta, identificadores da captura, interpretação
da busca e do produto, decisões de validação, imagens, resultado e duração.
Falhas incluem classe, códigos conhecidos (por exemplo,
`search_layout_not_recognized`), status HTTP quando disponível e localização
no código. Cookies, credenciais, conteúdo HTML, parâmetros de URLs e texto
arbitrário de exceções não entram nesses registros.

Os eventos ficam em `scraping.extraction_log`, criada pela migração
`20261005_07_extraction_logs`. Execuções anteriores recebem somente o resumo
que já existia; etapas detalhadas são registradas a partir da atualização.
Uma falha de gravação de log é reportada no stdout como
`log_persistence_failed` e não desfaz a extração.

## API autenticada

- `GET /extraction-logs`: últimos 200 eventos por padrão, em ordem crescente;
  aceita `request_id`, `site`, `level`, `before` e `limit` (até 500).
  Retorna `items`, `cursor` e `has_more`.
- `GET /extraction-logs/stream`: aceita os mesmos filtros e `after`.
  Cada quadro tem `event: log`, `id` e JSON em `data`.
  `Last-Event-ID` permite retomar após desconexão sem repetir eventos.

O frontend usa seu proxy de mesma origem e cookies HttpOnly do Panoptes.
O proxy encaminha os quadros sem esperar o término da resposta. A conexão
é renovada periodicamente para revalidar autenticação; consultas liberam a
sessão do banco entre leituras. Há heartbeat e reconexão automática.
Ao vivo, a tela mantém até 500 eventos; o restante continua no histórico.

No Docker Compose, atualize imagens e execute a migração antes dos workers:

```sh
docker compose up -d --build migrations backend workers frontend
```
