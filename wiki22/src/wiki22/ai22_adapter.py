from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


EXPECTED_RC_SHA256 = (
    "1DFA9DDE565B8C225BB973628D76D84656996ED080720643D3FF860304CF162A"
)

EXPECTED_RC_MANIFEST_SHA256 = (
    "E894B2AE8136FDC97D0F3C5E09D0668B90A722FE2491B401394DF2AFFDC19130"
)

EXPECTED_CORE_SHA256 = (
    "3C49A32FD82BE91B4F6FCD63D1009FEACA795FF94B52AE60BBA0738D43F7BC49"
)


class AI22AdapterError(
    RuntimeError
):
    pass


def _sha256_file(
    path: Path,
) -> str:

    h = hashlib.sha256()

    with path.open("rb") as handle:

        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            h.update(block)

    return h.hexdigest().upper()


def _canonical_sha(
    value,
) -> str:

    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        raw
    ).hexdigest().upper()


class AI22Adapter:
    """Controlled read-only boundary to AI22_V017_RC01."""

    rc_id = "AI22_V017_RC01"

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

        self.rc_root = (
            self.workspace_root
            / "rc_preparation"
            / self.rc_id
        )

        self.rc_package = (
            self.rc_root
            / "package"
        )

        self.rc_manifest_path = (
            self.rc_root
            / "evidence"
            / "AI22_V017_RC01_FILE_MANIFEST.json"
        )

        self.rc_identity_path = (
            self.rc_root
            / "evidence"
            / "AI22_V017_RC01_IDENTITY.json"
        )

        # Historical Windows aliases require symlinks and colon characters.
        # Keep this disposable compatibility tree on the host temporary FS;
        # FAT/exFAT removable media only carries portable, ordinary filenames.
        # Learned memory remains under wiki22/.runtime on the package volume.
        self._temporary_runtime = tempfile.TemporaryDirectory(
            prefix="wiki22-ai22-", dir="/tmp" if os.name != "nt" else None,
        )
        self.runtime_mount = Path(self._temporary_runtime.name) / "mount"

    def close(self) -> None:
        """Remove only this adapter's owned temporary compatibility files."""
        self._temporary_runtime.cleanup()

    def verify_integrity(
        self,
    ) -> dict:

        if not self.rc_manifest_path.is_file():
            raise AI22AdapterError(
                "RC manifest missing"
            )

        if (
            _sha256_file(
                self.rc_manifest_path
            )
            != EXPECTED_RC_MANIFEST_SHA256
        ):
            raise AI22AdapterError(
                "RC manifest identity mismatch"
            )

        if not self.rc_identity_path.is_file():
            raise AI22AdapterError(
                "RC identity missing"
            )

        manifest = json.loads(
            self.rc_manifest_path.read_text(
                encoding="utf-8-sig"
            )
        )

        identity = json.loads(
            self.rc_identity_path.read_text(
                encoding="utf-8-sig"
            )
        )

        rows = manifest.get(
            "files",
            []
        )

        if len(rows) != 36:
            raise AI22AdapterError(
                "unexpected RC file count"
            )

        for row in rows:

            path = (
                self.rc_package
                / row["relative_path"]
            )

            if not path.is_file():
                raise AI22AdapterError(
                    "RC file missing: "
                    + row["relative_path"]
                )

            if (
                _sha256_file(path)
                != row["sha256"]
            ):
                raise AI22AdapterError(
                    "RC file identity mismatch: "
                    + row["relative_path"]
                )

        rc_sha = _canonical_sha({
            "rc_id":
                self.rc_id,

            "files":
                rows,
        })

        if rc_sha != EXPECTED_RC_SHA256:
            raise AI22AdapterError(
                "RC canonical identity mismatch"
            )

        if (
            identity.get(
                "core_sha256"
            )
            != EXPECTED_CORE_SHA256
        ):
            raise AI22AdapterError(
                "RC core identity mismatch"
            )

        return {
            "status":
                "PASS",

            "rc_id":
                self.rc_id,

            "rc_sha256":
                rc_sha,

            "file_count":
                len(rows),

            "core_sha256":
                identity.get(
                    "core_sha256"
                ),
        }

    def _materialize_runtime_mount(
        self,
    ) -> Path:

        integrity = (
            self.verify_integrity()
        )

        if integrity["status"] != "PASS":
            raise AI22AdapterError(
                "RC integrity failed"
            )

        if self.runtime_mount.exists():

            shutil.rmtree(
                self.runtime_mount
            )

        self.runtime_mount.mkdir(
            parents=True
        )

        manifest = json.loads(
            self.rc_manifest_path.read_text(
                encoding="utf-8-sig"
            )
        )

        for row in manifest["files"]:

            relative = (
                row["relative_path"]
                .replace("\\", "/")
            )

            source = (
                self.rc_package
                / relative
            )

            destination = None

            if relative.startswith(
                "product/"
            ):
                destination = (
                    self.runtime_mount
                    / relative
                )

            elif relative.startswith(
                "v16/"
            ):
                destination = (
                    self.runtime_mount
                    / relative
                )

            elif relative.startswith(
                "v17/"
            ):
                suffix = relative[
                    len("v17/"):
                ]

                destination = (
                    self.runtime_mount
                    / "v17_dev"
                    / "AI22_V017_DEV_CANDIDATE_01"
                    / suffix
                )

            if destination is None:
                continue

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )

            if (
                _sha256_file(destination)
                != row["sha256"]
            ):
                raise AI22AdapterError(
                    "runtime mount byte mismatch: "
                    + relative
                )

        return self.runtime_mount

    def adjudicate_structured(
        self,
        *,
        question: str,
        evidence_payload: dict,
    ) -> dict:

        mount = (
            self._materialize_runtime_mount()
        )

        child = r"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path


