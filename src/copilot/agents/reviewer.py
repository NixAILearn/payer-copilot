"""The compliance reviewer: checks a specialist's draft against its evidence.

It calls no tools. It returns a ReviewVerdict (passed, reasons) through
structured output. Three rules, from the design:
1. Every factual claim traces to a tool result or a cited passage.
2. No coverage approval or denial is stated as final.
3. No medical advice.

Before the model judges, plain code looks up every ID, code, date and amount
in the draft in the full evidence (check_facts). Finding an exact date in a
long list is a lookup code always gets right and a small model often misses.
The model then judges only what code could not find, plus rules 2 and 3.
"""

import json
import re
import time
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from copilot import tracing
from copilot.common import today
from copilot.llm import ActionError, decide_structured
from copilot.schemas import ReviewVerdict

MAX_EVIDENCE_CHARS = 6000  # keeps the reviewer's prompt inside the context budget
MAX_ATTEMPTS = 2  # if the reviewer's own reply is invalid, it gets one more try
RETRY_NOTE = ("Your previous reply was cut off or invalid. Reply with the JSON verdict only, "
              "with at most one short reason per problem.")

# The kinds of facts code can look up exactly.
ID_PATTERN = re.compile(r"\b(?:CLM-\d+|M-\d+|PA-\d+|[A-Z]{2}-\d+|\d{5})\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
WORD_DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                       r" \d{1,2}, \d{4}\b")
AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def check_facts(draft: str, sources: str) -> tuple[list[str], list[str]]:
    """Look up each ID, code, date and $ amount from the draft in the sources.

    Returns (found, not_found). Dates written in words ("August 4, 2026")
    are compared as 2026-08-04, and $1,240.00 matches 1240.0.
    """
    numbers = {float(n) for n in NUMBER.findall(sources.replace(",", ""))}
    facts: list[tuple[str, bool]] = []
    for fact in ID_PATTERN.findall(draft) + ISO_DATE.findall(draft):
        facts.append((fact, fact in sources))
    for fact in WORD_DATE.findall(draft):
        iso = datetime.strptime(fact, "%B %d, %Y").date().isoformat()
        facts.append((fact, iso in sources))
    for match in AMOUNT.finditer(draft):
        facts.append((match.group(0), float(match.group(1).replace(",", "")) in numbers))
    found = list(dict.fromkeys(f for f, ok in facts if ok))  # dict.fromkeys drops repeats, keeps order
    not_found = list(dict.fromkeys(f for f, ok in facts if not ok))
    return found, not_found


SYSTEM_PROMPT = """You are the compliance reviewer for Acme Health Plan's operations copilot. You check a draft answer before an analyst sees it.

Check the draft against exactly three rules:
1. Every fact in the draft (amounts, dates, codes, limits, statuses, names) appears in the evidence. General wording and suggested next steps from the evidence are fine. A fact that is not in the evidence breaks this rule.
   Code has already looked up every ID, code, date and $ amount in the draft. Trust its two lists: never fail a fact on the "found" list. A fact on the "not found" list breaks this rule, unless the draft clearly works it out from the evidence (such as a total, or a date 60 days before today). Check other facts (names, statuses, limits, counts) against the evidence yourself.
   Conclusions worked out from evidence are fine when the facts they use are in the evidence: counting visits, the weeks between two dates, whether a date is within 60 days, or marking a criterion met, not met or unknown. Do not fail a draft over a judgement call; a person reviews those. But do fail a conclusion that the evidence contradicts, such as a count, a date range or a "not found" that leaves out records shown in the evidence.
   The same fact written another way counts as present: "August 4, 2026" is the same as "2026-08-04", and "$1,240" is the same as 1240.0.
2. The draft never makes a new coverage decision of its own, such as "this claim will be paid", "the member's MRI will be covered" or "this request is approved". Repeating the evidence is fine: "the claim was denied" or "these claims were paid" repeats the database, and "the Silver plan covers 30 PT visits" repeats a policy document. A recommendation for a person to review is also fine.
3. The draft gives no medical advice.

Saying the documents don't cover something is fine; it is not a fact that needs evidence.
Pass the draft if it follows all three rules. If it fails, give one short reason per problem, naming the rule and the words at fault.
"""


def review(question: str, draft: str, evidence: list[dict], run_id: str,
           notes: list[str] | None = None) -> ReviewVerdict:
    """Check one draft. Returns the verdict and writes it to the trace.

    notes are the saved member notes the specialist was shown. They count as
    evidence too, so "an appeal letter was already drafted" can pass.
    """
    evidence_text = json.dumps([{"tool": e["tool"], "result": e["result"]} for e in evidence])
    if len(evidence_text) > MAX_EVIDENCE_CHARS:
        evidence_text = evidence_text[:MAX_EVIDENCE_CHARS] + " ...(cut)"
    content = (f"Analyst's question:\n{question}\n\nDraft answer:\n{draft}\n\n"
               f"Evidence (tool results):\n{evidence_text or 'none'}")
    if notes:
        content += "\n\nEvidence (saved notes from earlier sessions):\n- " + "\n- ".join(notes)
    # The lookup uses the full evidence, not the cut text, plus the question and today's date.
    sources = " ".join([json.dumps(evidence), *(notes or []), question, today().isoformat()])
    found, not_found = check_facts(draft, sources)
    content += (f"\n\nChecked by code. Found in the evidence: {', '.join(found) or 'none'}."
                f"\nNot found in the evidence: {', '.join(not_found) or 'none'}.")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        step = max((s["step"] for s in tracing.read_run(run_id)), default=0) + 1
        start = time.perf_counter()
        # On the retry, the same prompt at temperature 0 would give the same
        # reply, so the retry note says what went wrong.
        text = content if attempt == 1 else f"{content}\n\n{RETRY_NOTE}"
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=text)]
        try:
            result = decide_structured(messages, ReviewVerdict, "reviewer")
        except ActionError as e:
            tracing.write_step(run_id, "reviewer", step, prompt=[{"role": "human", "content": text}],
                               raw_output=e.raw, error=str(e), latency_s=round(time.perf_counter() - start, 2))
            if attempt == MAX_ATTEMPTS:
                raise
            continue
        tracing.write_step(run_id, "reviewer", step, prompt=[{"role": "human", "content": text}],
                           raw_output=result.raw, action="review", arguments=result.data,
                           input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                           latency_s=result.latency_s)
        return ReviewVerdict.model_validate(result.data)
    raise AssertionError("unreachable")
