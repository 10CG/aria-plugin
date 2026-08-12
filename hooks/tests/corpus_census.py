#!/usr/bin/env python3
"""corpus_census.py -- authoritative counter for aria-plugin #128
(secret-guard-per-segment-evaluation, proposal.md SS6 / SC-18).

Covers TASK-008 (corpus/boundary counts), TASK-009 (13 credit-judgment
criteria + risky_patterns quantifier census), TASK-010 (spanning-pattern
family grouping + 28-branch coverage table).

Design constraints (see proposal.md SS6 and the task brief this script was
built from):
  * stdlib-only Python 3.
  * Matching engine is ALWAYS a real subprocess: `grep -E` for line/record
    semantics (what canonical `echo "$x" | grep -qE` and `_sg_line_match`
    both replicate), and real `bash -c '[[ ... =~ ... ]]'` for bash's
    whole-string ERE semantics. Python's `re` module is NEVER used to
    simulate POSIX ERE matching -- the dialects are not the same and the
    whole point of several SC's in this spec is that they differ on
    newline handling. `re` is used only for trivial literal-substring /
    line-shape bookkeeping that does not depend on ERE semantics.
  * The 13 credit-judgment regex strings and the risky_patterns array are
    extracted mechanically from source text (or via real bash evaluation
    for array elements) -- never hand-transcribed into this script.

Run: python3 hooks/tests/corpus_census.py [--hook PATH] [--corpus PATH] [--human]
Output: one JSON object on stdout (stable top-level keys: corpus, criteria,
patterns, families, branches, meta). Optional --human summary on stderr.
Exit code: 0 always for a completed run; non-zero only on structural
extraction failure (e.g. criteria site_count != 13), per proposal.md SC-18
("13 处判据行号清单恰 13 条, 否则 census 以非零退出并输出诊断").
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ============================================================================
# Path resolution
# ============================================================================

def default_hook_path() -> Path:
    return Path(__file__).resolve().parent.parent / 'secret-guard.sh'


def default_corpus_path() -> Path:
    return Path(__file__).resolve().parent / 'secret-guard.test.sh'


# ============================================================================
# Subprocess-backed matching engines (never simulate POSIX ERE in python re)
# ============================================================================

def grep_qE(pattern: str, text: str) -> bool:
    """Replicate `printf '%s' "$text" | grep -qE "$pattern"` -- grep's own
    line/record semantics (grep reads the input as a stream of \n-separated
    records and reports a match if ANY record matches the whole pattern).
    This is exactly what canonical secret-guard.sh's `echo "$command" |
    grep -qE ...` and the new `_sg_line_match()` helper both replicate."""
    try:
        p = subprocess.run(['grep', '-qE', pattern], input=text,
                            text=True, capture_output=True)
        return p.returncode == 0
    except FileNotFoundError as e:
        raise RuntimeError(f'grep binary not found: {e}')


def bash_regex_match(pattern: str, text: str) -> bool:
    """Replicate `[[ "$text" =~ $pattern ]]` -- bash's own whole-string ERE
    semantics (glibc regexec called ONCE on the entire string; no
    REG_NEWLINE, so `.` and `[[:space:]]` cross embedded newlines and `^`/`$`
    anchor to the true start/end of the whole string, not per line).
    Pattern/text passed as argv (not interpolated into script text) to avoid
    any shell-quoting hazard."""
    script = 'p=$1; s=$2; [[ "$s" =~ $p ]]'
    p = subprocess.run(['bash', '-c', script, 'bash', pattern, text],
                        capture_output=True)
    return p.returncode == 0


def bash_eval_literal(source_literal: str) -> str:
    """Feed an exact bash string-literal (quotes included, e.g. the raw
    source text '"\\|...\\$..."' or "'\\|...'") through real bash and
    capture the evaluated string value via printf. This is how this script
    gets the "runtime value" of a double-quoted regex literal (bash
    resolves \\$ -> $, \\" -> ", etc. per its OWN double-quote escaping
    rules) without this script having to hand-reimplement those rules --
    delegate to the real interpreter instead of guessing."""
    script = 'printf %s ' + source_literal
    p = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f'bash failed evaluating literal {source_literal!r}: {p.stderr}')
    return p.stdout


def bash_eval_array_block(block_text: str, array_name: str) -> list:
    """Feed a `declare -a NAME=( ... )` block (or any bash source that
    defines the named array) through real bash and read back the evaluated
    elements, NUL-delimited. This is how risky_patterns's 141 elements are
    obtained -- real bash resolves the `'"'"'`-style embedded-quote tricks
    used inside some pattern strings, which a naive text scanner would get
    wrong."""
    script = block_text + f'\nprintf \'%s\\0\' "${{{array_name}[@]}}"\n'
    p = subprocess.run(['bash', '-c', script], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f'bash failed evaluating array block: {p.stderr.decode("utf-8", "replace")}')
    raw = p.stdout
    if raw.endswith(b'\x00'):
        raw = raw[:-1]
    if not raw:
        return []
    return [part.decode('utf-8', 'surrogateescape') for part in raw.split(b'\x00')]


# ============================================================================
# TASK-008: quote-aware top-level boundary scanner (pure python, NOT an ERE
# match -- a bespoke character-classification state machine per spec).
# ============================================================================

_ST_NORMAL, _ST_SQ, _ST_DQ, _ST_ANSI = range(4)


def scan_top_level_boundaries(cmd: str):
    """Quote-aware scan for TOP-LEVEL ';' '&&' '||' '|' boundary tokens.

    State machine (verbatim from the task's canonical spec):
      - escape `\\` (outside single-quotes) consumes the next character
      - single-quote: no escaping at all: literal until the next `'`
      - double-quote: `\\` consumes the next character
      - `$'...'` (ANSI-C quoting): `\\` consumes the next character

    Token rules at top level:
      `;`  -> single-char token
      `&&` -> two-char token (consumes both `&`)
      `||` -> two-char token (consumes both `|`)
      `|`  -> single-char token, whenever not part of `||`
              (this includes `|&`: the `|` still counts as a `|` token; the
              trailing `&` is then just an ordinary top-level character,
              itself not a boundary token per this scanner's token set)

    A bare `&` (not `&&`) is NOT a boundary token in this scanner's output
    (it matters elsewhere in the hook for background-job detection, but not
    for corpus_census's SS6 boundary counts). Real newline characters are
    likewise never emitted as tokens here -- the caller classifies
    newline-only commands separately.

    Returns: list of (token_str, start_index) in left-to-right order.
    """
    tokens = []
    i = 0
    n = len(cmd)
    state = _ST_NORMAL
    while i < n:
        c = cmd[i]
        if state == _ST_NORMAL:
            if c == '\\':
                i += 2
                continue
            if c == "'":
                state = _ST_SQ
                i += 1
                continue
            if c == '"':
                state = _ST_DQ
                i += 1
                continue
            if c == '$' and i + 1 < n and cmd[i + 1] == "'":
                state = _ST_ANSI
                i += 2
                continue
            if c == ';':
                tokens.append((';', i))
                i += 1
                continue
            if c == '&':
                if i + 1 < n and cmd[i + 1] == '&':
                    tokens.append(('&&', i))
                    i += 2
                    continue
                i += 1
                continue
            if c == '|':
                if i + 1 < n and cmd[i + 1] == '|':
                    tokens.append(('||', i))
                    i += 2
                    continue
                tokens.append(('|', i))
                i += 1
                continue
            i += 1
        elif state == _ST_SQ:
            if c == "'":
                state = _ST_NORMAL
            i += 1
        elif state == _ST_DQ:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                state = _ST_NORMAL
            i += 1
        elif state == _ST_ANSI:
            if c == '\\':
                i += 2
                continue
            if c == "'":
                state = _ST_NORMAL
            i += 1
        else:
            raise AssertionError('unreachable state')
    return tokens


# ============================================================================
# TASK-008: extract the 305 bash_case (name, want, cmd) triples via real bash
# ============================================================================

def extract_bash_cases(corpus_path: Path):
    """Text-extract every source line starting with `bash_case "` (each
    invocation is confirmed to live on a single physical line -- verified:
    grep count of `^bash_case "` == grep count of `bash_case "` == 305, so
    there is no line where the call is embedded mid-line or split across
    lines), wrap them with a stub `bash_case()` that NUL-serializes its 3
    args, and run the result through a real bash process. This lets bash
    itself resolve quoting/`$'...'`-ANSI-C-escapes/etc. exactly as it would
    for the real test run, without touching any of the file's OTHER
    top-level code (hook invocations, temp-file setup, zsh/CRLF probes,
    etc.) -- those are simply never included in the extraction script."""
    text = corpus_path.read_text(encoding='utf-8')
    lines = text.split('\n')
    case_lines = [ln for ln in lines if ln.startswith('bash_case "')]
    stub = "bash_case() { printf '%s\\x00%s\\x00%s\\x00' \"$1\" \"$2\" \"$3\"; }\n"
    script = stub + '\n'.join(case_lines) + '\n'
    p = subprocess.run(['bash', '-c', script], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(
            f'bash_case extraction script failed (rc={p.returncode}): '
            f'{p.stderr.decode("utf-8", "replace")}')
    raw = p.stdout
    if raw.endswith(b'\x00'):
        raw = raw[:-1]
    parts = raw.split(b'\x00') if raw else []
    if len(parts) % 3 != 0:
        raise RuntimeError(
            f'bash_case extraction produced {len(parts)} NUL-fields, not a '
            f'multiple of 3 -- extraction is corrupt')
    triples = []
    for k in range(0, len(parts), 3):
        name = parts[k].decode('utf-8', 'surrogateescape')
        want = parts[k + 1].decode('utf-8', 'surrogateescape')
        cmdv = parts[k + 2].decode('utf-8', 'surrogateescape')
        triples.append((name, want, cmdv))
    if len(triples) != len(case_lines):
        raise RuntimeError(
            f'extracted {len(triples)} triples but found {len(case_lines)} '
            f'bash_case source lines -- mismatch')
    return triples


def classify_corpus(triples):
    with_boundary = []   # (name, want, cmd, tokens)
    newline_only = []    # (name, want, cmd)
    neither = []         # (name, want, cmd)
    for name, want, cmd in triples:
        tokens = scan_top_level_boundaries(cmd)
        if tokens:
            with_boundary.append((name, want, cmd, tokens))
        elif '\n' in cmd:
            newline_only.append((name, want, cmd))
        else:
            neither.append((name, want, cmd))
    return with_boundary, newline_only, neither


def build_corpus_section(triples):
    with_boundary, newline_only, neither = classify_corpus(triples)

    exp2 = [(n, w, c, t) for (n, w, c, t) in with_boundary if w == '2']
    exp0 = [(n, w, c, t) for (n, w, c, t) in with_boundary if w == '0']
    pure_pipe = [(n, w, c, t) for (n, w, c, t) in exp0
                 if all(tok[0] == '|' for tok in t)]
    true_boundary = [(n, w, c, t) for (n, w, c, t) in exp0
                      if not all(tok[0] == '|' for tok in t)]

    nl_blocked = [(n, w, c) for (n, w, c) in newline_only if w == '2']
    nl_allowed = [(n, w, c) for (n, w, c) in newline_only if w == '0']

    def names(seq):
        return [n for (n, *_rest) in seq]

    return {
        'total_bash_case': len(triples),
        'with_top_boundary': len(with_boundary),
        'boundary_expected_2': len(exp2),
        'boundary_expected_2_names': names(exp2),
        'boundary_expected_0': len(exp0),
        'boundary_expected_0_names': names(exp0),
        'pure_pipe': len(pure_pipe),
        'pure_pipe_names': names(pure_pipe),
        'true_boundary': len(true_boundary),
        'true_boundary_names': names(true_boundary),
        'newline_boundary': len(newline_only),
        'newline_boundary_names': names(newline_only),
        'newline_boundary_blocked': len(nl_blocked),
        'newline_boundary_blocked_names': names(nl_blocked),
        'newline_boundary_allowed': len(nl_allowed),
        'newline_boundary_allowed_names': names(nl_allowed),
        'neither_count': len(neither),
    }


# ============================================================================
# TASK-009 (first half): the 13 credit-judgment lines -- dual-form extraction
# ============================================================================

def _skip_quoted_literal(text: str, i: int):
    """text[i] must be a quote char (\' or "). Return (content_without_quotes,
    index_just_past_closing_quote). Single-quote: no escaping, ends at the
    very next \'. Double-quote: `\\` consumes the next char (does not end
    the string), ends at the first unescaped `"`. Byte-for-byte, no
    de-escaping performed here -- this is the "raw source literal" content
    (spec: 逐字节取出, 不做任何反转义)."""
    q = text[i]
    n = len(text)
    j = i + 1
    buf = []
    if q == "'":
        while j < n and text[j] != "'":
            buf.append(text[j])
            j += 1
        if j >= n:
            raise RuntimeError(f'unterminated single-quoted literal starting at {i}')
        return ''.join(buf), j + 1
    else:  # double quote
        while j < n:
            if text[j] == '\\' and j + 1 < n:
                buf.append(text[j])
                buf.append(text[j + 1])
                j += 2
                continue
            if text[j] == '"':
                return ''.join(buf), j + 1
            buf.append(text[j])
            j += 1
        raise RuntimeError(f'unterminated double-quoted literal starting at {i}')


def _find_first_quote_after(line: str, start: int):
    """Return index of the first \' or " at/after `start`, or None."""
    for k in range(start, len(line)):
        if line[k] in ("'", '"'):
            return k
    return None


def _extract_regex_from_line(line: str, trigger_end: int):
    """Given a line and the index right after a recognized trigger prefix
    (e.g. right after 'grep -qE ' or right after '_sg_line_match '), locate
    the first quoted string and extract it. Returns
    (quote_char, raw_source_literal_with_quotes, raw_content_no_quotes) or
    None if no quote found immediately (defensive; should not happen for
    well-formed lines matched by the caller's trigger regex)."""
    qidx = _find_first_quote_after(line, trigger_end)
    if qidx is None:
        return None
    content, end = _skip_quoted_literal(line, qidx)
    raw_literal = line[qidx:end]
    return line[qidx], raw_literal, content


def extract_criteria_form_b(hook_lines):
    """Form B (post-refactor): find `_sg_compute_credit()` function body
    (definition line to its matching standalone-`}` close), then within it
    find lines matching `^[[:space:]]*if _sg_line_match ` and extract the
    first quoted string after the trigger (the regex argument -- verified
    against the actual TASK-007 calling convention `_sg_line_match <re>
    "$seg"`, where <re> is the FIRST argument)."""
    func_start = None
    for idx, ln in enumerate(hook_lines):
        if ln.lstrip().startswith('_sg_compute_credit()') or \
           ln.lstrip().startswith('_sg_compute_credit ()'):
            func_start = idx
            break
    if func_start is None:
        return []
    func_end = None
    for idx in range(func_start + 1, len(hook_lines)):
        if hook_lines[idx].strip() == '}':
            func_end = idx
            break
    if func_end is None:
        return []
    results = []
    trigger = 'if _sg_line_match '
    for idx in range(func_start, func_end + 1):
        ln = hook_lines[idx]
        stripped = ln.lstrip()
        if stripped.startswith(trigger):
            trigger_end = len(ln) - len(stripped) + len(trigger)
            extracted = _extract_regex_from_line(ln, trigger_end)
            if extracted is None:
                continue
            quote_char, raw_literal, raw_content = extracted
            results.append({
                'line': idx + 1,  # 1-indexed
                'quote_char': quote_char,
                'raw_source_literal': raw_literal,
                'raw_content': raw_content,
            })
    return results


def extract_criteria_form_a(hook_lines):
    """Form A (canonical): lines strictly between the first 'Filter
    detection' banner and the first 'Risky read patterns' banner matching
    `^if echo "\\$command" \\| grep -qE `."""
    s_idx = None
    e_idx = None
    for idx, ln in enumerate(hook_lines):
        if 'Filter detection' in ln:
            s_idx = idx
            break
    if s_idx is not None:
        for idx in range(s_idx + 1, len(hook_lines)):
            if 'Risky read patterns' in hook_lines[idx]:
                e_idx = idx
                break
    if s_idx is None or e_idx is None:
        return []
    prefix = 'if echo "$command" | grep -qE '
    results = []
    for idx in range(s_idx + 1, e_idx):
        ln = hook_lines[idx]
        if ln.startswith(prefix):
            trigger_end = len(prefix)
            extracted = _extract_regex_from_line(ln, trigger_end)
            if extracted is None:
                continue
            quote_char, raw_literal, raw_content = extracted
            results.append({
                'line': idx + 1,
                'quote_char': quote_char,
                'raw_source_literal': raw_literal,
                'raw_content': raw_content,
            })
    return results


def compute_runtime_value(entry):
    """Get the value grep/_sg_line_match would ACTUALLY receive at runtime:
    single-quoted source -> identical to raw_content (bash never processes
    escapes inside single quotes); double-quoted source -> ask real bash to
    evaluate the exact raw_source_literal (quotes included) via printf, so
    this script never hand-reimplements bash's `\\$`/`\\"`/`\\\\` escaping
    rules (verified empirically during design: e.g. line-332-class judgments
    have `\\$` in source that bash's OWN double-quote evaluation turns into
    a bare, unescaped `$` anchor -- byte-for-byte source extraction would
    misrepresent this as a literal dollar sign if fed directly to grep)."""
    if entry['quote_char'] == "'":
        return entry['raw_content']
    return bash_eval_literal(entry['raw_source_literal'])


def build_criteria_regexes(hook_path: Path):
    hook_lines = hook_path.read_text(encoding='utf-8').split('\n')
    form_b = extract_criteria_form_b(hook_lines)
    if form_b:
        extraction_form = 'B'
        entries = form_b
    else:
        extraction_form = 'A'
        entries = extract_criteria_form_a(hook_lines)
    for e in entries:
        e['runtime_value'] = compute_runtime_value(e)
    return extraction_form, entries


def build_criteria_section(hook_path: Path):
    extraction_form, entries = build_criteria_regexes(hook_path)
    site_lines = [e['line'] for e in entries]
    site_count = len(site_lines)

    space_plus = sum(1 for e in entries if '[[:space:]]+' in e['raw_content'])
    space_star = sum(1 for e in entries if '[[:space:]]*' in e['raw_content'])
    space_any = sum(1 for e in entries if '[[:space:]]' in e['raw_content'])

    newline = compute_newline_affected(entries)

    return {
        'extraction_form': extraction_form,
        'site_lines': site_lines,
        'site_count': site_count,
        'regexes': [
            {
                'line': e['line'],
                'quote_char': e['quote_char'],
                'raw_content': e['raw_content'],
                'runtime_value': e['runtime_value'],
            }
            for e in entries
        ],
        'space_plus': space_plus,
        'space_star': space_star,
        'space_any': space_any,
        'newline_affected': newline,
    }, entries, site_count


# ============================================================================
# TASK-009: newline_affected -- hand-derived per-judgment witnesses
# ============================================================================
# Methodology (documented here because this is the one sub-metric the spec
# explicitly flags as historically disputed -- v5 said 11, R5 tech-lead said
# 12, R5-fix said 13, and the spec explicitly permits this script to land on
# a DIFFERENT number as long as it is reported honestly with methodology,
# rather than forced to match):
#
# For each of the 13 judgments, a minimal "spine" witness command fragment
# is hand-built from the judgment's RUNTIME-VALUE regex (see
# compute_runtime_value): every MANDATORY `[[:space:]]+` occurrence and
# every `[[:space:]]*` occurrence that sits directly on the regex's main
# alternative path (not buried inside a wholly-optional sub-group, e.g. the
# jq `(-flag)*` flag group or the jq `(.+\|...)?` pipe-prefix group are
# skipped -- using zero repetitions of an optional group is itself a valid
# way to satisfy the regex, so skipping them does not make the witness
# invalid, it just means THOSE inner occurrences are not exercised by this
# script's injection test). This is a real, disclosed coverage limitation,
# not a hidden one.
#
# Each witness is built as a list of parts where whitespace positions are
# tagged placeholders (not literal characters), so this script always knows
# the EXACT index of each `[[:space:]]` occurrence it is testing:
#   strict baseline: '*'-tagged slots -> '' (zero chars); '+'-tagged -> ' '
#                     (one space, the quantifier's minimum)
#   loose baseline:  ALL slots -> ' ' (one explicit space, even where '*'
#                     would allow zero) -- this directly generalizes the
#                     spec's own named example (`cat x >/dev/null` strict vs
#                     `cat x > /dev/null` loose for the stdout-discard
#                     judgment, which is witness #9 below, verbatim)
#
# For each tagged slot, one mutant per baseline style is built by replacing
# JUST that slot with a single real newline `\n` (all other slots keep
# their strict/loose baseline form). The mutant is tested against the
# judgment's runtime-value regex via both `grep -qE` (line/record semantics)
# and `bash [[ =~ ]]` (whole-string semantics, where `[[:space:]]` DOES
# match the injected `\n`). A verdict difference marks that occurrence
# newline-sensitive; a judgment counts toward the affected total for a given
# baseline if ANY of its tested occurrences is sensitive under that style.
#
# Every witness is self-verified (both strict and loose forms must actually
# match the judgment's own regex via grep -qE) before being used -- if a
# hand-built witness fails self-verification (e.g. because Phase B later
# edits the regex text, which the whole spec otherwise forbids -- "13 处正则
# 文本一个字节不动" -- but this script must not silently produce garbage if
# it ever happens), that judgment is excluded from the affected counts and
# flagged in `witness_errors` instead of guessed at.

LIT = 'lit'
SP = 'sp'

# Keyed by 1-based POSITION INDEX in ascending-line-number extraction order
# (stable across form A/B and across line-number drift, since the 13
# judgments' relative order has been unchanged across every version of this
# spec: jq-keys, jq-brace, grep-anchor, grep-invert, sed, cut, awk-$N,
# awk-/regex/, stdout-discard, &>-discard, curl-output, wc, checksum-tools).
CREDIT_WITNESS_SPEC = {
    1: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'jq'), (SP, 'c', '+'),
        (LIT, 'keys'), (SP, 'e', '*'), (LIT, '')],
    2: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'jq'), (SP, 'c', '+'), (LIT, '{')],
    3: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'grep'), (SP, 'c', '+'), (LIT, '^')],
    4: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'grep'), (SP, 'c', '+'), (LIT, '-v')],
    5: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'sed'), (SP, 'c', '+'), (LIT, 's//')],
    6: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'cut'), (SP, 'c', '+'), (LIT, '-d'),
        (SP, 'e', '*'), (LIT, 'x')],
    7: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'awk'), (SP, 'c', '+'), (LIT, '"$0')],
    8: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'awk'), (SP, 'c', '+'), (LIT, '"/x/')],
    9: [(LIT, '>'), (SP, 'e', '*'), (LIT, '/dev/null')],
    10: [(LIT, '&>'), (SP, 'e', '*'), (LIT, '/dev/null')],
    11: [(LIT, '-o'), (SP, 'x', '+'), (LIT, '/dev/null')],
    12: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'wc'), (SP, 'c', '+'), (LIT, '-l')],
    13: [(LIT, '|'), (SP, 'a', '*'), (LIT, 'sha256sum')],
}


