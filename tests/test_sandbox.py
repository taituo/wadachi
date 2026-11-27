"""The sandbox tools stay consistent: scripts parse, pins are complete, no logins in the tree."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SANDBOX = Path(__file__).resolve().parent.parent / "sandbox"
CLIS = ["claude", "codex", "opencode", "agy", "grok"]


def rows(name):
    return {line.split()[0]: line.split()[1:] for line in (SANDBOX / name).read_text().splitlines()
            if line.strip() and not line.startswith("#")}


@pytest.mark.parametrize("script", ["cliauth.sh", "lib.sh", "build-image.sh", "k8s-check.sh"])
def test_bash_scripts_parse(script):
    subprocess.run(["bash", "-n", str(SANDBOX / script)], check=True)


def test_entrypoint_is_posix_sh():
    sh = shutil.which("dash") or shutil.which("sh")
    subprocess.run([sh, "-n", str(SANDBOX / "entrypoint.sh")], check=True)


def test_every_cli_has_login_files_and_a_full_pin():
    logins, pins = rows("auth-files.txt"), rows("versions.lock")
    for cli in CLIS:
        assert logins[cli], cli
        assert all(not f.startswith("/") and ".." not in f for f in logins[cli])
        version, source, checksum = pins[cli]
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), cli
        if source.startswith("https://"):  # downloaded releases are checked by hash
            assert re.fullmatch(r"sha(256|512):[0-9a-f]+", checksum), cli
            assert version in source, cli
        else:
            assert source.startswith("npm:"), cli
    assert re.search(r"@sha256:[0-9a-f]{64}$", pins["node"][1])


def test_build_args_match_the_containerfile():
    args = set(re.findall(r"^ARG (\w+)", (SANDBOX / "Containerfile").read_text(), re.M))
    passed = set(re.findall(r"--build-arg (\w+)=", (SANDBOX / "build-image.sh").read_text()))
    assert args == passed


def test_lib_reads_the_tables():
    out = subprocess.run(["bash", "-c", f". {SANDBOX}/lib.sh; auth_files claude; pinned grok; pinned agy 4 | cut -c1-7"],
                         check=True, capture_output=True, text=True).stdout.split("\n")
    assert out[0] == ".claude/.credentials.json .claude.json"
    assert out[1] == rows("versions.lock")["grok"][0]
    assert out[2] == "sha512:"


def test_no_login_material_in_the_tree():
    for path in SANDBOX.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            assert not re.search(r'"(refreshToken|accessToken|access_token|refresh_token)"\s*:\s*"[^"]', text), path
