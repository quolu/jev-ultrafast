"""Bundled text files are UTF-8. Reading them with the platform default fails on Windows (cp932)."""

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "jev_ultrafast"


def test_package_text_reads_name_their_encoding():
    missing = []
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"read_text", "write_text"} and not any(k.arg == "encoding" for k in node.keywords):
                missing.append(f"{path.name}:{node.lineno}")
    assert missing == []


def test_import_and_env_loading_do_not_use_the_default_encoding(tmp_path):
    (tmp_path / ".env").write_text("JEV_ENCODING_CHECK=日本語\n", encoding="utf-8")
    # The child compares the value itself, so the console encoding of its output does not matter.
    code = (
        "import os, jev_ultrafast.browser, jev_ultrafast.demo as d;"
        " d.load_environment(); print(os.environ['JEV_ENCODING_CHECK'] == '\\u65e5\\u672c\\u8a9e')"
    )
    result = subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning", "-c", code],
        cwd=tmp_path, capture_output=True, text=True, errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"
