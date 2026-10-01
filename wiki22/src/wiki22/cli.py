from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiki22.app import Wiki22App
from wiki22.offline import OfflineGuard
from wiki22.ui import Wiki22LocalUI


MODULE_FILE = Path(
    __file__
).resolve()

DEFAULT_WIKI22_ROOT = (
    MODULE_FILE.parents[2]
)

DEFAULT_WORKSPACE_ROOT = (
    DEFAULT_WIKI22_ROOT.parent
)


def main() -> int:

    parser = argparse.ArgumentParser(
        prog="wiki22"
    )

    parser.add_argument(
        "--workspace-root",
        default=str(
            DEFAULT_WORKSPACE_ROOT
        ),
    )

    parser.add_argument(
        "--wiki22-root",
        default=str(
            DEFAULT_WIKI22_ROOT
        ),
    )

    parser.add_argument(
        "--health",
        action="store_true",
    )

    parser.add_argument(
        "--ui",
        action="store_true",
    )

    args = parser.parse_args()

    workspace_root = Path(
        args.workspace_root
    ).resolve()

    wiki22_root = Path(
        args.wiki22_root
    ).resolve()

    if args.ui:

        import sys

        ui = Wiki22LocalUI(
            workspace_root=
                workspace_root,

            wiki22_root=
                wiki22_root,
        )

        with OfflineGuard():

            ui.run(
                input_stream=
                    sys.stdin,

                output_stream=
                    sys.stdout,
            )

        return 0

    app = Wiki22App(
        workspace_root=
            workspace_root,

        wiki22_root=
            wiki22_root,
    )

    with OfflineGuard():

        result = app.startup()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