def _render_witness(spec, style):
    """style: 'strict' (star->'', plus->' ') or 'loose' (all -> ' ').
    Returns (rendered_string, [(tag, quant, start_index, filled_len), ...])
    so callers know exactly where each slot landed."""
    parts = []
    slots = []
    pos = 0
    for item in spec:
        if item[0] == LIT:
            parts.append(item[1])
            pos += len(item[1])
        else:
            _, tag, quant = item
            if style == 'strict':
                fill = '' if quant == '*' else ' '
            else:
                fill = ' '
            slots.append((tag, quant, pos, len(fill)))
            parts.append(fill)
            pos += len(fill)
    return ''.join(parts), slots


def _inject_newline(rendered, slots, slot_index):
    """Replace the slot at slot_index with a single '\\n', leave all other
    slots at their rendered (strict/loose) form."""
    tag, quant, start, flen = slots[slot_index]
    return rendered[:start] + '\n' + rendered[start + flen:]


def compute_newline_affected(entries):
    strict_affected = []
    loose_affected = []
    witness_errors = []
    detail = []

    for idx, entry in enumerate(entries, start=1):
        regex = entry['runtime_value']
        spec = CREDIT_WITNESS_SPEC.get(idx)
        if spec is None:
            witness_errors.append({
                'index': idx, 'line': entry['line'],
                'error': 'no hand-derived witness spec for this position index'
                         ' (extractor found a 14th+ line, or ordering shifted)'})
            continue

        strict_str, strict_slots = _render_witness(spec, 'strict')
        loose_str, loose_slots = _render_witness(spec, 'loose')

        if not grep_qE(regex, strict_str):
            witness_errors.append({
                'index': idx, 'line': entry['line'], 'style': 'strict',
                'witness': strict_str,
                'error': 'hand-built strict witness does NOT match its own '
                         'judgment regex via grep -qE -- self-verification '
                         'failed, excluding from affected counts'})
            continue
        if not grep_qE(regex, loose_str):
            witness_errors.append({
                'index': idx, 'line': entry['line'], 'style': 'loose',
                'witness': loose_str,
                'error': 'hand-built loose witness does NOT match its own '
                         'judgment regex via grep -qE -- self-verification '
                         'failed, excluding from affected counts'})
            continue

        per_occurrence = []
        this_strict_affected = False
        for k, (tag, quant, start, flen) in enumerate(strict_slots):
            mutant = _inject_newline(strict_str, strict_slots, k)
            g = grep_qE(regex, mutant)
            b = bash_regex_match(regex, mutant)
            diverged = (g != b)
            if diverged:
                this_strict_affected = True
            per_occurrence.append({
                'style': 'strict', 'slot': tag, 'quantifier': quant,
                'mutant': mutant, 'grep_match': g, 'bash_match': b,
                'diverged': diverged,
            })
        this_loose_affected = False
        for k, (tag, quant, start, flen) in enumerate(loose_slots):
            mutant = _inject_newline(loose_str, loose_slots, k)
            g = grep_qE(regex, mutant)
            b = bash_regex_match(regex, mutant)
            diverged = (g != b)
            if diverged:
                this_loose_affected = True
            per_occurrence.append({
                'style': 'loose', 'slot': tag, 'quantifier': quant,
                'mutant': mutant, 'grep_match': g, 'bash_match': b,
                'diverged': diverged,
            })

        if this_strict_affected:
            strict_affected.append(entry['line'])
        if this_loose_affected:
            loose_affected.append(entry['line'])
        detail.append({
            'index': idx, 'line': entry['line'],
            'strict_witness': strict_str, 'loose_witness': loose_str,
            'strict_affected': this_strict_affected,
            'loose_affected': this_loose_affected,
            'occurrences': per_occurrence,
        })

    return {
        'methodology': (
            "Per-judgment hand-derived 'spine' witness (skips wholly-optional "
            "sub-groups, e.g. jq's (-flag)* / (.+\\|...)? groups -- using zero "
            "repetitions of an optional group is a valid way to satisfy the "
            "regex, so those inner [[:space:]] occurrences are not exercised "
            "by this script; see module docstring near CREDIT_WITNESS_SPEC). "
            "strict = '*'-quantified slots rendered as 0 chars, '+'-quantified "
            "as 1 space; loose = all slots rendered as 1 space (generalizes "
            "the spec's own 'cat x >/dev/null' vs 'cat x > /dev/null' example, "
            "which is judgment #9 verbatim). For each slot, inject a single "
            "real newline in place of that slot's rendered spacing and compare "
            "grep -qE (line semantics) vs bash [[ =~ ]] (whole-string "
            "semantics, glibc regex without REG_NEWLINE); a verdict "
            "difference marks the occurrence newline-sensitive. A judgment "
            "counts as affected under a baseline style if ANY tested "
            "occurrence is sensitive under that style. Witnesses are "
            "self-verified against their own judgment regex via grep -qE "
            "before use; failures are excluded from the counts and reported "
            "in witness_errors instead."
        ),
        'strict': {
            'baseline_string': 'cat x >/dev/null',
            'baseline_description': "optional [[:space:]] slots rendered with 0 chars",
            'affected_count': len(strict_affected),
            'affected_lines': strict_affected,
        },
        'loose': {
            'baseline_string': 'cat x > /dev/null',
            'baseline_description': "all [[:space:]] slots rendered with 1 space",
            'affected_count': len(loose_affected),
            'affected_lines': loose_affected,
        },
        'witness_errors': witness_errors,
        'detail': detail,
    }


