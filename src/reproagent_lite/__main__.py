"""Allow ``python -m reproagent_lite`` to behave like the CLI entry point."""

from .cli import main


if __name__ == "__main__":
    # Propagate the CLI's documented exit code to shells and automation.
    raise SystemExit(main())
