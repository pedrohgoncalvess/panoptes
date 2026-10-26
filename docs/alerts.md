# Alertas por webhook

A página **Alertas** (`/alerts`) cadastra destinos HTTP(S), cada um com nome,
estado ativo/pausado e regras independentes por evento e rotina. Usa os componentes,
cores e navegação compartilhados da aplicação. O formulário permite combinar
várias regras e o histórico mostra entregas, tentativas e respostas HTTP.

Em **Modelos dos eventos**, selecione um dos seis eventos e clique em **Baixar
modelo .json**. Cada arquivo contém um exemplo completo do corpo enviado pelo
webhook, incluindo `data` e `matched_rules`, com dados fictícios. O download está
disponível mesmo sem cadastrar um destino e não dispara nenhum envio.

## Eventos e escopo

| Evento | Configuração | Disparo |
| --- | --- | --- |
| `extraction_started` | Rotinas | Quando um worker assume uma solicitação |
| `extraction_finished` | Rotinas | Encerramento em qualquer estado terminal |
| `extraction_error` | Rotinas | Encerramento `failed`, `blocked` ou `partial` |
| `price_threshold` | `threshold`, `direction`, `currency` | Ao entrar em preço ≤ limite (`below`) ou ≥ limite (`above`), inclusive a primeira observação conhecida |
| `price_drop` | `percent`, `currency` | Queda percentual mínima em relação ao preço anterior |
| `price_increase` | `percent`, `currency` | Aumento percentual mínimo em relação ao preço anterior |

Cada regra tem `routine_ids`: lista vazia abrange todas as extrações, incluindo as
manuais. Uma lista de UUIDs restringe à rotina agendada que originou a solicitação.
Uma execução é por fonte em descoberta e por produto em atualização. Solicitações
já ativas podem impedir outro agendamento do mesmo termo/produto; nesse caso, a
origem permanece a rotina que efetivamente criou a solicitação.

Regras de preço aceitam `entity_id` opcional para um anúncio específico. Comparações
usam a mesma oferta/vendedor e moeda, sem somar frete ou aplicar cupons/parcelamento.
Preços desconhecidos são ignorados. Variação exige preço anterior positivo; 10
significa 10%. Permanecer na faixa nominal não dispara novamente: o preço precisa
sair da faixa e entrar de novo. Capturas antigas recebidas após uma mais recente
não geram alertas de preço.

## Configurar pelo MCP

O [guia MCP](mcp.md) também é publicado em `panoptes://guide` e por
`get_usage_guide()`. Os schemas reais estão em
`get_usage_guide(tool_name="create_webhook")`.

1. Consulte `list_routines` e, se necessário, `search_products`. Use os UUIDs reais
   retornados; `entity_id` é o `public_id` do anúncio, não o produto canônico.
2. Consulte `list_webhooks` para verificar destinos existentes.
3. Use `create_webhook` com `value` no formato abaixo. A lista vazia neste exemplo
   escolhe explicitamente todas as extrações.

```json
{
  "value": {
    "name": "Monitoramento de preços",
    "url": "https://seu-destino.example/eventos",
    "enabled": true,
    "rules": [
      { "event": "extraction_error", "routine_ids": [] },
      { "event": "price_drop", "routine_ids": [], "currency": "BRL", "percent": "10" },
      { "event": "price_threshold", "routine_ids": [], "currency": "BRL", "direction": "below", "threshold": "2500.00" }
    ]
  }
}
```

4. Para editar ou pausar, leia `get_webhook`, preserve nome/endereço/regras e envie
   a configuração completa em `update_webhook`; pause com `enabled=false`.
   Não envie `public_id`, `created_at` ou `updated_at` dentro de `value`.
5. Consulte `list_webhook_deliveries` para acompanhar resultados. Cadastros e
   histórico paginam com `limit` (1..100) e `offset`; uma página menor encerra a lista.
6. `delete_webhook` remove destino e histórico quando solicitado.

Os mesmos recursos estão na API autenticada: `GET/POST /alerts/webhooks`,
`GET/PUT/DELETE /alerts/webhooks/{webhook_id}` e
`GET /alerts/webhooks/{webhook_id}/deliveries`.

## Recebimento e operação

O destino recebe POST JSON com `id`, `version=1`, `event`, `occurred_at`,
`routine_id`, `data` e `matched_rules`. Os cabeçalhos `X-Panoptes-Event` e
`X-Panoptes-Delivery` identificam evento e entrega. O `id` permanece igual nas
novas tentativas: o destino deve deduplicá-lo e responder HTTP 2xx quando aceitar.
Várias regras correspondentes ao mesmo evento geram uma entrega por destino;
eventos diferentes geram entregas separadas.

Eventos e envios são gravados na mesma transação dos dados da extração. A fila
persiste após reinícios. O backend despacha os eventos sem bloquear o worker,
com timeout total de 15 segundos por envio e até cinco tentativas, separadas por
30, 60, 120 e 240 segundos. Não há garantia de ordem e pode haver reentrega se o
destino aceitar uma chamada cuja resposta se perder. Os estados são `pending`,
`delivered`, `failed` e `cancelled`. O corpo da resposta do destino não é armazenado.

Editar ou pausar cancela envios pendentes. Uma entrega que já começou pode
concluir antes da alteração. Ativar novamente não reproduz eventos antigos.

Antes de executar a versão nova, aplique a migração
`20261024_16_alerts` e reinicie backend/workers. No Compose, execute o serviço de
migrações e reconstrua os serviços usando o fluxo de instalação do README.
O backend precisa permanecer ativo para despachar a fila.

Destinos privados/localhost são bloqueados por padrão, inclusive em respostas DNS
mistas. Não há redirecionamentos e o endereço resolvido é fixado por tentativa.
Para receptores internos em uma instalação confiável, configure
`WEBHOOK_ALLOW_PRIVATE_NETWORKS=true` no ambiente do backend e reinicie-o.

## Validação

```powershell
uv run --all-packages pytest tests/test_alerts.py tests/test_mcp.py tests/test_mcp_documentation.py tests/test_pricing.py tests/test_schedules.py -q
```

`tests/test_alerts_persistence.py` usa `TEST_ALERTS_DATABASE_URL` apontando para
um PostgreSQL **vazio e descartável**. Testa a migração real com tabelas de origem
de fixture e reverte todas as alterações. `tests/test_alerts_ui.py` usa
`ALERTS_UI_TEST_URL` com o frontend de fixture (`frontend/tests/preview.mjs`),
permitindo validar os fluxos desktop/mobile sem scraping ou envios externos.
