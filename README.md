[![Build](https://github.com/michael-lazar/smolnet-portal/workflows/test/badge.svg)](https://github.com/michael-lazar/smolnet-portal/actions/workflows/test.yml)

# Smolnet Portal

This repository contains the code powering https://portal.mozz.us.

The original version was written with Flask, maintained in a personal
repository and never publicly released. This repository is a full
rewrite (version 2) with following goals:

- Switching to an ASGI framework (quartz) to support more simultaneous
  proxy connections.
- Making the codebase more maintainable in the long term by adding
  unit tests, type hints, and linters.

This is probably only useful for myself. You are welcome to use the
code if you want, but I am not publishing this with the goal of
turning it into a collaborative open-source project. That being said,
bug reports are always welcome!

## Development

```bash
# Download the source
git clone https://github.com/michael-lazar/smolnet-portal
cd smolnet-portal/

# Initialize a virtual environment and install dependencies, etc.
# (requires uv, https://docs.astral.sh/uv/)
tools/bootstrap

# Initialize pre-commit hooks
uv run pre-commit install

# Launch the dev server
tools/quart --debug run -p 8000

# Run the tests, linters, etc.
tools/mypy
tools/ruff check
tools/ruff format

tools/pytest
tools/pytest --run-integration

# Add/upgrade dependencies
uv add <package>
uv lock --upgrade
```

## License

[The Human Software License](https://license.mozz.us)

> A hobbyist software license that promotes maintainer happiness
> through personal interactions. Non-human
> [legal entities](https://en.wikipedia.org/wiki/Legal_person) such as
> corporations and agencies aren't allowed to participate.
