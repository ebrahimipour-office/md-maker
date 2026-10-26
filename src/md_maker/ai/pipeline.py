"""PDF -> Markdown with AI help on the pages that need it.

triage (local) -> draft per page (local engines) -> AI per routed page,
in parallel -> verify, escalate weak pages once -> merge (local).
Any AI failure leaves the local draft in place: AI can only improve a page.
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

from .. import cache as cache_mod
from .. import verify
from ..merge import merge
from ..pdf import no_text_message, pdf_pages, render_page_png, resolve_engine
from ..triage import PageReport, triage
from . import prompts
from .backend import AIError, AIResult, Backend


class Budget:
    """Spending shared by every page and file of one run; limit 0 = none."""

    def __init__(self, limit: float):
        self.limit = limit
        self.spent = 0.0
        self._lock = threading.Lock()

    def add(self, usd: float):
        with self._lock:
            self.spent += usd

    def remaining(self) -> float | None:
        with self._lock:
            return None if not self.limit else max(0.0, self.limit - self.spent)


@dataclass
class PageResult:
    page: int
    route: str
    reasons: list[str]
    source: str = "local"  # local | ai | cache
    model: str = ""
    cost_usd: float = 0.0
    score: float | None = None
    confidence: str = ""
    notes: str = ""
    problems: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class _Job:
    report: PageReport
    draft: str
    image: bytes | None
    trusted: bool  # draft comes from a real text layer
    pages: int


class Pipeline:
    def __init__(self, settings, backend: Backend, budget: Budget, cache: cache_mod.Cache, log=None):
        self.s = settings
        self.backend = backend
        self.budget = budget
        self.cache = cache
        self.log = log or (lambda msg: None)
        self.system = prompts.system_prompt(settings.output.figure_notes)

    # -- one page ---------------------------------------------------------

    def _models(self, task: str) -> list[str]:
        """First choice, then the escalation model (if different)."""
        m = self.s.ai.models
        first = getattr(m, task)
        second = m.repair if task == "polish" else m.escalate
        return [first] if second == first else [first, second]

    def _effort(self, model_slot: str) -> str:
        return getattr(self.s.ai.effort, model_slot, "")

    def _call(self, job: _Job, task: str, model: str, effort: str, file_key: str) -> tuple[AIResult, bool]:
        """(result, from cache)."""
        page, pages = job.report.page, job.pages
        # transcribe never sees the draft, so it must not split the cache
        draft_key = "" if task == "transcribe" else cache_mod.key(job.draft)
        k = cache_mod.key(file_key, page, task, model, prompts.PROMPT_VERSION,
                          self.s.output.figure_notes, draft_key)
        if hit := self.cache.get(k):
            return AIResult(**hit), True
        if task == "polish":
            prompt, image = prompts.polish(job.draft, page, pages), None
        elif task == "repair":
            prompt, image = prompts.repair(job.draft, page, pages), job.image
        else:
            prompt, image = prompts.transcribe(page, pages), job.image
        remaining = self.budget.remaining()
        if remaining is not None and remaining <= 0:
            raise AIError("budget reached")
        result = self.backend.run(model=model, effort=effort, system=self.system,
                                  prompt=prompt, image=image, budget_usd=remaining)
        self.budget.add(result.cost_usd)
        self.cache.put(k, asdict(result))
        return result, False

    def _page(self, job: _Job, file_key: str) -> tuple[str, PageResult]:
        r = job.report
        res = PageResult(r.page, r.route, r.reasons)
        best: tuple[float, str] | None = None
        models = self._models(r.route)
        for i, model in enumerate(models):
            effort = self._effort("escalate" if i else r.route)
            try:
                result, cached = self._call(job, r.route, model, effort, file_key)
            except AIError as e:
                res.error = str(e)
                break
            md = verify.clean_output(result.markdown)
            score, problems = verify.score(md, job.draft, job.trusted)
            if result.confidence == "low":
                problems.append("model unsure" + (f": {result.notes}" if result.notes else ""))
            res.cost_usd += 0 if cached else result.cost_usd
            if best is None or score >= best[0]:
                best = (score, md)
                res.source = "cache" if cached else "ai"
                res.model, res.score, res.confidence = model, score, result.confidence
                res.notes, res.problems = result.notes, problems
                res.error = ""
            if score >= self.s.ai.routing.min_verify_score and result.confidence != "low":
                break
            if i + 1 < len(models):
                self.log(f"  page {r.page + 1}: {model} scored {score:.2f} ({'; '.join(problems)}), "
                         f"retrying with {models[i + 1]}")
        if best is None:
            return job.draft, res
        return best[1], res

    # -- whole document ---------------------------------------------------

    def convert(self, path: Path) -> tuple[str, dict]:
        s = self.s
        doc = pymupdf.open(path)
        if doc.needs_pass:
            raise ValueError("PDF is password-protected")
        reports = triage(doc, s)
        engine = resolve_engine(doc, s.pdf.engine, s.ocr.lang)
        ai_pages = [r for r in reports if r.route != "local"]

        # Local OCR of scans the AI will transcribe is wasted work: skip it,
        # and only run it if the AI fails on one of them.
        scans_to_ai = any(r.scanned and r.route == "transcribe" for r in reports)
        ocr = "never" if scans_to_ai and s.ocr.mode == "auto" else s.ocr.mode
        local = lambda ocr_mode: pdf_pages(path, engine=engine, ocr=ocr_mode, lang=s.ocr.lang,
                                           ocr_dpi=s.ocr.dpi, spacing=s.pdf.fix_spacing)
        drafts = local(ocr)

        jobs = []
        for r in ai_pages:
            image = None
            if r.route != "polish":
                image = render_page_png(doc[r.page], s.ai.image_dpi, s.ai.image_max_side)
            jobs.append(_Job(r, drafts[r.page], image, trusted=r.route != "transcribe", pages=len(doc)))

        file_key = cache_mod.file_hash(path)
        out = list(drafts)
        results = {r.page: PageResult(r.page, r.route, r.reasons) for r in reports}
        if jobs:
            self.log(f"{path.name}: {len(jobs)} of {len(doc)} page(s) to AI")
        with ThreadPoolExecutor(max_workers=s.ai.concurrency) as pool:
            futures = {pool.submit(self._page, j, file_key): j for j in jobs}
            for done, fut in enumerate(as_completed(futures), 1):
                job = futures[fut]
                md, res = fut.result()
                out[job.report.page], results[job.report.page] = md, res
                self.log(_progress_line(done, len(jobs), res))

        failed_scans = [r.page for r in reports if r.scanned and results[r.page].source == "local"]
        if failed_scans and ocr != s.ocr.mode:
            self.log(f"  local OCR for page(s) {', '.join(str(p + 1) for p in failed_scans)}")
            ocr_drafts = local(s.ocr.mode)
            for p in failed_scans:
                out[p] = ocr_drafts[p]

        md = merge(out, s.pdf.page_markers)
        if not md.strip():
            raise ValueError(no_text_message(s.ocr.lang))
        report = {
            "file": str(path),
            "engine": engine,
            "pages": [{**asdict(reports[i]), **asdict(results[i])} for i in range(len(doc))],
            "ai_pages": len(jobs),
            "fallbacks": sum(1 for j in jobs if results[j.report.page].source == "local"),
            "cost_usd": round(sum(r.cost_usd for r in results.values()), 4),
        }
        return md, report


def _progress_line(done: int, total: int, res: PageResult) -> str:
    if res.source == "local":
        status = f"kept local draft ({res.error or 'no result'})"
    else:
        status = f"{res.model} score {res.score:.2f}"
        status += " (cached)" if res.source == "cache" else f" ${res.cost_usd:.3f}"
        if res.problems:
            status += f"  ! {'; '.join(res.problems)}"
    return f"  [{done}/{total}] page {res.page + 1:<4} {res.route:<10} {status}"


def stderr_log(msg: str):
    print(msg, file=sys.stderr, flush=True)