root = Path(
    sys.argv[1]
)


class OfflineSocket(
    socket.socket
):

    def connect(
        self,
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "NETWORK_BLOCKED_BY_WIKI22"
        )

    def connect_ex(
        self,
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "NETWORK_BLOCKED_BY_WIKI22"
        )


def blocked_connection(
    *args,
    **kwargs,
):
    raise RuntimeError(
        "NETWORK_BLOCKED_BY_WIKI22"
    )


socket.socket = OfflineSocket


def blocked_dns(
    *args,
    **kwargs,
):
    raise RuntimeError(
        "NETWORK_BLOCKED_BY_WIKI22"
    )

socket.create_connection = (
    blocked_connection
)

socket.getaddrinfo = blocked_dns
socket.gethostbyname = blocked_dns
socket.gethostbyname_ex = blocked_dns


sys.path.insert(
    0,
    str(root),
)


from product.ai22_runtime.api import (
    AI22ProductAPI,
    REQUEST_SCHEMA,
)

from product.ai22_runtime.bridge_loader import (
    load_validated_v016_bridge,
)

from product.ai22_runtime.runtime import (
    AI22ProductRuntime,
)


request_input = json.loads(
    sys.stdin.read()
)


question = request_input[
    "question"
]

evidence_payload = request_input[
    "evidence_payload"
]


runtime = AI22ProductRuntime()

snapshot = runtime.start()


if (
    snapshot.state != "READY"
    or snapshot.error is not None
):
    raise RuntimeError(
        "AI22_RUNTIME_NOT_READY"
    )


bridge = (
    load_validated_v016_bridge()
)


targets = (
    bridge.semantic
    .extract_v16_targets(
        question
    )
)


if not targets:

    raise RuntimeError(
        "AI22_NO_TARGET_EXTRACTED"
    )


target = targets[0]


v16_entailed = bool(
    bridge.guard.bind_v16_target(
        target,
        evidence_payload,
    )
)


api = AI22ProductAPI(
    runtime,
    auto_start=False,
)


