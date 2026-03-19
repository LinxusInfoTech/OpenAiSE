# Contributing to OpenAiSE

Thanks for your interest in contributing. Here's how to get involved.

## Ways to contribute

- Report bugs via GitHub Issues
- Request features via GitHub Issues (use the Feature Request template)
- Submit pull requests for bug fixes or new features
- Improve documentation
- Fork and build your own version — the Apache 2.0 license allows this freely

## Getting started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/<your-username>/OpenAiSE.git`
3. Create a branch: `git checkout -b feat/your-feature` or `fix/your-bug`
4. Run the install script: `sudo bash install.sh`
5. Make your changes and add tests where applicable
6. Run the test suite: `poetry run pytest`
7. Push your branch and open a Pull Request against `main`

## Pull Request guidelines

- PRs must target the `main` branch
- All CI checks must pass before review
- Merging into `main` requires approval from the repository owner
- Keep PRs focused — one feature or fix per PR
- Include a clear description of what changed and why

## Issue guidelines

- Search existing issues before opening a new one
- Use the provided templates for bugs and feature requests
- Include steps to reproduce for bug reports
- Be specific about the expected vs actual behaviour

## Code style

- Python 3.11+, formatted with `black` (line length 100)
- Linted with `ruff`
- Type-checked with `mypy`
- Run all three before submitting: `poetry run black . && poetry run ruff check . && poetry run mypy aise/`

## License

By contributing, you agree your contributions will be licensed under the Apache License 2.0.
