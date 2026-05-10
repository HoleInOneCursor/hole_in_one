from __future__ import annotations

import argparse
import sys

# If argv looks like the Cursor/Greptile CLI, run orchestrate.main() (same process argv).
_ORCHESTRATE_FLAGS = frozenset({
    "--prompt",
    "-p",
    "--continuous",
    "-i",
    "--interactive-prompt",
})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hole-in-golf",
        description="Hole In Golf terminal frontend and orchestration entrypoint.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="ui",
        choices=("ui", "backend"),
        help="`ui` opens the terminal dashboard (default); `backend` runs the orchestration loop.",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=1.0,
        help="Dashboard refresh cadence in seconds.",
    )
    return parser


def main() -> None:
    argv = sys.argv[1:]

    if _ORCHESTRATE_FLAGS.intersection(argv):
        from hole_in_one.orchestrate import main as orchestrate_main

        orchestrate_main()
        return

    # Common mistake: `hole-in-golf Change the app…` (sentence as first “mode”).
    if argv and argv[0] not in ("ui", "backend") and not any(a.startswith("-") for a in argv):
        from hole_in_one.orchestrate import main as orchestrate_main

        sys.argv = [sys.argv[0], "--prompt", " ".join(argv)]
        orchestrate_main()
        return

    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "backend":
        from hole_in_one.orchestrate import main as backend_main

        backend_main()
        return
    from hole_in_one.ui.app import run_dashboard

    run_dashboard(refresh_interval=max(0.25, args.refresh_interval))


if __name__ == "__main__":
    main()