# ============================================================================
# TASK-009 (second half) / TASK-010: risky_patterns array extraction
# ============================================================================

def locate_risky_patterns_block(hook_lines):
    start = None
    for idx, ln in enumerate(hook_lines):
        if 'declare -a risky_patterns=(' in ln:
            start = idx
            break
    if start is None:
        raise RuntimeError("could not locate 'declare -a risky_patterns=(' in hook file")
    end = None
    for idx in range(start + 1, len(hook_lines)):
        if hook_lines[idx].strip() == ')':
            end = idx
            break
    if end is None:
        raise RuntimeError("could not locate closing ')' line for risky_patterns array")
    return start, end


def build_patterns_and_source_counts(hook_path: Path):
    hook_lines = hook_path.read_text(encoding='utf-8').split('\n')
    start, end = locate_risky_patterns_block(hook_lines)
    block_text = '\n'.join(hook_lines[start:end + 1])

    # -- source-line quote-style census (textual property of the block,
    #    independent of bash evaluation) --
    single_q = 0
    double_q = 0
    other_lines = []
    for idx in range(start + 1, end):
        stripped = hook_lines[idx].strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith("'"):
            single_q += 1
        elif stripped.startswith('"'):
            double_q += 1
        else:
            other_lines.append({'line': idx + 1, 'text': hook_lines[idx]})

    # -- bash-evaluated elements (authoritative for all quantifier/backslash
    #    census below; see module docstring) --
    elements = bash_eval_array_block(block_text, 'risky_patterns')

    contains_backslash_b = sum(1 for e in elements if '\\b' in e)
    bracket_pipe = sum(1 for e in elements if '[^|]' in e)
    bracket_pipe_star = sum(1 for e in elements if '[^|]*' in e)
    bracket_pipe_plus = sum(1 for e in elements if '[^|]+' in e)
    both = sum(1 for e in elements if '[^|]*' in e and '[^|]+' in e)
    dot_star = sum(1 for e in elements if '.*' in e)

    patterns_section = {
        'source_single_quoted': single_q,
        'source_double_quoted': double_q,
        'source_other_lines': other_lines,
        'total': len(elements),
        'contains_backslash_b': contains_backslash_b,
        'bracket_pipe': bracket_pipe,
        'bracket_pipe_star': bracket_pipe_star,
        'bracket_pipe_plus': bracket_pipe_plus,
        'both': both,
        'dot_star': dot_star,
    }
    return patterns_section, elements, (start, end)


