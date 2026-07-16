# Contributing to OpenAgora

Thank you for your interest in contributing to OpenAgora! 🎉

This document will help you get started. Whether you are fixing a typo, adding a feature, or integrating a new sandbox provider, we are excited to have you on board.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Environment](#development-environment)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)
- [Review Process](#review-process)
- [Questions?](#questions)

---

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By contributing, you agree to uphold this code. Please report unacceptable behavior to the maintainers.

---

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/OpenAgora.git
   cd OpenAgora
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feature/my-awesome-feature
   # or
   git checkout -b fix/issue-description
   ```
4. **Set up your development environment** (see below).
5. **Make your changes**, add tests, and ensure everything passes.
6. **Push to your fork** and open a Pull Request.

---

## How Can I Contribute?

### Reporting Bugs

Before opening a bug report, please search [existing issues](https://github.com/albert-lv/OpenAgora/issues) to avoid duplicates.

When reporting a bug, include:

- A clear, descriptive title
- Steps to reproduce the problem
- Expected behavior vs. actual behavior
- Your environment (OS, Go version, Python version, Docker version)
- Relevant logs or error messages
- Minimal reproduction case if possible

Use the [Bug Report template](https://github.com/albert-lv/OpenAgora/issues/new?template=bug_report.md) when opening an issue.

### Suggesting Features

We welcome feature suggestions! When proposing a new feature:

- Explain the use case and the problem it solves
- Describe how it fits into Arena's four-plane architecture
- Mention any alternatives you have considered

Use the [Feature Request template](https://github.com/albert-lv/OpenAgora/issues/new?template=feature_request.md).

### Contributing Code

- Look for issues labeled `good first issue` or `help wanted` for beginner-friendly tasks.
- For larger changes, please open an issue first to discuss the design.
- Keep changes focused. A Pull Request should ideally address a single concern.
- Add tests for new functionality and update documentation as needed.

### Improving Documentation

Documentation improvements are some of the highest-impact contributions. If you find something unclear, outdated, or missing, please open a PR.

---

## Development Environment

### Required Tools

| Tool | Version | Purpose |
|------|---------|---------|
| Go | 1.25+ | Core server |
| Python | 3.10+ | SDK, verification, trainer adapters |
| uv | latest | Python package management |
| Docker | latest | Sandbox runtime |
| Make | any | Build tasks |
| protoc | 3.x+ | Protocol Buffers (if modifying `.proto` files) |

### Quick Setup

```bash
# Build the Go server
make build

# Install Python SDK dependencies
cd python/openagora-sdk && uv sync --extra dev

# Run the test suite
make test
```

### Useful Commands

```bash
make build          # Build ./bin/openagora-server
make proto          # Regenerate protobuf code
make docker-server  # Build server Docker image
make docker-agent   # Build minimal agent Docker image
make test           # Run Go + Python tests
make sdk-test       # Run Python tests only
make install-hooks  # Install pre-commit git hooks
make dev            # Start local development server
```

### Git Hooks

Install the pre-commit hooks to run lint/format checks locally before each commit:

```bash
make install-hooks
```

This prevents the `arena: command not found` / `langsmith: command not found` messages that can occur when an inconsistent or missing hook configuration is present.

---

## Project Structure

Understanding the layout will help you navigate the codebase:

```
OpenAgora/
├── go/                   # Go core
│   ├── cmd/              # Binaries
│   └── pkg/              # Reusable packages (server, proxy, sandbox, ...)
├── proto/                # gRPC / Protobuf definitions
├── python/               # Python packages
│   ├── openagora-sdk/        # Python client
│   ├── openagora-verify/     # Verification plugins
│   └── openagora-verl/       # veRL adapter
├── docker/               # Dockerfiles
├── docs/                 # Documentation
├── examples/             # Examples and integrations
├── Makefile              # Common tasks
└── .github/workflows/    # CI / CD
```

---

## Coding Standards

### Go

- Follow the [Effective Go](https://go.dev/doc/effective_go) guidelines.
- Run `gofmt` on all Go files.
- `golangci-lint` is enforced in CI. Run it locally if possible:
  ```bash
  cd go && golangci-lint run ./...
  ```
- Keep package names short and meaningful.
- Document exported symbols with Go doc comments.

### Python

- Follow [PEP 8](https://peps.python.org/pep-0008/).
- Use type hints where practical.
- Format with a consistent style (we use what the project currently uses).
- Add docstrings to public modules, classes, and functions.

### Protocol Buffers

- Keep `.proto` files backward-compatible when possible.
- Add clear field and message documentation.
- Run `make proto` after modifying `.proto` files.

### Docker

- Keep images small and layer caches friendly.
- Use multi-stage builds where appropriate.
- Document any non-obvious environment variables in comments.

---

## Testing

All changes should include tests when applicable.

### Running Tests

```bash
# Go tests
cd go && go test ./...

# Python SDK tests
cd python/openagora-sdk && uv run pytest

# All tests
make test
```

### Writing Tests

- Go: use the standard `testing` package and `testify` where helpful.
- Python: use `pytest`.
- Add integration tests for new sandbox providers or trajectory backends.
- Ensure CI passes before requesting a review.

---

## Commit Messages

We prefer clear commit messages that explain the "why" as well as the "what":

```
subject: summary in imperative mood (50 chars or less)

Body explaining the motivation and any important details.
Use bullet points if there are multiple changes.

Fixes #123
```

Examples:

```
Add E2B sandbox provider

Implements the sandbox.Provider interface for E2B sandboxes.
Includes lifecycle hooks and environment variable injection.

Fixes #42
```

```
Fix token budget race in concurrent rollouts

The token counter was not atomic, causing budget overruns under
high concurrency. Switched to atomic.Uint64.
```

---

## Pull Request Process

1. **Open a PR** from your fork to the `main` branch.
2. **Fill out the PR template** as completely as possible.
3. **Ensure CI passes.** If CI fails, please fix the issues.
4. **Request review** from a maintainer.
5. **Address feedback** promptly and kindly.
6. **Squash or clean up commits** if requested.

A maintainer will merge once:

- CI is green
- At least one maintainer has approved
- All review comments are resolved

---

## Review Process

We aim to review PRs within a few business days. Reviews may include:

- Suggestions for code clarity or performance
- Requests for additional tests or documentation
- Questions about design choices

Please be respectful and constructive in your responses. Code review is a collaborative process.

---

## Questions?

- 💬 [GitHub Discussions](https://github.com/albert-lv/OpenAgora/discussions)
- 🐛 [GitHub Issues](https://github.com/albert-lv/OpenAgora/issues)

Welcome aboard, and happy building! 🚀