if sys.platform.startswith("linux"):
    import os
    from product.ai22_runtime.resource_guard import ResourceGuard
    def current_resources():
        rss = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        return {"memory_rss_bytes": rss, "memory_metric_available": True}
    api.resource_guard = ResourceGuard(resource_sampler=current_resources)

response = api.dispatch({
    "schema":
        REQUEST_SCHEMA,

    "request_id":
        "WIKI22-AI22-INTEGRATION",

    "operation":
        "adjudicate_structured",

    "payload": {
        "question":
            question,

        "target":
            target,

        "evidence_payload":
            evidence_payload,

        "v16_entailed":
            v16_entailed,
    },
})


print(
    json.dumps(
        {
            "response":
                response,

            "v16_entailed":
                v16_entailed,

            "runtime_state":
                snapshot.state,

            "runtime_version":
                snapshot.product_runtime_version,

            "runtime_source_count":
                snapshot.runtime_source_count,

            "network":
                "BLOCKED",

            "offline":
                True,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
)
"""

        env = dict(
            os.environ
        )

        env[
            "PYTHONUTF8"
        ] = "1"

        env[
            "PYTHONIOENCODING"
        ] = "utf-8"

        env[
            "PYTHONDONTWRITEBYTECODE"
        ] = "1"


        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(mount),
            ],
            cwd=str(mount),
            env=env,
            input=json.dumps(
                {
                    "question":
                        question,

                    "evidence_payload":
                        evidence_payload,
                },
                ensure_ascii=False,
            ),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=180,
        )


        if completed.returncode != 0:

            raise AI22AdapterError(
                "AI22 adjudication child failed:\n"
                + completed.stdout
                + "\n"
                + completed.stderr
            )


        lines = [
            line.strip()
            for line
            in completed.stdout.splitlines()
            if line.strip()
        ]


        if not lines:

            raise AI22AdapterError(
                "AI22 adjudication returned no output"
            )


        result = json.loads(
            lines[-1]
        )


        response = result.get(
            "response",
            {}
        )


        if response.get(
            "status"
        ) != "OK":

            raise AI22AdapterError(
                "AI22 adjudication status not OK: "
                + repr(response)
            )


        result[
            "rc_id"
        ] = self.rc_id

        result[
            "rc_sha256"
        ] = EXPECTED_RC_SHA256

        result[
            "adapter"
        ] = "AI22Adapter"

        return result

    def verify_excerpt(self, *, question: str, claim: str, evidence: dict) -> dict:
        """Verify an exact local excerpt with the frozen documentary primitive.

        This is documentary support, not native semantic adjudication. Wiki22
        owns query relevance; no fabricated V16 target or entailment is passed.
        """
        # Validate provenance here, before crossing into the frozen runtime.
        # The AI22 child receives only the accepted excerpt, never rejected
        # sentences from the surrounding source chunk.
        start, end = evidence["start"], evidence["end"]
        original = evidence["document_text"]
        if not (0 <= start < end <= len(original)):
            raise AI22AdapterError("INVALID_SOURCE_OFFSETS")
        accepted_evidence = {"evidence_id": evidence["evidence_id"],
                             "text": original[start:end], "start": start, "end": end}
        mount = self._materialize_runtime_mount()
        child = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from wiki22.offline import OfflineGuard
with OfflineGuard():
    from product.ai22_runtime.runtime import AI22ProductRuntime
    runtime = AI22ProductRuntime()
    snapshot = runtime.start()
    if snapshot.state != "READY" or snapshot.error:
        raise RuntimeError("AI22_RUNTIME_NOT_READY")
    request = json.load(sys.stdin)
    source = request["evidence"]
    excerpt = source["text"]
    # Exact equality protects accents/polarity before the frozen normalizer.
    exact = request["claim"] == excerpt
    supported, rows = runtime.modules.core.documentary_support(request["claim"], [excerpt])
    print(json.dumps({
        "decision": "DOCUMENTED" if exact and supported else "STOP",
        "operation": "documentary_support",
        "semantic_adjudication": "NOT_RUN",
        "support_rows": rows if exact and supported else [],
        "question": request["question"], "claim": request["claim"],
        "evidence_id": source["evidence_id"],
        "runtime_state": snapshot.state,
        "runtime_version": snapshot.product_runtime_version,
        "network": "BLOCKED", "offline": True,
    }, ensure_ascii=False))
"""
        env = dict(os.environ)
        env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        result = subprocess.run([sys.executable, "-c", child, str(mount)],
            cwd=mount, env=env, input=json.dumps({"question": question, "claim": claim,
            "evidence": accepted_evidence}, ensure_ascii=False), text=True, encoding="utf-8",
            capture_output=True, timeout=120, check=False)
        if result.returncode:
            raise AI22AdapterError("AI22 documentary check failed: " + result.stderr)
        value = json.loads(result.stdout.splitlines()[-1])
        value.update(rc_id=self.rc_id, rc_sha256=EXPECTED_RC_SHA256)
        return value

    def health(
        self,
    ) -> dict:

        mount = (
            self._materialize_runtime_mount()
        )

        child = r"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path


root = Path(
    sys.argv[1]
)


class OfflineSocket(socket.socket):

    def connect(
        self,
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "NETWORK_BLOCKED_BY_WIKI22"
        )

    def connect_ex(
        self,
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "NETWORK_BLOCKED_BY_WIKI22"
        )


def blocked_connection(
    *args,
    **kwargs,
):
    raise RuntimeError(
        "NETWORK_BLOCKED_BY_WIKI22"
    )


socket.socket = OfflineSocket


def blocked_dns(
    *args,
    **kwargs,
):
    raise RuntimeError(
        "NETWORK_BLOCKED_BY_WIKI22"
    )

socket.create_connection = (
    blocked_connection
)

socket.getaddrinfo = blocked_dns
socket.gethostbyname = blocked_dns
socket.gethostbyname_ex = blocked_dns


sys.path.insert(
    0,
    str(root),
)


from product.ai22_runtime.runtime import (
    AI22ProductRuntime,
)


runtime = AI22ProductRuntime()

snapshot = runtime.start()


print(
    json.dumps(
        {
            "state":
                snapshot.state,

            "error":
                snapshot.error,

            "runtime_version":
                snapshot.product_runtime_version,

            "runtime_source_count":
                snapshot.runtime_source_count,

            "network":
                "BLOCKED",

            "product_runtime_module":
                str(
                    Path(
                        sys.modules[
                            "product.ai22_runtime.runtime"
                        ].__file__
                    ).resolve()
                ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
"""

        env = dict(
            os.environ
        )

        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(mount),
            ],
            cwd=str(mount),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
        )

        if completed.returncode != 0:

            raise AI22AdapterError(
                "AI22 runtime health child failed:\n"
                + completed.stdout
                + "\n"
                + completed.stderr
            )

        lines = [
            line.strip()
            for line
            in completed.stdout.splitlines()
            if line.strip()
        ]

        if not lines:
            raise AI22AdapterError(
                "AI22 runtime health returned no data"
            )

        result = json.loads(
            lines[-1]
        )

        if (
            result.get("state")
            != "READY"
            or result.get("error")
            is not None
            or result.get(
                "runtime_version"
            )
            != "0.11.0"
        ):
            raise AI22AdapterError(
                "AI22 runtime not READY: "
                + repr(result)
            )

        module_path = Path(
            result[
                "product_runtime_module"
            ]
        )

        try:
            module_path.relative_to(
                mount
            )
        except ValueError:
            raise AI22AdapterError(
                "AI22 runtime loaded outside controlled RC mount"
            )

        return {
            **result,

            "rc_id":
                self.rc_id,

            "rc_sha256":
                EXPECTED_RC_SHA256,

            "adapter":
                "READY",

            "offline":
                True,
        }


# =====================================================================
# WIKI22_LINUX_WINDOWS_PATH_COMPAT_V1
#
# Linux-only compatibility layer for the immutable AI22_V017_RC01
# runtime. The frozen RC contains historical Windows path constants.
#
# This layer DOES NOT modify RC01 or its copied files.
# It creates compatibility symlinks inside the disposable Wiki22
# runtime mount after RC bytes have been verified/materialized.
# =====================================================================

if os.name != "nt":

    _wiki22_original_materialize_runtime_mount = (
        AI22Adapter._materialize_runtime_mount
    )


    def _wiki22_install_linux_windows_path_aliases(
        mount: Path,
    ) -> None:

        windows_separator = chr(92)

        windows_console_root = (
            "E:"
            + windows_separator
            + "22AI-CONSOLE"
        )

        windows_product_root = (
            windows_console_root
            + windows_separator
            + "product"
        )

        windows_v16_root = (
            windows_console_root
            + windows_separator
            + "v16"
        )

        windows_v17_root = (
            windows_console_root
            + windows_separator
            + "v17_dev"
        )

        windows_candidate_root = (
            windows_v17_root
            + windows_separator
            + "AI22_V017_DEV_CANDIDATE_01"
        )

        aliases = {
            windows_console_root:
                mount,

            windows_product_root:
                mount / "product",

            windows_v16_root:
                mount / "v16",

            windows_v17_root:
                mount / "v17_dev",

            windows_candidate_root:
                (
                    mount
                    / "v17_dev"
                    / "AI22_V017_DEV_CANDIDATE_01"
                ),
        }


        for windows_literal, target in aliases.items():

            alias = (
                mount
                / windows_literal
            )


            if alias.exists() or alias.is_symlink():
                continue


            if not target.exists():
                continue


            relative_target = os.path.relpath(
                target,
                start=alias.parent,
            )


            alias.symlink_to(
                relative_target,
                target_is_directory=
                    target.is_dir(),
            )


    def _wiki22_linux_materialize_runtime_mount(
        self,
    ) -> Path:

        mount = (
            _wiki22_original_materialize_runtime_mount(
                self
            )
        )


        _wiki22_install_linux_windows_path_aliases(
            mount
        )


        return mount


    AI22Adapter._materialize_runtime_mount = (
        _wiki22_linux_materialize_runtime_mount
    )


# =====================================================================
# WIKI22_LINUX_FROZEN_EVIDENCE_BINDING_V1
#
# Product-layer Linux compatibility binding.
#
# Canonical frozen evidence is copied into the DISPOSABLE Wiki22
# runtime mount only.
#
# AI22_V017_RC01 source package remains byte-identical.
# =====================================================================

if os.name != "nt":

    _wiki22_previous_materialize_for_evidence = (
        AI22Adapter._materialize_runtime_mount
    )


    def _wiki22_linux_bind_frozen_evidence(
        self,
    ) -> Path:

        mount = (
            _wiki22_previous_materialize_for_evidence(
                self
            )
        )


        recovery_root = (
            self.workspace_root
            / "recovered_ai22_frozen_evidence"
        )


        target = (
            mount
            / "v17_dev"
            / "AI22_V017_DEV_CANDIDATE_01"
            / "evidence"
        )


        target.mkdir(
            parents=True,
            exist_ok=True,
        )


        for name in (
            "V017_IMMUTABLE_SOURCE_MANIFEST.json",
            "V017_FINAL_FREEZE_READINESS_MANIFEST.json",
        ):

            source = (
                recovery_root
                / name
            )


            if not source.is_file():
                raise AI22AdapterError(
                    "Canonical Linux frozen evidence missing: "
                    + str(source)
                )


            destination = (
                target
                / name
            )


            shutil.copy2(
                source,
                destination,
            )


        return mount


    AI22Adapter._materialize_runtime_mount = (
        _wiki22_linux_bind_frozen_evidence
    )