# ============================================================================
# TASK-010: families -- key extraction on the bash-evaluated pattern text
# ============================================================================

def skip_bracket_expr(s: str, i: int) -> int:
    """s[i] == '['. Return index just past the matching ']', treating POSIX
    named classes / collating symbols / equivalence classes ([:xxx:],
    [.xxx.], [=xxx=]) as atomic so an embedded ']' inside one of those does
    not prematurely close the bracket expression."""
    n = len(s)
    assert s[i] == '['
    j = i + 1
    if j < n and s[j] == '^':
        j += 1
    if j < n and s[j] == ']':
        j += 1
    while j < n:
        if s[j] == '[' and j + 1 < n and s[j + 1] in ':.=':
            marker = s[j + 1]
            end = s.find(marker + ']', j + 2)
            if end == -1:
                j += 1
                continue
            j = end + 2
            continue
        if s[j] == ']':
            return j + 1
        j += 1
    return j  # unterminated -- return end of string defensively


def skip_group(s: str, i: int) -> int:
    """s[i] == '('. Return index just past the matching ')', treating
    escaped parens as literal and bracket expressions as atomic (so a
    literal '(' or ')' inside a `[...]` char class, e.g. `[;&|(){]`, does
    not perturb the paren-depth count)."""
    n = len(s)
    assert s[i] == '('
    depth = 1
    j = i + 1
    while j < n and depth > 0:
        c = s[j]
        if c == '\\' and j + 1 < n:
            j += 2
            continue
        if c == '[':
            j = skip_bracket_expr(s, j)
            continue
        if c == '(':
            depth += 1
            j += 1
            continue
        if c == ')':
            depth -= 1
            j += 1
            continue
        j += 1
    return j


