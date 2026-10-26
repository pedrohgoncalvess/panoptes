# Frontend Panoptes

SvelteKit com servidor Node e proxy autenticado. O navegador usa /api na propria
origem; o endereco do backend e privado e resolvido no servidor em runtime.
Login, refresh e SSR usam a mesma configuracao.

## Desenvolvimento no Windows

Suba os servicos no WSL com `docker compose up --build -d`. No terminal Windows:

```powershell
cd frontend
npm ci
npm run dev
```

Abra a URL do Vite, normalmente http://localhost:5173. O Vite le o .env da raiz
do monorepo e depois o .env do frontend. Variaveis do terminal tem prioridade.
BACKEND_HOST (localhost) e BACKEND_PORT (8000) apontam para o backend publicado.
Alterar .env requer reiniciar o Vite. FRONTEND_DEV_PORT e independente da porta
Docker: ambos os frontends podem rodar juntos.

Se a configuracao WSL nao encaminhar localhost ao Windows, ajuste BACKEND_HOST
ou PANOPTES_API_URL para um endereco acessivel pelo Node do Windows. O acesso
continua dependendo da publicacao/encaminhamento de portas da sua maquina.

```powershell
$env:PANOPTES_API_URL = "http://localhost:8100"
npm run dev
```

## Docker no WSL

```sh
docker compose up --build -d
```

Abra http://localhost:3000 (FRONTEND_PORT no .env). O container usa
http://backend:8000 na rede Compose, independentemente de BACKEND_PORT.
Nao e necessario descobrir o IP do container. O Dockerfile usa build em etapas,
npm ci, adapter-node e usuario sem privilegios; executa o build de producao
com as rotas de servidor e cookies HttpOnly.

Precedencia no servidor: PANOPTES_API_URL, depois http://BACKEND_HOST:BACKEND_PORT.
Compose injeta a URL com DNS interno. Essas variaveis nao usam PUBLIC_ ou VITE_
e nao sao expostas ao navegador. O launcher usa HTTP para o acesso direto local;
FRONTEND_PROTOCOL=https permite indicar HTTPS quando necessario. Em um reverse
proxy, configure PROTOCOL_HEADER com o header sobrescrito pelo proxy e,
se necessario, HOST_HEADER. Verificacoes de origem permanecem ativas.

## Verificacao e build local

```sh
npm run check
npm run build
npm run test:config
npm run test:http
npm start
```

npm start executa o build Node (porta 3000 por padrao). Fora do Compose, exporte
BACKEND_HOST/BACKEND_PORT ou PANOPTES_API_URL no terminal. O build Node nao le
.env automaticamente. Depois do build, FRONTEND_TEST_RUNTIME=node permite
executar a suite HTTP contra o servidor de producao.
