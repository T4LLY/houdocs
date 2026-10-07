# HouDocs

[![CI](https://github.com/T4LLY/houdocs/actions/workflows/ci.yml/badge.svg)](https://github.com/T4LLY/houdocs/actions/workflows/ci.yml)

HouDocs is an offline-first CLI for indexing, searching, and reading local SideFX Houdini documentation. It provides structured access to node documentation, HOM Python APIs, VEX functions, and general Houdini documentation.

After documentation has been initialized for a Houdini version, normal documentation search and read commands use local versioned indexes and do not require a running Houdini process.

## Requirements

- Python 3.11 or later
- A local SideFX Houdini installation for `houdocs init`
- [uv](https://docs.astral.sh/uv/)

## Installation

Clone the repository and install its `houdocs` command with uv:

```bash
git clone https://github.com/T4LLY/houdocs.git
cd houdocs
uv tool install .
```

Verify the installation:

```bash
houdocs --help
```

For development without installing the command globally, use `uv sync` and prefix commands with `uv run` instead:

```bash
uv sync
uv run houdocs --help
```

### Install AI skills

After the repository is available at `T4LLY/houdocs`, install its bundled Houdini documentation skill with:

```bash
npx skills add T4LLY/houdocs
```

This installs the `houdini-cli-documents-search` skill for supported AI coding tools.

## Usage

### Initialize documentation

Build the local documentation indexes from an installed Houdini version:

```bash
houdocs init
```

Select a specific installed version when needed:

```bash
houdocs init --houdini-version 22.0.429
```

If no version is selected explicitly or through configuration, HouDocs uses the newest discovered Houdini installation. Initialization collects the installed Help documentation and runtime node metadata, then builds version-local documentation and search databases.

Use `--progress` to show interactive initialization progress on a TTY:

```bash
houdocs init --progress
```

Reinitializing an existing version requires confirmation before its generated databases are rebuilt.

### Search documentation

Search all indexed documentation domains:

```bash
houdocs search "packed primitive"
```

Restrict the search to one domain when the target is already known:

```bash
houdocs search "connect node input" --domain hom
```

Available domains are:

- `node` — Houdini node documentation
- `hom` — HOM Python APIs
- `vex` — VEX functions
- `document` — general Houdini documentation

Search combines lexical and semantic ranking. Results are intentionally compact and contain navigation metadata such as `path`, `kind`, `score`, and `tokens`; use the corresponding reader command to retrieve the actual documentation.

### Read general documentation

Read a complete documentation page:

```bash
houdocs read Node
```

List its sections without loading their bodies:

```bash
houdocs sections Node
```

Read one section directly:

```bash
houdocs read Node setInput
```

When a page title is ambiguous, HouDocs returns numbered candidates. Re-run `read` or `sections` with `--pick N` to select one.

### Read node documentation

Read structured documentation for a node type:

```bash
houdocs node Sop/attribwrangle
```

Node results expose structured inputs, outputs, parameters, and related documentation. A detail path can retrieve one specific item, for example:

```bash
houdocs node Sop/attribwrangle/parameters/snippet
```

### Read HOM documentation

Read one HOM symbol directly:

```bash
houdocs hom hou.Node.setInput
```

### Read VEX documentation

Read one VEX function directly:

```bash
houdocs vex xyzdist
```

### Configuration

HouDocs stores global configuration in the platform-standard `houdocs` configuration directory. A `.houdocs.toml` file in the current working directory can override global settings for that directory without being created automatically.

For example, select the default Houdini reference version with:

```toml
[houdini]
version = "22.0.429"
```

An explicit `--houdini-version` passed to `init` takes precedence over configured versions.

### Common commands

```bash
# Search across all documentation domains.
houdocs search "packed primitive"

# Read structured node documentation.
houdocs node Sop/attribwrangle

# Read a HOM symbol.
houdocs hom hou.Node.setInput

# Read a VEX function.
houdocs vex xyzdist

# List sections of a general documentation page.
houdocs sections Node
```

Run `--help` at any command level to see its available options:

```bash
houdocs init --help
```

## Testing

GitHub Actions runs Ruff, Pyright, Mypy, Pytest, and OpenSpec strict validation independently on native Ubuntu and Windows runners for pushes, pull requests, and manual runs. Python checks use Python 3.12; tests use fixtures instead of requiring a Houdini installation. Real Houdini initialization is not covered by CI.

Run the same five checks locally on Windows, Linux, or WSL (Node.js 22 and uv are required):

```powershell
uv sync --locked --group dev --python 3.12
uvx --from ruff==0.15.22 ruff check src tests
uv run --with pyright==1.1.414 pyright src
uv run --with mypy==2.4.0 mypy src
uv run --no-sync pytest
npm exec --yes --package=@fission-ai/openspec@1.13.2 -- openspec validate --all --strict
```

WSL checks Linux behavior only; the GitHub Actions Windows runner checks native Windows behavior.

## Related tools

`houbridge`, `houdocs`, and `houlayout` are separate CLIs designed for agent orchestration. Each can be assigned only to agents that need its capabilities, keeping command surfaces small and avoiding unnecessary runtime access.

### Houbridge

`houbridge` provides the general Houdini runtime interface: session management, execution, capture, resources, and scene access.

Use it when an agent needs to control a live Houdini session or execute Houdini Python.

### HouDocs

`houdocs` provides structured search and retrieval over locally indexed Houdini documentation.

It can be assigned to agents that need Houdini API and documentation access without exposing general runtime execution.

### Houlayout

`houlayout` is a node-oriented wrapper around Houbridge for inspecting and organizing Houdini networks.

It intentionally exposes a smaller node/layout-focused interface than the general Houbridge runtime surface.

In short:

- `houbridge` — general Houdini runtime and execution
- `houdocs` — structured Houdini documentation search and retrieval
- `houlayout` — constrained node and network operations

## License

[MIT License](LICENSE)