def strip_position_prefix(p: str) -> str:
    """Strip a leading bare `^` or a leading `(^|...)` alternation group
    (the position-anchor idiom used throughout risky_patterns, e.g.
    `(^|[;&|(){]|`|[[:cntrl:]])`)."""
    if p.startswith('^'):
        return p[1:]
    if p.startswith('('):
        end = skip_group(p, 0)
        inner = p[1:end - 1]
        if inner == '^' or inner.startswith('^|'):
            return p[end:]
    return p


def strip_leading_blank_class(p: str) -> str:
    """Strip one leading `[[:blank:]]` or `[[:space:]]` occurrence (with its
    optional trailing quantifier `* + ?`) -- the "剥掉 ... [[:blank:]]*/
    [[:space:]]* 类" step of the family key rule."""
    for cls in ('[[:blank:]]', '[[:space:]]'):
        if p.startswith(cls):
            j = len(cls)
            if j < len(p) and p[j] in '*+?':
                j += 1
            return p[j:]
    return p


def extract_family_key(original_pattern: str) -> str:
    """Apply proposal.md 转出1 / A.2-task-brief's key convention:
      1. strip a leading position-anchor prefix (`^` or `(^|...)`)
      2. strip one leading [[:blank:]]*/[[:space:]]* occurrence
      3. if what remains starts with '(' (an alternation group), the WHOLE
         group (verbatim) is the key, spelled `GRP:(...)`.
      4. otherwise take the longest run of literal characters (escaped
         metachars `\\X` decode to literal X, EXCEPT `\\b` which is a
         zero-width word-boundary and stops the run rather than
         contributing a literal 'b') until hitting an unescaped regex
         metachar or a `[[:space:]]`/`[[:blank:]]` class.
      5. if that run is empty (no literal fragment at all right at the
         front), the key is the pattern's own original full text, prefixed
         `EMPTY:` for legibility, guaranteeing each such pattern is its own
         singleton family (spec: "完全无字面片段者各自成族, key = 原文")."""
    p = strip_position_prefix(original_pattern)
    p = strip_leading_blank_class(p)

    if p.startswith('('):
        end = skip_group(p, 0)
        return 'GRP:' + p[0:end]

    j = 0
    n = len(p)
    buf = []
    metachars = set('.^$*+?()[]|')
    while j < n:
        c = p[j]
        if c == '\\' and j + 1 < n:
            nxt = p[j + 1]
            if nxt == 'b':
                break  # word-boundary assertion -- zero width, stop here
            buf.append(nxt)  # escaped literal, e.g. \. \| \$ \{ \^
            j += 2
            continue
        if c in metachars:
            break
        buf.append(c)
        j += 1
    token = ''.join(buf)
    if token:
        return token
    return 'EMPTY:' + original_pattern


