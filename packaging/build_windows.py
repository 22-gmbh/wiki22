"""Build the Wiki22 Windows launcher from source with the Windows SDK and MSVC.

Run from an x64 Native Tools prompt. This builds no installer and never signs a
file itself. Signing is a separate, provenance-checked GitHub Actions step.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.9.0"


def resources():
    icon = (ROOT / "packaging/wiki22.ico").as_posix()
    return f'''#include <windows.h>
1 ICON "{icon}"
1 VERSIONINFO
 FILEVERSION 1,9,0,0
 PRODUCTVERSION 1,9,0,0
 FILEFLAGSMASK 0x3fL
 FILEFLAGS 0
 FILEOS VOS_NT_WINDOWS32
 FILETYPE VFT_APP
 FILESUBTYPE 0
BEGIN
 BLOCK "StringFileInfo"
 BEGIN
  BLOCK "040904b0"
  BEGIN
   VALUE "CompanyName", "22 GmbH\\0"
   VALUE "FileDescription", "Wiki22 desktop launcher\\0"
   VALUE "FileVersion", "{VERSION}\\0"
   VALUE "InternalName", "Wiki22\\0"
   VALUE "LegalCopyright", "Copyright (c) 2026 22 GmbH\\0"
   VALUE "OriginalFilename", "Wiki22.exe\\0"
   VALUE "ProductName", "Wiki22\\0"
   VALUE "ProductVersion", "{VERSION}\\0"
  END
 END
 BLOCK "VarFileInfo"
 BEGIN
  VALUE "Translation", 0x409, 1200
 END
END
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    build = ROOT / "build/windows"
    build.mkdir(parents=True, exist_ok=True)
    rc = build / "Wiki22.rc"
    rc.write_text(resources(), encoding="utf-8")
    if args.prepare_only:
        print("Windows resource file prepared; no executable built.")
        return
    for tool in ("rc.exe", "cl.exe"):
        if not shutil.which(tool):
            raise RuntimeError("Use an x64 Native Tools prompt with Windows SDK: " + tool)
    resource = build / "Wiki22.res"
    output = ROOT / "dist/windows-unsigned"
    output.mkdir(parents=True, exist_ok=True)
    executable = output / "Wiki22.exe"
    subprocess.run(["rc.exe", "/nologo", "/fo", str(resource), str(rc)], check=True)
    subprocess.run([
        "cl.exe", "/nologo", "/O2", "/MT", "/utf-8", "/W4",
        str(ROOT / "packaging/bootstrap.c"), str(resource),
        "/Fe:" + str(executable), "/Fo:" + str(build / "Wiki22.obj"),
        "/link", "/SUBSYSTEM:WINDOWS", "/DYNAMICBASE", "/NXCOMPAT",
        "kernel32.lib", "user32.lib", "shell32.lib", "ole32.lib", "uuid.lib",
    ], check=True)
    if executable.stat().st_size >= 4 * 1024**3:
        raise RuntimeError("Executable exceeds the Authenticode size limit")
    # Keep the signing artifact restricted to one first-party executable.
    receipt = {
        "product": "Wiki22", "version": VERSION, "signed": False,
        "artifact": "Wiki22.exe", "bytes": executable.stat().st_size,
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "native_windows_app_tested": False,
    }
    (ROOT / "dist/build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
