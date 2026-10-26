# Panoptes — Sessões

Extensão Manifest V3 para Chrome e Edge. Aproveita a sessão da aba atual do
Mercado Livre, Amazon Brasil, Pichau ou Terabyte, incluindo cookies HttpOnly. Não abre um novo
navegador e não exige refazer reconhecimento facial quando o site aceita a sessão.

## Instalação

1. Abra `chrome://extensions` ou `edge://extensions`.
2. Ative **Modo do desenvolvedor**.
3. Clique em **Carregar sem compactação** e selecione esta pasta:
   `extensions/session-bridge` (a pasta que contém `manifest.json`).
4. Fixe **Panoptes — Sessões** na barra do navegador.

Não é necessário instalar dependências ou compilar. Para atualizar, use o botão
**Recarregar** na página de extensões.

## Uso

1. Abra o Panoptes no mesmo perfil do navegador e entre como administrador.
2. Abra a página inicial da loja e conclua qualquer verificação pendente.
   Amazon e Mercado Livre exigem conta conectada no envio de sessão;
   Pichau e Terabyte permitem acesso público verificado.
3. Clique na extensão e informe o endereço do frontend Panoptes
   (por padrão `http://localhost:3000`). Escolha **Neste navegador** e clique em
   **Ativar coleta neste navegador**, ou escolha **Enviar sessão para o navegador
   do Docker** e clique em **Enviar sessão desta aba**.
4. Autorize o acesso ao endereço do Panoptes e mantenha o painel aberto durante
   a validação. Após o sucesso, a extensão abre e destaca a sessão na página
   **Conexões** do Panoptes, com estado, origem e data de salvamento.

O backend precisa ter `BROWSER_SESSION_KEY` configurada. Atualize backend e
frontend após adicionar esta integração:

```sh
docker compose up -d --build backend workers frontend
```

## Funcionamento e limites

- Só ativa após um clique explícito. No modo local, a extensão consulta tarefas
  do Panoptes em segundo plano e usa a aba selecionada para navegar e capturar
  HTML das fontes autorizadas. Não coleta senha, câmera ou histórico.
- Usa as credenciais HttpOnly existentes da aba Panoptes para uma requisição
  de mesma origem. Nenhuma senha ou token Panoptes é copiado para a extensão.
- A extensão salva endereço, identificador da conexão e IDs das abas. Cookies e
  armazenamento capturados para o Docker ficam em memória durante o envio.
  HTTPS é obrigatório fora de localhost.
- Importa cookies não particionados dos domínios de autenticação da
  fonte, localStorage e sessionStorage da origem da aba atual. IndexedDB, passkeys
  e outros perfis/abas não são exportados nesta versão. Cookies particionados
  são ignorados. Contas que dependem desses mecanismos podem precisar reconectar.
- Na importação para Docker, o backend valida os domínios e limites, testa a sessão em um contexto separado
  e só grava o estado criptografado depois de confirmar cookie de autenticação
  e página autenticada. Esse mesmo contexto é reutilizado nas coletas seguintes,
  conservando os dados produzidos durante a validação. Uma importação recusada
  preserva a conexão anterior.
- O site pode recusar a transferência para o Docker, exigir nova autenticação
  ou expirar a sessão. A importação não elimina verificações do site.
- Não atende navegação anônima. Fechar o painel durante o envio pode interrompê-lo;
  confira o estado no Panoptes antes de reenviar.
- Abas do Panoptes em uma página de erro do Chrome são recuperadas em Conexões
  antes da captura. Uma aba já carregada é preferida. Se o endereço não responder,
  o envio para antes de coletar a sessão e informa o endereço a verificar. Se a
  página de erro estiver na aba da loja, é necessário recarregar essa página.

## Verificação

```sh
cd extensions/session-bridge
npm test
```

APIs usadas: [cookies](https://developer.chrome.com/docs/extensions/reference/api/cookies)
e [scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting).

## Verificação durante a extração

Se os logs indicarem CAPTCHA, abra a busca que falhou no seu navegador local,
conclua o desafio e envie a sessão novamente pela extensão. Você pode enviar
diretamente da aba de resultados (`lista.mercadolivre.com.br`) ou de produto
(`produto.mercadolivre.com.br`). A tela de CAPTCHA não é aceita para envio.
Depois da atualização dos arquivos, recarregue a extensão em `chrome://extensions`
ou `edge://extensions` para usar a versão **0.3.0** e aceitar a nova permissão de alarmes.

## Coleta no navegador local

Este modo mantém cookies, IndexedDB e outros dados no perfil real do navegador;
sessionStorage é conservado ao reutilizar a aba selecionada, enquanto ela estiver
aberta. O Docker recebe apenas o HTML das páginas de busca e produto. Headers e
navegação são os normais do navegador, sem substituição de identidade.

Mantenha a aba selecionada disponível para as coletas e uma aba do Panoptes
autenticada no mesmo perfil. Evite usar a aba de coleta para outras atividades.
Se fechar a aba da fonte, a extensão poderá recriá-la, mas o sessionStorage
anterior não estará disponível. A aba Panoptes fechada ou deslogada torna a
conexão indisponível. Use **Conexões → Desconectar** para interromper a coleta.
Após reiniciar o backend, trocar de navegador ou substituir a conexão, ative
novamente pela extensão. Só uma extensão por fonte atende o workspace.

Uma captura espera até 55 segundos; páginas têm limite de 6 MB. Não há retorno
automático ao HTTP quando a conexão local fica indisponível. O HTML entra nos
mesmos parsers e capturas privadas no S3, com `capture_mode=browser_local` nos
logs. O status 200 representa uma captura de DOM bem-sucedida, não um status HTTP
medido (a API de scripting não fornece a resposta HTTP). Imagens continuam
usando o download HTTP dos workers.

Se houver CAPTCHA ou login, a extensão traz a aba para a frente, interrompe a
extração sem enviar o formulário e permite que você resolva a etapa normalmente,
inclusive reconhecimento facial com sua câmera. Depois, reexecute a extração;
não é preciso exportar cookies novamente neste modo. HTML comum pode incluir
personalização da conta e fica no armazenamento privado existente do Panoptes.