SPANNING_GROUPING_CONVENTION = (
    "Spanning set = bash-evaluated risky_patterns elements containing literal "
    "'[^|]' (any quantifier) OR literal '.*'. Family key derivation, applied "
    "to each spanning element's ORIGINAL (unstripped) text: (1) strip a "
    "leading position-anchor prefix -- bare '^' or a '(^|...)' alternation "
    "group whose first alternative is literally '^'; (2) strip one leading "
    "[[:blank:]]*/[[:space:]]* occurrence; (3) if an alternation group '(' "
    "starts what remains, the WHOLE group verbatim is the key, spelled "
    "'GRP:(...)'; (4) else take the longest run of literal characters "
    "(escaped metachars decode to their literal char, e.g. '\\.' -> '.', "
    "EXCEPT '\\b' which is zero-width and stops the run) until a regex "
    "metachar or a [[:space:]]/[[:blank:]] class; (5) if that run is empty, "
    "the key is the pattern's own full original text (prefixed 'EMPTY:'), "
    "so each such pattern is its own singleton family. This mechanically "
    "resolves guard-class / no-literal-token patterns (e.g. '/v1/var/', "
    "'169\\.254\\.169\\.254', 'hvs\\.[A-Za-z0-9]{24,}') by their own leading "
    "literal fragment (escaped dots decode to literal '.') without any "
    "hand-curated exception list -- any 55-vs-56-style boundary case this "
    "produces is a direct, inspectable consequence of these five steps, "
    "visible in family_table."
)


def build_families_section(elements):
    spanning = [(i, e) for i, e in enumerate(elements) if '[^|]' in e or '.*' in e]
    family_table = {}
    for i, e in spanning:
        key = extract_family_key(e)
        family_table.setdefault(key, []).append(i)

    return {
        'spanning_total': len(spanning),
        'grouping_convention': SPANNING_GROUPING_CONVENTION,
        'family_count': len(family_table),
        'family_table': family_table,
    }, spanning


# ============================================================================
# TASK-010: 28-branch alternation coverage table (hand-derived isolating
# regexes, per proposal.md SC-15 dimension-2 table, keyed by 1-based
# criterion position index -- same ordering rationale as CREDIT_WITNESS_SPEC)
# ============================================================================
# Each isolating regex is derived BY HAND from the judgment's runtime-value
# regex by narrowing its alternation group to exactly one branch (or, for
# the two non-alternating single-branch judgments #7/#8, the isolating
# regex IS the parent regex -- there is nothing to narrow). Where narrowing
# to a bare literal risks an accidental SUBSTRING match against a sibling
# branch (e.g. "paths" is a literal substring of "leaf_paths"), a `\b`
# word-boundary is added specifically to prevent that cross-attribution;
# this is noted per-entry below. The one INTENTIONAL exception is the
# `[Dd]` branch of judgment #5, which proposal.md explicitly documents as
# "accidentally" covered by any corpus command containing an unrelated
# literal 'd'/'D' (e.g. "REDACTED") -- no `\b` is added there because that
# accidental-hit behavior is the spec's own documented expectation, not a
# bug this table should paper over.

