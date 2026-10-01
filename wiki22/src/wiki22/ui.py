from __future__ import annotations
from wiki22.knowledge.selector import build_knowledge_provider

import json
from pathlib import Path
from typing import TextIO

from wiki22.ai22_adapter import (
    AI22Adapter,
)

from wiki22.knowledge.synthetic import (
    SyntheticProvider,
)

from wiki22.query_engine import (
    QueryEngine,
)

from wiki22.offline import (
    OfflineGuard,
)

from wiki22.viewer import (
    KnowledgeViewer,
)


class Wiki22LocalUI:

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        wiki22_root: str | Path,
    ) -> None:

        self.workspace_root = Path(
            workspace_root
        )

        self.wiki22_root = Path(
            wiki22_root
        )

        self.provider = build_knowledge_provider(self.wiki22_root)

        from wiki22.native22_fast.session import NativeSession
        self.native_session = NativeSession(self.wiki22_root / ".runtime/native22/memory.sqlite3")
        self.engine = QueryEngine(self.provider, native_session=self.native_session)

        self.viewer = KnowledgeViewer(
            self.provider
        )

        self.ai22 = AI22Adapter(
            workspace_root=
                self.workspace_root,

            wiki22_root=
                self.wiki22_root,
        )

    @staticmethod
    def _emit(
        output: TextIO,
        title: str,
        value,
    ) -> None:

        output.write(
            "\n"
            + "=" * 72
            + "\n"
        )

        output.write(
            title
            + "\n"
        )

        output.write(
            "=" * 72
            + "\n"
        )

        if isinstance(
            value,
            str,
        ):

            output.write(
                value
                + "\n"
            )

        else:

            output.write(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    default=str,
                )
                + "\n"
            )

    def execute(
        self,
        command: str,
        *,
        output: TextIO,
    ) -> bool:

        command = command.strip()

        if not command:

            return True

        lowered = command.lower()

        if lowered in {
            "quit",
            "exit",
        }:

            self._emit(
                output,
                "WIKI22",
                "Session closed.",
            )

            return False

        if lowered == "help":

            self._emit(
                output,
                "COMMANDS",
                (
                    "query <question>\n"
                    "article <article-id>\n"
                    "evidence <evidence-id>\n"
                    "diagnostics\n"
                    "help\n"
                    "quit"
                ),
            )

            return True

        if lowered == "diagnostics":

            self._emit(
                output,
                "DIAGNOSTICS",
                {
                    "product":
                        "Wiki22",

                    "version":
                        "0.1.0",

                    "offline":
                        True,

                    "knowledge_provider":
                        self.provider.stats(),

                    "provider_health":
                        {
                            "status":
                                self.provider.health().status,

                            "provider":
                                self.provider.health().provider,

                            "offline":
                                self.provider.health().offline,
                        },

                    "ai22":
                        self.ai22.health(),

                    "production":
                        False,
                },
            )

            return True

        if lowered.startswith(
            "article "
        ):

            article_id = (
                command[
                    len("article "):
                ].strip()
            )

            article = (
                self.viewer.article(
                    article_id
                )
            )

            self._emit(
                output,
                "ARTICLE",
                (
                    article
                    if article is not None
                    else {
                        "status":
                            "NOT_FOUND",

                        "article_id":
                            article_id,
                    }
                ),
            )

            return True

        if lowered.startswith(
            "evidence "
        ):

            evidence_id = (
                command[
                    len("evidence "):
                ].strip()
            )

            evidence = (
                self.viewer.evidence(
                    evidence_id
                )
            )

            self._emit(
                output,
                "SUPPORTING EVIDENCE",
                (
                    evidence
                    if evidence is not None
                    else {
                        "status":
                            "NOT_FOUND",

                        "evidence_id":
                            evidence_id,
                    }
                ),
            )

            return True

        if lowered.startswith(
            "query "
        ):

            question = (
                command[
                    len("query "):
                ].strip()
            )

            result = (
                self.engine
                .answer_with_ai22(
                    question,
                    ai22_adapter=
                        self.ai22,
                )
            )

            self._emit(
                output,
                "ANSWER",
                {
                    "status":
                        result.get(
                            "status"
                        ),

                    "answer":
                        result.get(
                            "answer"
                        ),

                    "related_articles": result.get("related_articles", []),
                    "answer_type":
                        result.get(
                            "answer_type"
                        ),

                    "ai22_decision":
                        result.get(
                            "ai22_decision"
                        ),

                    "article_id":
                        (
                            result.get(
                                "retrieval",
                                {},
                            ).get(
                                "article_id"
                            )
                        ),
                },
            )

            self._emit(
                output,
                "SUPPORTING EVIDENCE",
                result.get(
                    "supporting_evidence",
                    [],
                ),
            )

            self._emit(output, "QUERY TRACE", result.get("trace", {
                "query": question,
                "provider": self.provider.stats(),
                "status": result.get("status"),
                "ai22_processing": result.get("ai22_processing"),
            }))

            return True

        self._emit(
            output,
            "ERROR",
            {
                "status":
                    "UNKNOWN_COMMAND",

                "command":
                    command,
            },
        )

        return True

    def run(
        self,
        *,
        input_stream: TextIO,
        output_stream: TextIO,
    ) -> None:

        self._emit(
            output_stream,
            "WIKI22 V0.1",
            (
                "Offline local knowledge interface.\n"
                "Type 'help' for commands."
            ),
        )

        while True:

            output_stream.write(
                "\nwiki22> "
            )

            output_stream.flush()

            line = input_stream.readline()

            if line == "":

                break

            if not self.execute(
                line,
                output=output_stream,
            ):

                break


def run_local_ui() -> None:

    import sys

    module_file = Path(
        __file__
    ).resolve()

    wiki22_root = (
        module_file.parents[2]
    )

    workspace_root = (
        wiki22_root.parent
    )

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
