import json
import os
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from md_maker import config, main, merge, verify
from md_maker.ai import prompts
from md_maker.ai.backend import AIError, AIResult
from md_maker.ai.claude_cli import ClaudeCLI
from md_maker.ai.pipeline import Budget, Pipeline
from md_maker.cache import Cache
from md_maker.triage import triage

FIXTURES = Path(__file__).parent / "fixtures"
ZWNJ = "‌"


@pytest.fixture(scope="module", autouse=True)
def fixtures():
    subprocess.run([sys.executable, str(Path(__file__).parent / "make_fixtures.py")], check=True)


# -- settings ----------------------------------------------------------------


def test_settings_layering(tmp_path, monkeypatch):
    user = config.user_config()
    user.parent.mkdir(parents=True)
    user.write_text('[ai]\nconcurrency = 2\nbudget_usd = 1\n[ai.models]\nrepair = "opus"\n')
    project = tmp_path / "proj"
    project.mkdir()
    (project / "md-maker.toml").write_text("[ai]\nconcurrency = 3\n")
    explicit = tmp_path / "x.toml"
    explicit.write_text('[ocr]\nlang = "eng"\n')
    monkeypatch.chdir(project)
    monkeypatch.delenv("MD_MAKER_AI")

    s = config.load(explicit, {"ai": {"budget_usd": 5}})
    assert s.ai.models.repair == "opus"  # user file
    assert s.ai.concurrency == 3  # project file beats user file
    assert s.ocr.lang == "eng"  # --config
    assert s.ai.budget_usd == 5.0 and isinstance(s.ai.budget_usd, float)  # CLI flag
    assert s.ai.mode == "smart" and s.ai.models.polish == "haiku"  # defaults


def test_settings_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("MD_MAKER_AI")
    bad = tmp_path / "bad.toml"
    bad.write_text("[ai]\nconcurency = 2\n")
    with pytest.raises(config.ConfigError, match="unknown setting `ai.concurency`"):
        config.load(bad)
    bad.write_text('[ai]\nconcurrency = "2"\n')
    with pytest.raises(config.ConfigError, match="must be int"):
        config.load(bad)
    bad.write_text('[ai]\nmode = "always"\n')
    with pytest.raises(config.ConfigError, match="ai.mode"):
        config.load(bad)


def test_init_and_show_config(capsys):
    assert main(["--init-config"]) == 0
    assert config.user_config().read_text() == config.template()
    assert main(["--init-config"]) == 1  # never overwrites
    assert main(["--show-config", "--ai", "max"]) == 0
    assert 'mode = "max"' in capsys.readouterr().out


# -- triage ------------------------------------------------------------------


def _routes(name, settings):
    return [r.route for r in triage(pymupdf.open(FIXTURES / name), settings)]


def test_triage_routes():
    s = config.load(None, {"ai": {"mode": "smart"}})
    assert _routes("persian.pdf", s) == ["repair"]  # table + mixed scripts
    assert _routes("persian_multipage.pdf", s) == ["polish"] * 4
    assert _routes("english.pdf", s) == ["local"]
    assert _routes("persian_scanned.pdf", s) == ["transcribe"]
    s = config.load(None, {"ai": {"mode": "max", "routing": {"polish_rtl": False}}})
    assert _routes("english.pdf", s) == ["repair"]
    assert _routes("persian_multipage.pdf", s) == ["repair"] * 4


# -- verify / merge / cache --------------------------------------------------


def test_verify_score():
    draft = "# عنوان\n\nنسخه 2.1 از نرم افزار PayStar بررسی می شود ۱۳۹۹"
    good = f"# عنوان\n\nنسخه 2.1 از نرم{ZWNJ}افزار PayStar بررسی می{ZWNJ}شود ۱۳۹۹"
    assert verify.score(good, draft, True) == (1.0, [])
    score, problems = verify.score("نسخه از بررسی", draft, True)
    assert score < 0.85 and "numbers missing" in problems
    assert verify.score("| a | b |\n|---|---|\n| 1 |", "", False)[0] < 1
    assert verify.score("Here is the page:\n\ntext", "", False)[0] < 1
    assert verify.clean_output("```markdown\n# hi\n```") == "# hi"


