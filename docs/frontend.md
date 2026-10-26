# Frontend Panoptes

Svelte 5 + SvelteKit 3. A identidade usa azul mineral, superfícies claras e o olhar
de Argos como referência discreta. Sem neon, brilhos ou gradientes decorativos.

## Executar

Com a API e os serviços do Compose ativos:

```sh
cd frontend
npm install
npm run dev
```

O servidor usa `PANOPTES_API_URL` ou `http://BACKEND_HOST:BACKEND_PORT`, com
defaults localhost e 8000. O Vite le o `.env` da raiz e do frontend; Compose
injeta `http://backend:8000`. Veja [Windows e Docker](../frontend/README.md).
O navegador
acessa `/api` na mesma origem; não precisa de CORS nem recebe os JWTs no JSON.
O administrador local existente é `admin@panoptes.com`, senha `admin`.

## Telas e operações

- `/`: login com e-mail e senha; sessões válidas vão ao dashboard.
- `/login`: redireciona para `/`.
- `/administrator`: dropdown de configurações; a rota redireciona para `/administrator/categories`.
- `/administrator/categories`: categorias e sugestões para novas extrações (administradores).
- `/administrator/taxonomy`: classificação de produtos, subcategorias e ajustes manuais (administradores).
- `/administrator/mcp-keys`: emissão e revogação de chaves MCP, com expiração e permissões por rotina e marketplace.
- `/mcp-keys`: redireciona para `/administrator/mcp-keys`, preservando links antigos.
- `/dashboard`: indicadores, atividade diária e últimas extrações.
- `/analytics/extractions`: análise operacional, períodos de 7, 14 e 30 dias.
- `/analytics/prices`: produtos por termo, fotos, ofertas, variação, menor preço histórico, cupons, pagamento e frete. `/analytics` redireciona para extrações.
- `/routines`: criar, editar, pausar, ativar e remover agendas; horários fixos,
  intervalo ou distribuição diária, com fuso IANA.
- `/extractions`: cadastrar termos de produto, iniciar descoberta, filtrar,
  paginar, consultar resumo e repetir execuções encerradas. Atualiza a cada
  3 segundos enquanto a aba está visível.
- `/data`: tabelas dos resultados e histórico por página, filtros e ações para
  interromper coletas ou excluir os dados vinculados. Veja [Dados](data-management.md).
- Alertas: apenas o item desabilitado na sidebar, identificado como “Em breve”.

As telas usam os endpoints existentes de autenticação, termos e rotinas.
Novos endpoints protegidos:

| Endpoint | Resposta |
| --- | --- |
| `GET /analytics?days=7` | Totais e série diária, incluindo dias sem atividade; `days` entre 1 e 90 |
| `GET /scrape-requests?status=failed&limit=25&offset=0` | Extrações com origem, resumo, status e total filtrado |

A série diária usa dias de calendário UTC. Produtos e rotinas ativas são totais
globais; extrações, conclusão, falhas e andamento respeitam o período escolhido.
A aba Dados requer a migration `20261019_12_data_management`.

## Sessão

Access e refresh ficam em cookies HttpOnly, SameSite Strict e Secure sob HTTPS.
Quando o access está ausente ou a API retorna 401, o servidor renova a sessão,
salva o par rotacionado e repete a chamada uma vez. Refresh inválido limpa os
cookies e retorna para o login. Erros temporários da API preservam a sessão.
Logout revoga a sessão no backend e remove os cookies. As mutações exigem a
origem do próprio frontend; o proxy aceita somente as rotas usadas pela UI.

Chamadas simultâneas compartilham a renovação, com cache curto do par resultante
para requisições que ainda carregam o cookie anterior. Esse compartilhamento é
por processo; múltiplas instâncias do frontend exigem afinidade de sessão ou
coordenação compartilhada para refresh.

## Componentes e tokens

`frontend/src/lib/styles/tokens.css` centraliza cores, espaçamento, raios,
sombras e duração/easing. `Button`, `Input`, `Select`, `Status`, `Notice`, `Icon`
e `Brand` são componentes reutilizáveis. Estados de foco, hover, disabled,
carregamento e feedback são consistentes. `prefers-reduced-motion` desativa
transições; a sidebar móvel suporta Escape e fica inerte quando fechada.

## Validar

```sh
cd frontend
npm run check
npm run lint
npm run build
npm run test:http
```

Os testes HTTP do frontend iniciam uma API de fixture local e o Vite, validando
cookies, redirecionamento, refresh concorrente, refresh expirado, logout, falha
temporária e proteção de origem. Não alteram dados reais. Para revisão visual
offline, `node tests/preview.mjs` disponibiliza fixtures na porta 5188.

No backend, `pytest` cobre rotas protegidas sem credenciais, JWT malformado,
assinatura incorreta, token expirado, refresh usado como access e sessões
revogadas, inativas, expiradas ou de outro usuário, além dos parâmetros das
novas rotas. Testes PostgreSQL/MinIO continuam opt-in conforme o README.

A nova extração cadastra uma busca. Reexecução abre o histórico paginado e aparece quando existe ao menos uma extração; execuções em andamento não podem ser reenviadas. A consulta autenticada `GET /analytics/prices?term_id=<uuid>&limit=24&offset=0` pagina todos os produtos associados ao termo e mostra ofertas da última coleta, com histórico das 30 observações recentes. Menor preço e variação são calculados por oferta e moeda, sem aplicar cupons automaticamente.