BRANCH_TABLE_SPEC = [
    # judgment #1 -- jq safe-expression (keys/length/paths/leaf_paths)
    (1, 'keys', r'\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+["\']?(.+\|[[:space:]]*)?(keys)["\']?[[:space:]]*($|\|)'),
    (1, 'length', r'\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+["\']?(.+\|[[:space:]]*)?(length)["\']?[[:space:]]*($|\|)'),
    # 'paths' is a literal substring of 'leaf_paths' -- \b prevents a
    # leaf_paths corpus command from being mis-attributed to the 'paths'
    # branch via substring containment.
    (1, 'paths', r'\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+["\']?(.+\|[[:space:]]*)?(\bpaths\b)["\']?[[:space:]]*($|\|)'),
    (1, 'leaf_paths', r'\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+["\']?(.+\|[[:space:]]*)?(leaf_paths)["\']?[[:space:]]*($|\|)'),
    # judgment #2 -- jq brace-projection (no alternation; single branch)
    (2, '{', r'\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+["\']?\{'),
    # judgment #3 -- grep anchor char class [\^\$]
    (3, '^', r'\|[[:space:]]*grep([[:space:]]+-[a-zA-Z]+)*[[:space:]]+[^[:space:]]*\^'),
    (3, '$', r'\|[[:space:]]*grep([[:space:]]+-[a-zA-Z]+)*[[:space:]]+[^[:space:]]*\$'),
    # judgment #4 -- grep -v / --invert-match
    (4, '-v', r'\|[[:space:]]*grep[[:space:]]+(-v)\b'),
    (4, '--invert-match', r'\|[[:space:]]*grep[[:space:]]+(--invert-match)\b'),
    # judgment #5 -- sed branches: [Ss]/.../ lower, [Ss]/.../ upper, [0-9]+d, [Dd]
    (5, '[Ss]/.../lower-s', r'\|[[:space:]]*sed[[:space:]]+[^[:space:]]*(s/[^/]*/)'),
    (5, '[Ss]/.../upper-S', r'\|[[:space:]]*sed[[:space:]]+[^[:space:]]*(S/[^/]*/)'),
    (5, '[0-9]+d', r'\|[[:space:]]*sed[[:space:]]+[^[:space:]]*([0-9]+d)'),
    # [Dd]: intentionally NOT word-boundaried -- proposal.md documents this
    # branch as legitimately/accidentally hit by any 'd'/'D' char in the
    # matched segment (e.g. the 'd' in "REDACTED"); that is the spec's own
    # expected behavior for this specific branch, not a defect to suppress.
    (5, '[Dd]', r'\|[[:space:]]*sed[[:space:]]+[^[:space:]]*([Dd])'),
    # judgment #6 -- cut -d / -f
    (6, '-d', r'\|[[:space:]]*cut[[:space:]]+-(d)[[:space:]]*[^[:space:]-]'),
    (6, '-f', r'\|[[:space:]]*cut[[:space:]]+-(f)[[:space:]]*[^[:space:]-]'),
    # judgment #7 -- awk $N (no alternation; single branch = parent itself)
    (7, '$N', r'\|[[:space:]]*awk[[:space:]]+[\'"][^\'"]*\$[0-9]'),
    # judgment #8 -- awk /regex/ (no alternation; single branch = parent itself)
    (8, '/regex/', r'\|[[:space:]]*awk[[:space:]]+[\'"][^\'"]*/[^/]+/'),
    # judgment #9 -- stdout discard (no alternation; single branch = parent itself)
    (9, 'stdout-discard', r'([^0-9&]|^)>[[:space:]]*/dev/null'),
    # judgment #10 -- &> discard (no alternation; single branch = parent itself)
    (10, '&>-discard', r'&>[[:space:]]*/dev/null'),
    # judgment #11 -- curl -o / --output
    (11, '-o', r'(-o[[:space:]]+/dev/null)'),
    (11, '--output', r'(--output[[:space:]]+/dev/null)'),
    # judgment #12 -- wc -l / -c / -w
    (12, '-l', r'\|[[:space:]]*wc[[:space:]]+-(l)'),
    (12, '-c', r'\|[[:space:]]*wc[[:space:]]+-(c)'),
    (12, '-w', r'\|[[:space:]]*wc[[:space:]]+-(w)'),
    # judgment #13 -- checksum tool alternation
    (13, 'sha256sum', r'\|[[:space:]]*(sha256sum)\b'),
    (13, 'md5sum', r'\|[[:space:]]*(md5sum)\b'),
    (13, 'sha1sum', r'\|[[:space:]]*(sha1sum)\b'),
    (13, 'sha512sum', r'\|[[:space:]]*(sha512sum)\b'),
]


def build_branches_section(criteria_entries, corpus_triples):
    # criteria_entries is ordered by ascending line number == position index
    index_to_entry = {i + 1: e for i, e in enumerate(criteria_entries)}

    # Perf: several branches share the same parent judgment (e.g. all 4
    # jq-alternation branches share judgment #1's parent regex). Precompute
    # each DISTINCT criterion's parent-match subset of the corpus ONCE
    # (13 x 305 grep calls total) instead of once per branch row (28 x 305)
    # -- then each branch only re-tests its isolating regex against that
    # criterion's (usually much smaller) subset instead of the full 305,
    # instead of the naive 28 x 305 x 2 approach. Semantics are identical to
    # "先用父判据正则过滤该命令命中者, 再用隔离正则确认经该分支命中" --
    # only the redundant repeated parent-filtering is removed.
    parent_match_cache = {}
    for crit_idx in sorted({spec[0] for spec in BRANCH_TABLE_SPEC}):
        entry = index_to_entry.get(crit_idx)
        if entry is None:
            parent_match_cache[crit_idx] = []
            continue
        parent_regex = entry['runtime_value']
        parent_match_cache[crit_idx] = [
            (name, want, cmd) for (name, want, cmd) in corpus_triples
            if grep_qE(parent_regex, cmd)
        ]

    branch_table = []
    zero_coverage = 0
    for crit_idx, branch_label, isolating_regex in BRANCH_TABLE_SPEC:
        entry = index_to_entry.get(crit_idx)
        parent_line = entry['line'] if entry else None
        candidates = parent_match_cache.get(crit_idx, [])
        hits = [name for (name, want, cmd) in candidates if grep_qE(isolating_regex, cmd)]
        coverage = 'covered' if hits else 'zero'
        if coverage == 'zero':
            zero_coverage += 1
        branch_table.append({
            'criterion_index': crit_idx,
            'criterion_line': parent_line,
            'branch': branch_label,
            'isolating_regex': isolating_regex,
            'corpus_hits': hits,
            'coverage': coverage,
        })
    return {
        'total_branches': len(BRANCH_TABLE_SPEC),
        'branch_table': branch_table,
        'zero_coverage_count': zero_coverage,
    }


