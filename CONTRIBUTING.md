# Contribuindo

## Setup de desenvolvimento

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

## Comandos úteis

| Comando | Descrição |
|---------|-----------|
| `make test` | Roda testes com coverage (mín. 50%) |
| `make lint` | Verifica lint (Ruff) |
| `make format` | Formata código com Ruff |
| `make migrate` | Aplica migrações |
| `make run` | Inicia servidor de desenvolvimento |

## Padrões

- **Lint:** Ruff (config em `pyproject.toml`)
- **Testes:** pytest + pytest-django
- **Commits:** Preferir [Conventional Commits](https://www.conventionalcommits.org/) (feat:, fix:, docs:, etc.)

## CI

O GitHub Actions executa em todo push/PR:

1. **Lint** — Ruff check + format
2. **Testes** — pytest com coverage ≥ 50%
