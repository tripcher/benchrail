# Contributing

Contributions are welcome through GitHub pull requests.

## Development

Install dependencies:

```bash
uv sync --dev
```

Run the focused tests for your change, then run the full local checks:

```bash
make unit
make lint
```

## Pull requests

- Open pull requests against `main`; direct pushes to `main` are blocked.
- Keep changes focused and add the narrowest tests that prove behavior changes.
- Update documentation when user-facing behavior changes.
- Never include secrets, credentials, authentication files, or machine-specific absolute paths.

Only the repository owner merges pull requests and creates release tags.

## Releases

Releases are published from protected semantic-version tags matching `vMAJOR.MINOR.PATCH`.
Release tags are created by the repository owner after the corresponding change has merged to
`main`.
