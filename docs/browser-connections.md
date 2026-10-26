# Conexões por navegador

## Pichau e Terabyte

As duas lojas estão em **Conexões** e na extensão (versão 0.4.0).
Usam Chromium com janela por padrão (`BROWSER_RETAIL_HEADLESS=false`),
com Xvfb no Docker. No Windows local, as janelas pertencem ao backend.
O modo sem janela recebeu desafios nos testes reais; o modo com janela coletou
as duas lojas sem login ou CAPTCHA manual.

A coleta pública confirma acesso à loja, sem declarar isso como login autenticado,
e reutiliza o contexto e seu estado criptografado. Se surgir verificação, a coleta
para sem armazenar o formulário. Clique em **Conectar**, conclua o desafio manualmente,
faça login somente se necessário e clique em **Usar esta sessão** para guardar o
acesso sem login. O overlay verifica periodicamente os sinais de conta conectada:
ao confirmar o login, salva a sessão criptografada e fecha automaticamente, inclusive
na página da conta. Acesso público sem login só fecha pelo botão de confirmação.
O botão aguarda o salvamento antes de fechar; falhas preservam o overlay e mostram
o motivo. Cliques repetidos ou simultâneos à confirmação automática são aceitos.
Alternativamente, use **Neste navegador** na extensão. Recarregue a extensão
para disponibilizar e autorizar as duas novas lojas.

Para repetir o teste pelo serviço real do backend e parsers do worker, sem banco:

```sh
uv run --all-packages python scripts/probe_browser.py --restart
```

Foram oito páginas HTTP 200: busca, RTX 3070, SSD e leitura após restaurar o
contexto nas duas lojas. Relatório: `artifacts/backend-browser-final/report.json`.
`--interactive` abre as janelas e aguarda confirmação no terminal quando o operador
precisar interagir. Os estados do diagnóstico são temporários e criptografados,
descartados ao terminar. As conexões do aplicativo conservam seu volume normal.
O sucesso observado não garante que as lojas aceitem todos os acessos futuros.

Para testar o modal sem contas reais, execute `frontend/tests/preview.mjs` com
`FRONTEND_TEST_RETAIL_BROWSER=1` e rode `tests/test_connections_ui.py` com
`RETAIL_UI_TEST_URL=http://127.0.0.1:5188`. O cenário valida confirmação manual,
login automático e erro de salvamento. `RUN_BROWSER_TESTS=1` habilita também
`tests/test_retail_login_dom.py`, com sinais de login e sessão criptografada em Chromium.

Para Mercado Livre que funciona no Chrome pessoal mas apresenta desafio no
Docker, use a extensão em **Neste navegador**. A aba selecionada recebe as
coletas, preservando o contexto real, e envia HTML ao fluxo existente de parsers,
logs e S3. Não transfere cookies nem perfil neste modo. Veja instalação, ativação
e limites em [session-bridge](../extensions/session-bridge/README.md).
Mantenha o navegador e a aba Panoptes autenticada abertos; após reiniciar o
backend, ative novamente. **Desconectar** interrompe as tarefas da conexão.

O administrador abre **Conexões** no painel, escolhe Amazon Brasil ou Mercado
Livre e faz login em um overlay com o fundo escurecido. Clique diretamente no
campo da página e use seu teclado e mouse: digitação, Tab, atalhos, colagem,
cliques, arrasto e rolagem são enviados em ordem ao navegador. Complete o segundo
fator ou as verificações do próprio site manualmente. O overlay salva a sessão e
fecha automaticamente apenas depois de confirmar cookies de autenticação válidos
e sinais de conta conectada na página. **Página inicial** só navega; não confirma
login. **Abrir login** permite voltar ao formulário. **Fechar** descarta a interação e conserva a sessão
anterior; **Desconectar** apaga a sessão local. Desconectar não revoga a sessão no
provedor: para isso use os controles de segurança da sua conta no site.

## Configuração

Execute `uv sync --all-packages`. Gere uma chave Fernet e um token interno:

Para configurar automaticamente sem exibir segredos, execute
`.venv\Scripts\python.exe scripts/configure_browser.py`. O comando preenche apenas
configurações ausentes/vazias no `.env`, conserva valores existentes e usa o DNS
do Compose. Use `--local` ao configurar processos fora do Docker. Para configurar
manualmente, use os comandos abaixo:

```powershell
.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Configure no `.env` (não versione os valores):

```dotenv
BROWSER_SESSION_KEY=<chave Fernet gerada>
BROWSER_SERVICE_TOKEN=<token aleatório gerado>
BROWSER_SERVICE_URL=http://backend:8000
```

Execute `docker compose up --build -d`. O backend instala Chromium e dependências
no build. O volume `browser_sessions` conserva o estado criptografado entre
reinicializações. Guarde a chave separadamente dos backups do volume. Trocar ou
perder a chave exige desconectar e conectar novamente todas as fontes.

Fora do Docker, instale o navegador com
`.venv\Scripts\python.exe -m playwright install chromium`. Configure
`BROWSER_SERVICE_URL=http://localhost:8000` para os workers e a mesma chave e token
no backend. `BROWSER_SESSION_DIR` pode definir o diretório privado de sessões;
o padrão é `.browser-sessions`. Os processos precisam receber as variáveis no
ambiente, como as demais configurações do backend/workers. Execute apenas **uma
instância/processo de backend**: o navegador e seus bloqueios ficam na memória
desse processo. Uma arquitetura com réplicas exigiria um serviço de navegador
separado com coordenação distribuída.
No Windows, execute Uvicorn sem `--reload`/múltiplos workers, para manter o loop
Proactor necessário aos subprocessos do Playwright.
O Mercado Livre usa Chromium com janela por padrão: o formulário respondeu
corretamente nesse modo nos testes, enquanto o headless recebia 403. No Windows,
a janela dedicada aparecerá no desktop do processo do backend. Dentro do Docker,
`python -m panoptes_backend.launch` cria uma tela virtual Xvfb privada; o usuário
continua interagindo pelo overlay. Em Linux fora do Docker, instale Xvfb e use o
mesmo comando ou forneça `DISPLAY` de uma sessão gráfica. O backend encerra a
tela virtual quando é desligado. Amazon continua usando seu navegador headless
separado. `BROWSER_MERCADO_LIVRE_HEADLESS=true` permite testar o modo headless,
mas pode reproduzir o erro 403.

## Comportamento e proteção

- A fila atual é compartilhada. Existe uma sessão por fonte para todo o workspace;
  apenas `admin@panoptes.com` pode operar ou visualizar o navegador. Não há seleção
  de contas por usuário ou rotina nesta versão.
- A interface espelha imagens do navegador; Mercado Livre usa modo com janela
  em uma tela virtual no Docker, e Amazon usa headless. Não usa iframe nem
  copia cookies do Chrome pessoal. O estado persistido contém cookies,
  localStorage e IndexedDB, criptografados com Fernet; nenhum perfil de navegador,
  gerenciador de senhas, trace, vídeo ou captura de login é salvo.
- Uma sessão salva é reconhecida por cookies de autenticação não expirados e
  sinais de conta conectada no DOM, fora das páginas de login/verificação/erro.
  O cookie anônimo `session-token` da Amazon não confirma login. Respostas HTTP
  de erro e falhas ao capturar a tela mantêm o overlay aberto. Isso não garante que o provedor aceite
  todas as próximas páginas. Os adaptadores podem precisar de atualização caso o
  provedor mude seu login.
- Sessões são segredos que permitem acesso à conta. Restrinja o volume e a chave,
  use HTTPS ao expor o painel fora da máquina e não publique o token interno.
  O endpoint interno exige `X-Browser-Service-Token` e não passa pelo proxy público
  do frontend. Entradas de texto são tratadas como segredos e não são registradas.
- O navegador permite apenas HTTPS dos domínios das fontes, seus assets e os
  domínios de CAPTCHA declarados em `browser/service.py`; downloads e service
  workers ficam desabilitados. Fluxos que precisem de outro domínio exigem revisar
  essa lista. O worker só pode solicitar páginas nos hosts de coleta cadastrados.
