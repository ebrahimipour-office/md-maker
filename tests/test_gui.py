import queue
import sys

from md_maker.gui import _QueueWriter, build_argv


def test_build_argv():
    assert build_argv(["a.pdf", "dir"], "  ", "off", "never", False, True, False, True) == [
        "a.pdf", "dir", "--ai", "off", "--ocr", "never", "--page-markers", "--plan"]
    assert build_argv(["a.pdf"], "out", "smart", "auto", True, False, True, False)[-4:] == [
        "-o", "out", "--rtl-wrap", "--report"]


def test_cli_output_reaches_log(tmp_path):
    from md_maker import cli

    (tmp_path / "x.html").write_text("<h1>Hi</h1><p>text</p>")
    q = queue.Queue()
    old = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _QueueWriter(q)
    try:
        code = cli._main(build_argv([tmp_path / "x.html"], "", "off", "auto", False, False, False, False))
    finally:
        sys.stdout, sys.stderr = old
    log = "".join(q.queue)
    assert code == 0 and "x.md" in log and (tmp_path / "x.md").exists()
