# Contributing

Contributions to AniBridge are always appreciated! Please follow the guidelines below to help us maintain a high-quality codebase.

## Development

This guide is for developers who want to contribute to the backend of the AniBridge project. It assumes you'll be using Visual Studio Code with Dev Containers (requires Docker). Of course, you are free to use any IDE you prefer, but the VS Code IDE and Devcontainer settings are already pre-configured with linting and dependency management for you.

_If you decide to use a different IDE, you will need to set up the environment manually and infer the project's dependencies yourself. Take a look at [`.devcontainer/devcontainer.json`](/.devcontainer/devcontainer.json) and [`.vscode/settings.json`](/.vscode/settings.json) for an idea of what's required._

### Tools required

- [Visual Studio Code](https://code.visualstudio.com/) with the [Dev Containers](https://code.visualstudio.com/docs/remote/containers) extension
- [Docker](https://www.docker.com/)

### Getting started

1. Fork AniBridge.
2. Clone the repository into your development machine ([_info_](https://docs.github.com/en/get-started/quickstart/fork-a-repo)).
3. Open the project in Visual Studio Code, it will prompt you to reopen in a dev container, do so.
4. If you didn't receive a prompt, you can also open the command palette (Ctrl+Shift+P) and select "Reopen in Container".
5. The dev container will build and setup all required packages and dependencies.
6. Once the dev container is ready, you can activate the Python virtual environment with `source .venv/bin/activate`.

## Contributing Code

The AniBridge codebase can be split into three primary components:

```
.
├── README.md
├── frontend
│   └── ... # Frontend (Svelte/TypeScript)
└── src
    ├── core
    │   └── ... # Core synchronization engine (Python)
    └── web
        └── ... # API (Python/Litestar)
```

The project has a set of developer scripts at `scripts/dev.py` to help with common tasks. You can run these scripts with `python scripts/dev.py <command>`. Run `python scripts/dev.py --help` to see a list of available commands.

- Follow the coding standard. We use [ruff](https://docs.astral.sh/ruff/) for Python linting and [ESLint](https://eslint.org/) for JavaScript/TypeScript linting.
    - Run `python scripts/dev.py lint` to ensure your Python and Svelte code passes the linting rules.
    - Run `python scripts/dev.py format` to auto-format your Python and Svelte code.
    - Run `python scripts/dev.py test` to run the test suite and ensure all tests pass.
- Make sure any complex or non-obvious code is explained with comments. This helps maintain readability and ease of review.

## Pull Requesting

- Make pull requests to the default/HEAD branch.
- Please ensure your pull request has a clear title and description.
- Fill out the pull request template in its entirety, it helps us understand what your changes are and why they are needed.
- Each PR should come from its own [feature branch](http://martinfowler.com/bliki/FeatureBranch.html) not develop in your fork, it should have a meaningful branch name (what is being added/fixed).
    - new-feature (Good)
    - fix-bug (Good)
    - patch (Bad)
    - develop (Bad)
- Each PR should solve one issue or add one feature (or a group of meaningfully connected issues/features), if you have multiple, please create a separate PR for each.
- Check for existing pull requests at https://github.com/anibridge/anibridge/pulls to avoid duplicates.