def test_merge_joins_split_table_and_lifts_headings():
    pages = ["## Title\n\n| a | b |\n|---|---|\n| 1 | 2 |", "| a | b |\n|---|---|\n| 3 | 4 |\n\nafter"]
    assert merge.merge(pages) == "# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nafter\n"
    # without a repeated header, the continuation's first row is data
    pages = ["| a | b |\n|---|---|\n| 1 | 2 |", "| 3 | 4 |\n|---|---|\n| 5 | 6 |"]
    assert merge.merge(pages) == "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n"
    assert "<!-- page 2 -->" in merge.merge(pages, page_markers=True)


def test_merge_running_heads():
    pages = [f"Company Report\n\nbody {n}\n\nPage {n}" for n in range(1, 5)]
    assert merge.merge(pages).split() == "body 1 body 2 body 3 body 4".split()
    one_liners = [f"text of page {n}" for n in range(1, 5)]
    assert merge.merge(one_liners).count("text of page") == 4


def test_cache(tmp_path):
    c = Cache(tmp_path)
    c.put("ab12", {"x": "سلام"})
    assert c.get("ab12") == {"x": "سلام"}
    assert Cache(None).get("ab12") is None


# -- pipeline with a fake backend ---------------------------------------------


class FakeBackend:
    def __init__(self, answers):
        self.answers = answers  # model -> markdown, prompt -> markdown, or an exception
        self.calls = []

    def run(self, *, model, effort, system, prompt, image=None, budget_usd=None):
        self.calls.append({"model": model, "image": image is not None, "prompt": prompt, "budget": budget_usd})
        answer = self.answers[model]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(prompt)
        return AIResult(answer, "high", "", 0.01, model)


def _pipeline(backend, tmp_path, budget=0.0, **ai):
    s = config.load(None, {"ai": {"mode": "smart", "budget_usd": budget, **ai}})
    return Pipeline(s, backend, Budget(budget), Cache(tmp_path / "cache"))


def test_pipeline_repairs_routed_page(tmp_path):
    fixed = _local(FIXTURES / "persian.pdf").replace("نرم افزار", f"نرم{ZWNJ}افزار")
    backend = FakeBackend({"sonnet": f"```markdown\n{fixed}```"})
    md, report = _pipeline(backend, tmp_path).convert(FIXTURES / "persian.pdf")
    assert f"نرم{ZWNJ}افزار PayStar" in md
    assert [c["model"] for c in backend.calls] == ["sonnet"] and backend.calls[0]["image"]
    page = report["pages"][0]
    assert page["route"] == "repair" and page["source"] == "ai" and page["score"] >= 0.85
    # second run comes from the cache
    backend.calls.clear()
    _, report = _pipeline(backend, tmp_path).convert(FIXTURES / "persian.pdf")
    assert backend.calls == [] and report["pages"][0]["source"] == "cache"


def _local(path):
    from md_maker.pdf import pdf_to_markdown

    return pdf_to_markdown(path)


def test_pipeline_escalates_weak_result(tmp_path):
    good = _local(FIXTURES / "persian.pdf")
    backend = FakeBackend({"sonnet": "# گزارش", "opus": good})
    md, report = _pipeline(backend, tmp_path).convert(FIXTURES / "persian.pdf")
    assert [c["model"] for c in backend.calls] == ["sonnet", "opus"]
    assert report["pages"][0]["model"] == "opus" and "سرور" in md


def test_pipeline_keeps_draft_on_failure_and_budget(tmp_path):
    backend = FakeBackend({"haiku": AIError("haiku: CLI exited with 1")})
    md, report = _pipeline(backend, tmp_path).convert(FIXTURES / "persian_multipage.pdf")
    assert "متن اصلی صفحه 4" in md and report["fallbacks"] == 4
    # budget: the first paid call spends it, the rest keep their drafts
    backend = FakeBackend({"haiku": "متن", "sonnet": "متن"})
    _, report = _pipeline(backend, tmp_path / "b", budget=0.005, concurrency=1).convert(
        FIXTURES / "persian_multipage.pdf"
    )
    assert len(backend.calls) <= 2 and report["fallbacks"] >= 3


def test_pipeline_polish_is_text_only(tmp_path):
    echo = lambda prompt: prompt.split("<draft>\n")[1].split("\n</draft>")[0]
    backend = FakeBackend({"haiku": echo})
    md, _ = _pipeline(backend, tmp_path).convert(FIXTURES / "persian_multipage.pdf")
    assert [c["model"] for c in backend.calls] == ["haiku"] * 4
    assert not any(c["image"] for c in backend.calls) and "متن اصلی صفحه 4" in md
    assert "<draft>" in backend.calls[0]["prompt"]


# -- the real CLI wrapper, against a fake `claude` executable -----------------

