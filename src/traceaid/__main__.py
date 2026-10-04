"""Allow ``python -m traceaid`` to invoke the CLI."""

from traceaid.cli import main

raise SystemExit(main())
