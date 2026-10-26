# Panoptes backend

A aplicacao async esta em `src/panoptes_backend`.

Instalacao, Compose, migrations e testes sao gerenciados na raiz do monorepo.
Consulte [README](../README.md) e [contrato de extracao](../docs/extraction-contract.md).
Execute `uv sync --all-packages` a partir da raiz; o lockfile oficial e `../uv.lock`.

Os modulos antigos `agents_module`, `openrouter_module`, `log` e `utils`,
o Makefile e `backend/uv.lock` sao legados preservados. Nao sao usados pelos
servicos novos. As migrations foram transferidas para `../migrations/sql`.