FAKE_CLAUDE = """
import json, os, sys
args = sys.argv[1:]
msg = json.loads(sys.stdin.readline())
system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
    kinds = [c["type"] for c in msg["message"]["content"]]
    f.write(json.dumps({"args": args, "content": kinds, "system": system}) + "\\n")
model = args[args.index("--model") + 1]
print(json.dumps({"type": "system", "subtype": "init"}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.02,
    "modelUsage": {"claude-" + model + "-9": {"inputTokens": 5, "cacheReadInputTokens": 100,
                                             "cacheCreationInputTokens": 900, "outputTokens": 40}},
    "structured_output": {"markdown": "# FAKE " + model + "\\n\\nبدنه", "confidence": "high", "notes": ""}}))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A fake `claude` on PATH: a shebang script, or on Windows a claude.cmd
    wrapper, which is how an npm install of Claude Code runs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "fake_claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    if sys.platform == "win32":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n')
    else:
        exe = bin_dir / "claude"
        exe.write_text(f"#!{sys.executable}\n" + FAKE_CLAUDE, encoding="utf-8")
        exe.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return log


def test_claude_cli_backend(fake_claude):
    s = config.load(None, {"ai": {"mode": "smart"}})
    r = ClaudeCLI(s).run(model="sonnet", effort="medium", system="sys", prompt="p", image=b"png", budget_usd=1.5)
    assert r.markdown.startswith("# FAKE sonnet") and r.cost_usd == 0.02
    assert (r.model, r.input_tokens, r.output_tokens) == ("claude-sonnet-9", 1005, 40)
    call = json.loads(fake_claude.read_text(encoding="utf-8"))
    assert call["content"] == ["image", "text"]
    # free-form text reaches the CLI through a file, intact
    system = prompts.system_prompt(True)
    assert "می‌شود" in system and "\n" in system
    ClaudeCLI(s).run(model="haiku", effort="", system=system, prompt="p")
    assert json.loads(fake_claude.read_text(encoding="utf-8").splitlines()[1])["system"] == system
    for flag in ("--json-schema", "--no-session-persistence", "--max-budget-usd", "--effort"):
        assert flag in call["args"]
    assert "--bare" not in call["args"]


def test_claude_cli_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(AIError, match="not found"):
        ClaudeCLI(config.load(None, {"ai": {"mode": "smart"}}))


def test_cli_ai_end_to_end(fake_claude, tmp_path, capsys):
    out = tmp_path / "out.md"
    assert main([str(FIXTURES / "persian.pdf"), "-o", str(out), "--ai", "smart", "--report"]) == 0
    err = capsys.readouterr().err
    assert "repair     claude-sonnet-9" in err and "escalate   claude-opus-9" in err
    assert "    2 call(s)      2,010 in       80 out  $0.040" in err
    # the fake answer misses the page's words, so sonnet's result is retried with opus
    models = [c["args"][c["args"].index("--model") + 1] for c in map(json.loads, fake_claude.read_text(encoding="utf-8").splitlines())]
    assert models == ["sonnet", "opus"]
    assert out.read_text().startswith("# FAKE opus")
    report = json.loads(out.with_suffix(".report.json").read_text())
    assert report["pages"][0]["route"] == "repair" and report["cost_usd"] == 0.04
    assert report["input_tokens"] == 2010 and report["pages"][0]["model"] == "claude-opus-9"


def test_cli_missing_claude_falls_back(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert main([str(FIXTURES / "english.pdf"), "--stdout", "--ai", "max"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("# Quarterly Report") and "not found" in captured.err


def test_cli_plan(capsys):
    assert main([str(FIXTURES / "persian.pdf"), str(FIXTURES / "english.pdf"), "--plan", "--ai", "smart"]) == 0
    out = capsys.readouterr().out
    assert "repair     sonnet" in out and "-> 1 local" in out


# -- opt-in: a real model call --------------------------------------------------


@pytest.mark.skipif(os.environ.get("MD_MAKER_LIVE") != "1", reason="set MD_MAKER_LIVE=1 to call the real Claude CLI")
def test_live_repair_of_persian_table(tmp_path):
    s = config.load(None, {"ai": {"mode": "smart"}})
    md, report = Pipeline(s, ClaudeCLI(s), Budget(0.5), Cache(None)).convert(FIXTURES / "persian.pdf")
    assert report["pages"][0]["source"] == "ai"
    assert f"نرم{ZWNJ}افزار" in md and "| ۱ | سرور | ۵۰۰٬۰۰۰ |" in md
