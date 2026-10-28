# Investigação das extrações — 28/10/2026

Consulta por SSH dos containers, logs dos workers, auditoria de IA e uma
captura existente no S3. O servidor foi acessado somente para leitura.
As correções estão no checkout de desenvolvimento; não houve deploy,
reprocessamento de extrações nem alteração das sessões ou do banco de produção.

## Evidências

Os logs disponíveis cobrem 26/10 às 13:57 até 28/10 às 09:58,
no fuso America/Sao_Paulo. Das 2.226 execuções finalizadas:

| Resultado | Quantidade |
| --- | ---: |
| Concluídas | 1.112 |
| Bloqueadas | 1.064 |
| Falhas | 46 |
| Parciais | 4 |

- **Sessões bloqueadas gerando execuções repetidas:** 478 bloqueios da Amazon,
  311 da Terabyte e 275 da Pichau. As três sessões persistidas estão em
  `verification_required`. O backend recusa novas leituras nesse estado sem
  navegar, mas o agendador continuava criando coletas para esses sites.
  Portanto, os números representam execuções recusadas, não 1.064 novos CAPTCHAs.
- **Limitação do provedor de IA:** 43 execuções falharam com
  `classifier_rate_limited`; extrações parciais também tiveram produtos afetados.
  A auditoria das últimas 48 horas confirmou HTTP 429 do pool compartilhado do
  Google AI Studio para `google/gemini-2.5-flash-lite`, inclusive em normalização,
  taxonomia e comércio. As tentativas já existiam, mas esperavam somente 2 e
  4 segundos quando não havia Retry-After numérico.
- **Comunicação com o navegador:** duas execuções (Terabyte e KaBuM) falharam
  com `httpx.ReadError` no POST interno ao backend, sem nova tentativa.
- **Mercado Livre:** uma execução recebeu HTTP 200, mas o HTML preservado
  mostrava uma tela intermediária com botão `continue-button`, classe
  `micro-landing-button` e aviso de dependência de JavaScript. Não havia
  resultados. Isso foi registrado incorretamente como
  `search_layout_not_recognized`.
- **Resposta inválida da IA:** a auditoria também mostrou uma citação de
  descrição inteira excedendo os 1.000 caracteres permitidos no classificador.
  A validação local rejeitou a resposta corretamente.

## Mudanças em desenvolvimento

- Endpoint interno autenticado `/internal/browser/availability`, que retorna
  apenas estados de conexão, sem cookies ou conteúdo de sessão.
- Agendamento de descoberta e atualização filtra fontes cuja sessão exige
  intervenção ou cujo navegador local está indisponível. Os horários continuam
  avançando; as fontes voltam a participar nos próximos horários após recuperar
  a conexão. Produtos e acompanhamentos permanecem habilitados. Pedidos manuais
  e execuções que já estavam na fila preservam o comportamento anterior.
- Se a consulta de disponibilidade falhar, o agendador mantém os horários
  pendentes para consultar novamente, sem criar uma nova leva às cegas.
- Cliente do navegador tenta até três vezes para falhas de rede, timeout,
  protocolo remoto e HTTP 502/503/504, com pausas de 2 e 4 segundos. Bloqueios
  e erros permanentes não são repetidos automaticamente.
- HTTP 429 da IA agora espera 10 e 30 segundos, mantendo três tentativas,
  auditoria individual e tratamento de Retry-After numérico limitado a 30 segundos.
  Isso pode recuperar limites temporários; não garante disponibilidade do provedor.
- A tela intermediária do Mercado Livre é reconhecida como verificação antes
  do parser, tanto no backend como no worker.
- O prompt pede citações literais curtas de até 1.000 caracteres. A validação
  local continua obrigatória; a mudança de prompt não garante respostas válidas.

## Validação e operação

281 testes passaram e dois de integração foram ignorados.
A cobertura inclui autenticação do endpoint interno, reconexão, filtragem das
duas modalidades de agendamento, falhas temporárias, bloqueios e schemas da IA.
Ruff passou nos arquivos alterados.

Os SELECTs de atualização foram extraídos do código novo e executados numa
transação explicitamente somente de leitura no PostgreSQL do servidor. Nas
cinco rotinas existentes, o filtro preservou 13 dos 51 alvos e excluiu os 38
das três fontes bloqueadas. Excluir todas as fontes produziu zero candidatos.
Não foram inseridas execuções durante essa validação.

Para ativar, backend e workers precisam ser atualizados juntos, e o registro de
agentes precisa sincronizar o prompt (`python -m panoptes_ai.sync agents`).
As sessões de Amazon, Pichau e Terabyte ainda precisam ser recuperadas pela
tela de conexões. O código não resolve nem contorna os desafios dos sites.
Não foram feitas novas chamadas ao provedor de IA nesta investigação.
