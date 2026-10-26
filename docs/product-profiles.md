# Extração por busca e descrição

Novas extrações exigem apenas o termo de busca e uma ou mais fontes. O formulário
oferece uma checkbox de liga/desliga por fonte, descrição opcional de até 1000
caracteres, preço de referência opcional e limites de páginas e candidatos.
Categoria, título obrigatório, marcas, autores, características e observações
não fazem parte do novo formulário. As extrações antigas preservam seus critérios.

## Mapeamento e classificação

O termo é usado sem acréscimos para montar a busca da loja. Os cartões descobrem
candidatos; não decidem a seleção. Cada candidato dentro do limite configurado tem
sua página capturada e interpretada. O classificador compara os campos extraídos
(título, descrição, marca, modelo e especificações) com a busca e a descrição do
usuário. Não recebe HTML inteiro, dados de sessão ou preços para decidir identidade.

A classificação registra aceito, rejeitado ou inconclusivo e evidências por requisito.
O termo 'Ryzen 7' permite modelos diferentes da família; a descrição 'processador
avulso da linha 3d' restringe o resultado a processadores avulsos X3D, sem exigir
literalmente a palavra processador no título. Kits e acessórios não substituem o
produto principal. Descrições são restrições de seleção, não observações informativas.

O agente `product_classifier` usa a infraestrutura existente do OpenRouter com
structured output, auditoria e custos. `OPENROUTER_API_KEY` e
`PRODUCT_CLASSIFIER_ENABLED=true` habilitam a interpretação semântica. Nome completo
idêntico ao pedido, sem descrição adicional, pode ser confirmado por regra. Nos demais
casos, se o classificador estiver desabilitado, falhar ou citar evidência inexistente,
o resultado permanece inconclusivo e não vira observação aprovada. Não há aprovação
silenciosa de uma descrição que não foi avaliada. Evidências matched/mismatch precisam
ser citações literais dos campos enviados. A decisão final é derivada das checagens;
missing nunca conta como matched.

Preços continuam sendo extraídos pelos parsers. O preço informado é referência de
comparação, sem excluir ofertas acima dele. Ausência de preço não é incompatibilidade
de identidade. Limites de candidatos contam páginas de produtos analisadas no novo
modo: todos os cartões seguem para detalhe dentro desse orçamento. Ao atingir o
limite, o resumo mostra que a busca foi truncada.

## API

`POST /search-terms` aceita o formato simplificado:

```json
{
  "site": "amazon_br",
  "term": "Ryzen 7",
  "description": "processador avulso da linha 3d",
  "reference_price": "1500.00",
  "max_pages": 2,
  "max_candidates": 20
}
```

O backend congela busca, descrição e referência em `criteria` com `match_mode=intent`.
O payload legado com `criteria` continua aceito. Não exige consulta ao cadastro de
categorias para o modo novo. `POST /search-terms/{id}/discover-sources` aceita
`{"sites":["amazon_br","kabum_br","terabyte_br"]}`. A interface envia somente as fontes
marcadas, validando pelo menos uma seleção.

## Agendamento

A primeira extração apenas mapeia e salva os produtos confirmados. O worker não
enfileira mais atualizações pelo intervalo implícito de 24 horas dos targets.
Repetições devem ser configuradas em Rotinas, por descoberta ou atualização direta.
Targets e intervalos antigos permanecem armazenados por compatibilidade e para a
atualização manual, sem criar um agendamento. As rotinas explícitas existentes
continuam funcionando. Não é necessária migration.

## Compatibilidade com perfis anteriores

### Histórico do modo profile

Buscas legadas usam `match_mode: profile`. Categoria e termo de busca bastam para iniciar
uma extração. Título, autores, marcas, características e preço de referência são opcionais.
O formulário permite categoria, autores, marcas, palavras do produto/modelo,
preço de referência em BRL e características
com nome, valor, unidade e comparação (`eq`, `gte`, `lte`, `contains`). Observações
servem como contexto; requisitos obrigatórios devem estar nas características.
O preço informado é uma referência do usuário, não uma média de mercado calculada
e não um limite que exclui ofertas. Analytics mostra a diferença para cada oferta.

## Categorias

`GET /categories` lista categorias ativas. Administradores podem listar e criar/editar
por `GET /admin/categories` e `PUT /admin/categories/{slug}`. A autorização é conferida
no backend pelo papel do usuário; a navegação também oculta a página para usuários comuns.
Categorias iniciais: livros, eletrodomésticos, eletrônicos, hardware, material escolar e outros.
Palavras de reconhecimento identificam a categoria no título ou na categoria informada
pelo site. Características sugeridas preenchem o formulário; qualquer outra pode ser adicionada.
Desativar preserva o histórico e as buscas existentes.

O nome e as palavras da categoria são congelados no JSONB de critérios da busca.
Novas definições só afetam novas buscas. O mesmo termo pode ter configurações distintas.
O índice de configuração usa `md5(criteria::text)` para agrupar fontes com critérios iguais;
este hash é uma chave de configuração, não um mecanismo de segurança.

## Seleção no primeiro scrape

O qualificador determinístico verifica palavras do produto sem exigir a ordem do título,
marca, autores e cada característica com evidência extraída das especificações.
Títulos e autores toleram pequenas diferenças de grafia por pontuação de
similaridade; veja [comparação de nomes](name-matching.md). A avaliação registra
o resultado e o limite usado, incluindo correspondência por sobrenome.
Unidades compatíveis são convertidas: litros/mililitros, TB/GB/MB, GB/s/MB/s etc.
Capacidade de armazenamento e velocidade são dimensões distintas. Unidades ausentes,
faixas e alternativas ambíguas não confirmam requisitos numéricos.

Uma diferença comprovada rejeita o produto. Informação insuficiente deixa a seleção
incerta e não ativa seu acompanhamento. Apenas produtos confirmados passam à persistência
e à associação de produtos. Repetições dependem de Rotinas. A avaliação e as evidências ficam em
`scraping.search_candidate.detail_validation` e `scraping.product_validation.validation`.
`GET /scrape-requests/{id}/qualifications` alimenta a seção “Seleção de produtos” no frontend.
As coletas e capturas de HTML mantêm o fluxo de armazenamento existente.

O qualificador não chama um modelo para inventar especificações faltantes. O fallback
OpenRouter existente continua dedicado à extração comercial com structured output e evidência.
Buscas antigas continuam usando seus modos de validação originais.

## Migração

`20261006_09_product_profiles` adiciona papéis de usuário, categorias configuráveis,
índice de critérios e chave de configuração. O administrador inicial recebe `role=admin`;
outros usuários recebem `role=user`. Não há mudança de credenciais.
O rollback da chave exige que não existam múltiplas configurações para o mesmo termo/fonte,
porque a restrição anterior não as suporta; não elimina registros para resolver conflitos.

Aplicação via Compose: construir `migrations backend workers frontend`, executar
`docker compose run --rm --no-deps migrations` e recriar backend, workers e frontend.
