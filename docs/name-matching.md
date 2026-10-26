# Comparação de títulos e autores

Títulos e autores usam similaridade de Levenshtein normalizada por palavra,
após remover acentos, pontuação e diferenças de maiúsculas. O resultado varia
de 0 a 1. Cada palavra solicitada precisa alcançar o limite: 0,85 para títulos
e 0,80 para autores. A pontuação final é a menor entre as palavras solicitadas,
para que uma palavra igual não esconda outra incompatível.

Palavras com menos de cinco caracteres e palavras contendo números precisam
coincidir exatamente. Isso protege títulos curtos e números de modelos.
Em produto exato, as palavras devem aparecer no início e na mesma ordem;
complementos posteriores são permitidos. No perfil, podem aparecer em qualquer
ordem, com palavras adicionais, sem reutilizar uma palavra do anúncio.

Um sobrenome isolado pode corresponder à última palavra do nome completo.
Assim, Dostoievsky aceita Fiódor Dostoiévski e Fyodor Dostoevsky. Quando o usuário
informa o nome completo, todas as palavras precisam corresponder. As listas de
autores continuam exigindo ao menos um autor compatível. Nomes ausentes continuam
inconclusivos; ISBN, categoria e demais critérios mantêm suas validações.

As avaliações de perfil registram a similaridade e o limite na evidência.
As versões são product_name_match/1.1.0 e product_qualification/1.1.0.
As regras se aplicam às próximas execuções; avaliações anteriores permanecem
como histórico. Similaridade de texto não garante identidade: sobrenomes iguais
ou grafias muito próximas ainda podem representar pessoas diferentes.
