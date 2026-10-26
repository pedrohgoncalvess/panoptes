# Investigar falhas do parser com HTML preservado

Cada página recebida é armazenada no bucket S3 antes da interpretação, usando
uma chave `html/<prefixo>/<sha256>`. A captura no banco associa arquivo, extração,
URLs, data, encoding, modo de acesso e resposta HTTP. O HTML não é removido quando
o parser falha; o mesmo conteúdo é reutilizado pelo hash, sem criar outra cópia.

Nas próximas falhas de leitura, o evento **HTML preservado para análise do leitor**
informa a etapa (busca ou produto), leitor e versão, causa e referências do
arquivo e da captura. Nos logs, **Baixar HTML** também está disponível em eventos
de páginas recebidas anteriormente, inclusive nas extrações já malsucedidas.
O download exige autenticação e usa uma URL S3 válida por cinco minutos, enviada
como arquivo anexado. O bucket permanece privado.

Para melhorar o parser em uma investigação posterior:

1. Filtre os logs pela extração que falhou e baixe a captura da página afetada.
2. Confira se ela contém resultados/produtos, uma tela de autenticação ou uma
   verificação do site. Uma resposta HTTP 200, por si só, não garante resultados.
3. Reproduza o erro offline com o leitor da fonte: `parse_search` usa HTML,
   identificador da captura e número da página; `parse_product` também precisa
   da URL final e do código do produto. Consulte a versão indicada no evento.
4. Ajuste os seletores e extração dos campos com base na captura. Prepare uma
   fixture mínima sem dados pessoais para os testes em `workers/parsers` e
   confirme que o novo leitor mantém os casos anteriores funcionando.

As capturas reais ficam no S3 para estudo; fixtures adicionadas ao repositório
devem conter apenas o HTML necessário para reproduzir o comportamento.
Esse histórico permite comparar capturas entre versões sem acessar o site
novamente durante o desenvolvimento do parser.

Uma captura do Mercado Livre mostrou que a busca foi redirecionada para
`/captcha/wall/logged`, com HTTP 200 e a mensagem “Por segurança, complete esta
etapa”. Esse conteúdo é uma verificação do site, não uma mudança nos resultados
de busca. O backend e o worker agora reconhecem essa tela e marcam a execução
como bloqueada, sem encaminhá-la ao parser. Nos logs, abra a busca no navegador
local, conclua o desafio e envie novamente a sessão pela extensão. A extensão
aceita a aba `lista.mercadolivre.com.br` após a conclusão, mas não exporta a tela
de CAPTCHA. O site pode solicitar uma nova verificação ao usar a sessão no Docker.

Uma captura posterior no navegador local trouxe resultados válidos, mas os
links da paginação estavam sem `href`. O parser convertia o valor ausente na
raiz de `lista.mercadolivre.com.br`, que redirecionava à página inicial. Agora
esse botão gera `pagination_url_unavailable`, encerra a descoberta como parcial
e preserva os produtos encontrados. Links vazios, desabilitados, externos ou
com credenciais não são seguidos. Avançar por paginação controlada exclusivamente
por JavaScript ainda exige integração com o navegador local.

Se um parser falhar em uma página posterior, o resumo conserva os resultados
anteriores e marca a execução parcial quando já houve produtos concluídos.
A captura que falhou continua preservada no S3 com seu diagnóstico.