# ============================================================================
# Main
# ============================================================================

def main():
    ap = argparse.ArgumentParser(
        description='Authoritative census counter for aria-plugin #128 '
                     '(secret-guard-per-segment-evaluation, SC-18).')
    ap.add_argument('--hook', type=Path, default=None,
                     help='override path to secret-guard.sh')
    ap.add_argument('--corpus', type=Path, default=None,
                     help='override path to secret-guard.test.sh')
    ap.add_argument('--human', action='store_true',
                     help='also print a human-readable summary to stderr')
    args = ap.parse_args()

    hook_path = args.hook or default_hook_path()
    corpus_path = args.corpus or default_corpus_path()

    if not hook_path.is_file():
        print(f'corpus_census: hook path not found: {hook_path}', file=sys.stderr)
        sys.exit(1)
    if not corpus_path.is_file():
        print(f'corpus_census: corpus path not found: {corpus_path}', file=sys.stderr)
        sys.exit(1)

    diagnostics = []
    exit_code = 0

    # ---- TASK-008: corpus ----
    triples = extract_bash_cases(corpus_path)
    corpus_section = build_corpus_section(triples)

    # ---- TASK-009: criteria + patterns ----
    criteria_section, criteria_entries, site_count = build_criteria_section(hook_path)
    if site_count != 13:
        diagnostics.append(
            f'criteria.site_count == {site_count}, expected exactly 13 -- '
            f'extraction did not find the 13 canonical credit judgments '
            f'(extraction_form={criteria_section["extraction_form"]!r}); '
            f'see criteria.site_lines for what WAS found')
        exit_code = 1

    patterns_section, pattern_elements, _block_span = build_patterns_and_source_counts(hook_path)

    # ---- TASK-010: families + branches ----
    families_section, _spanning = build_families_section(pattern_elements)
    branches_section = build_branches_section(criteria_entries, triples)

    meta_section = {
        'hook_path': str(hook_path),
        'corpus_path': str(corpus_path),
        'extraction_form': criteria_section['extraction_form'],
        'corpus_case_count': len(triples),
        'note': (
            'Authoritative counter for aria-plugin #128 '
            '(secret-guard-per-segment-evaluation). All ERE matching is done '
            'via real subprocess grep -E / bash [[ =~ ]] -- never simulated '
            'in python re. Dual-form criteria extraction: tries form B '
            '(_sg_compute_credit()/_sg_line_match, post-refactor) first, '
            'falls back to form A (canonical grep -qE loop) if form B is '
            'absent.'
        ),
        'diagnostics': diagnostics,
    }

    output = {
        'corpus': corpus_section,
        'criteria': criteria_section,
        'patterns': patterns_section,
        'families': families_section,
        'branches': branches_section,
        'meta': meta_section,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=False))

    if args.human:
        print_human_summary(output, file=sys.stderr)

    if diagnostics:
        for d in diagnostics:
            print(f'corpus_census: DIAGNOSTIC: {d}', file=sys.stderr)

    sys.exit(exit_code)


def print_human_summary(output, file):
    c = output['corpus']
    cr = output['criteria']
    p = output['patterns']
    f = output['families']
    b = output['branches']
    m = output['meta']
    lines = []
    lines.append('=' * 70)
    lines.append('corpus_census.py -- human summary')
    lines.append('=' * 70)
    lines.append(f"hook: {m['hook_path']}  (form {m['extraction_form']})")
    lines.append(f"corpus: {m['corpus_path']}  ({m['corpus_case_count']} bash_case)")
    lines.append('')
    lines.append('-- corpus (TASK-008) --')
    lines.append(f"with_top_boundary: {c['with_top_boundary']} "
                  f"(want=2: {c['boundary_expected_2']}, want=0: {c['boundary_expected_0']} "
                  f"[pure_pipe {c['pure_pipe']} + true_boundary {c['true_boundary']}])")
    lines.append(f"newline_boundary: {c['newline_boundary']} "
                  f"(blocked {c['newline_boundary_blocked']} + allowed {c['newline_boundary_allowed']})")
    lines.append('')
    lines.append('-- criteria (TASK-009) --')
    lines.append(f"site_count: {cr['site_count']}  site_lines: {cr['site_lines']}")
    lines.append(f"space_plus: {cr['space_plus']}  space_star: {cr['space_star']}  space_any: {cr['space_any']}")
    na = cr['newline_affected']
    lines.append(f"newline_affected strict: {na['strict']['affected_count']}/13  "
                 f"loose: {na['loose']['affected_count']}/13  "
                 f"(witness_errors: {len(na['witness_errors'])})")
    lines.append('')
    lines.append('-- patterns (TASK-009) --')
    lines.append(f"total: {p['total']} (single {p['source_single_quoted']} + double {p['source_double_quoted']})")
    lines.append(f"contains_backslash_b: {p['contains_backslash_b']}  bracket_pipe: {p['bracket_pipe']} "
                 f"(star {p['bracket_pipe_star']} / plus {p['bracket_pipe_plus']} / both {p['both']})  "
                 f"dot_star: {p['dot_star']}")
    lines.append('')
    lines.append('-- families (TASK-010) --')
    lines.append(f"spanning_total: {f['spanning_total']}  family_count: {f['family_count']}")
    lines.append('')
    lines.append('-- branches (TASK-010) --')
    lines.append(f"total_branches: {b['total_branches']}  zero_coverage_count: {b['zero_coverage_count']}")
    print('\n'.join(lines), file=file)


if __name__ == '__main__':
    main()
