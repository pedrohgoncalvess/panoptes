# Investigação das falhas de extração — 26/10/2026

Foram consultados os eventos persistidos em `scraping.extraction_log`, os
resumos de `scraping.scrape_request` e a auditoria `ai.interaction`, desde
25/10/2026 no fuso America/Sao_Paulo. O histórico não foi reescrito.

## Causas confirmadas

- Produtos antigos incompatíveis continuavam habilitados nas rotinas de
  atualização. A busca por Ryzen 7 incluía 13 kits da Pichau, e Ryzen 5 incluía
  dois notebooks da KaBuM. As rejeições eram corretas, mas se repetiam a cada
  hora. No último levantamento antes da correção havia 195 falhas com
  `product_type_mismatch`, além de 11 rejeições antigas com `intent_classified`.
- O provedor Google AI Studio, acessado pelo OpenRouter com
  `google/gemini-2.5-flash-lite`, respondeu HTTP 429. Vinte das 25 execuções com
  `classifier_failed` tinham esse erro na auditoria. Não havia tentativa
  automática para esse retorno.
- Cinco falhas antigas de classificação envolveram respostas redundantes:
  checagens repetidas ou uma descrição que não havia sido solicitada. A
  normalização desses casos já existia no código encontrado e foi coberta
  novamente pela regressão, mantendo rejeição de contradições e citações falsas.
- Os agentes `commerce` e `taxonomy_normalizer` recebiam HTTP 400 com a mensagem
  `The specified schema produces a constraint that has too many states for
  serving`. Os limites de strings e arrays, combinados com estruturas aninhadas,
  tornavam a gramática de saída complexa demais para o provedor. Essas falhas de
  enriquecimento também podiam ocorrer em extrações com status concluído.

## Correções aplicadas

- Atualizações rejeitadas especificamente por `product_type_mismatch` suspendem
  o acompanhamento na mesma transação que finaliza a execução. Falhas incertas
  ou temporárias mantêm o acompanhamento habilitado.
- Foram suspensos os 15 acompanhamentos identificados acima, preservando
  produtos, observações e histórico, com evento `tracking_paused` por produto.
  O estado anterior foi salvo em
  `artifacts/extraction-tracking-paused-20261026.json`.
- O gateway de IA tenta até três vezes em HTTP 429, 502, 503 e 504, com espera
  progressiva e respeito ao Retry-After numérico limitado a 30 segundos. Cada
  tentativa tem sua própria auditoria. Erros permanentes, respostas inválidas
  e cancelamentos não são repetidos.
- Os logs distinguem limite de requisições da IA, indisponibilidade do provedor
  e resposta de classificação inválida.
- Para Gemini, o schema enviado conserva tipos, campos obrigatórios, enums,
  referências e proibição de campos extras; limites e formatos complexos são
  aplicados pela validação local completa antes de aceitar a resposta.

## Validação e limites

142 testes passaram, um teste de integração foi ignorado. A suíte inclui
gateway, classificador, workflow, agendamento, comércio e taxonomia. O build
Docker do worker e frontend terminou com sucesso e as imagens foram ativadas.

A revisão automática bloqueou o teste externo que reenviaria duas entradas
históricas ao provedor, por exigir autorização específica para esse envio.
Portanto, a eliminação do HTTP 400 foi validada localmente com os schemas reais
e respostas simuladas, sem confirmação externa nessa investigação. As novas
tentativas reduzem falhas temporárias, mas não garantem disponibilidade caso
o provedor mantenha a limitação. Execuções antigas continuam registradas como
ocorreram; não foram repetidas em massa.
