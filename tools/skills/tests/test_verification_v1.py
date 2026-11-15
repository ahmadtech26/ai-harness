"""Normalisation v1 (tools/verification/v1.py): its own self-test, and the owner's rules of 2026-11-14.

tools/verification sits outside this package's Docker build context (tools/skills), so the image's test stage skips
these; `uv run pytest -q` in tools/skills (a repository checkout) runs them."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

V1 = Path(__file__).resolve().parents[2] / 'verification' / 'v1.py'
pytestmark = pytest.mark.skipif(not V1.is_file(), reason='tools/verification/v1.py is not in this tree (Docker image)')


def _module():
    spec = importlib.util.spec_from_file_location('verification_v1', V1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_self_test_passes():
    run = subprocess.run([sys.executable, '-I', str(V1)], capture_output=True, text=True, encoding='utf-8')

    assert (run.returncode, run.stdout.strip()) == (0, 'v1 self-test ok'), run.stderr


def test_folds_no_letters_and_keeps_punctuation():
    v1 = _module()

    assert v1.v1('إذا أُبرم العقدُ') == 'إذا أبرم العقد'
    assert v1.compare('الهيئة', 'الهيئه') == (False, 'body')
    assert v1.compare('على', 'علي') == (False, 'body')
    assert v1.compare('والمحكمة', 'المحكمة') == (False, 'body')
    assert v1.compare('أ. يحق', 'أ- يحق') == (False, 'formatting')
    assert v1.compare('المادة (٥)', 'المادة (5)') == (True, None)
    assert v1.compare('النص\r\n\r\nالتالي', 'النص التالي') == (True, None)