- A janela de login expira após 15 minutos. Enquanto estiver aberta, coletas daquela
  fonte terminam como `blocked` com causa `connection_in_progress`; a janela não
  é movimentada pelos workers. Cada fonte serializa navegação, interação e captura.
- Fontes desconectadas continuam usando HTTP. Fontes conectadas usam o mesmo
  contexto de navegador para busca e páginas de produto; os parsers continuam os
  mesmos e o snapshot registra `capture_mode=browser`. Imagens usam o HTTP existente.
- Login obrigatório, CAPTCHA, 403 e 429 interrompem a coleta e atualizam o estado
  da conexão. Não há tentativa de contornar esses desafios. Reconecte e solicite
  a coleta novamente; jobs bloqueados não são reenfileirados automaticamente.
  HTML de páginas de login/verificação detectadas não é enviado ao MinIO. HTML de
  produto autenticado pode conter personalização da conta e continua privado no
  armazenamento existente.
- A integração não garante redução de bloqueios. Login e coleta reais devem ser
  validados com a conta do operador em cada fonte.
- Os formulários brasileiros são abertos diretamente, com locale e
  `Accept-Language` em português. Uma página de erro em espanhol ainda pode ser
  enviada pelo Mercado Livre quando ele recusa o acesso; o aviso do overlay
  apresenta esse erro em português, sem tratar a navegação como autenticação.
  O login brasileiro usa `www.mercadolivre.com/jms/mlb/lgz/login` com retorno para
  `www.mercadolivre.com.br`; ambos os domínios são permitidos para a interação.
  O domínio de contas `.com` não é um host de coleta: os workers continuam
  limitados às páginas brasileiras cadastradas.
- Abas vazias ou popups que ainda não terminaram de carregar não substituem a
  página espelhada. Abas de login prontas são selecionadas e, ao fecharem, a tela
  volta à última página válida.
- O painel só começa a capturar imagens após a abertura ser confirmada. Falhas
  de inicialização preservam a mensagem original e oferecem **Tentar novamente**;
  uma conexão perdida interrompe as capturas, evitando repetir “Abra a conexão
  novamente”. O proxy permite até 60 segundos para abrir o navegador. Um processo
  de Chromium encerrado é recriado na próxima conexão.
- O container cria um diretório HOME gravável para o usuário do Chromium, usado
  também pelas configurações e pelo cache. Falhas de inicialização registram a
  exceção do Playwright nos logs do backend; a tela virtual registra o DISPLAY
  selecionado e seus erros de inicialização.

## Importação pela extensão

A extensão em [`extensions/session-bridge`](../extensions/session-bridge/README.md)
aproveita o login já realizado no Chrome ou Edge, incluindo a verificação facial
com a webcam local. O usuário instala a pasta pelo modo do desenvolvedor,
mantém o Panoptes aberto e autenticado como administrador no mesmo perfil e
envia a sessão pela aba do site. Cookies e localStorage são capturados somente
no clique, sem senha ou dados da câmera. O endereço Panoptes é a única preferência
persistida pela extensão.

`POST /browser-connections/{site}/import` recebe o estado via proxy autenticado,
valida os domínios e limites, verifica a autenticação em um contexto separado e
substitui o arquivo criptografado somente após confirmação. Em caso de recusa,
preserva a sessão anterior. Cookies particionados, IndexedDB e sessionStorage
não são exportados pela extensão nesta versão. O site ainda pode exigir login
ao transferir a sessão para o Docker.

## API

Rotas administrativas autenticadas em `/browser-connections`: `GET` lista estados,
`POST /{site}/connect` abre a janela, `GET /{site}/frame` retorna JPEG em base64 com
`Cache-Control: no-store` ou confirma autenticação e salva a sessão,
`POST /{site}/input` envia eventos (incluindo ponteiro e atalhos), `POST /{site}/save`
salva, `POST /{site}/cancel` fecha sem salvar e `DELETE /{site}` desconecta.
O worker usa `POST /internal/browser/fetch` com seu token separado; esse endpoint
retorna HTML apenas quando a navegação não exige interação humana.
