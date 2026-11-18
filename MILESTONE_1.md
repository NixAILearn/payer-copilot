# Milestone 1: Synthetic data

**Goal:** one seeded script builds the whole fake health plan: a SQLite database and 10 policy documents. **Check:** row counts match the design and the planted demo cases exist.

## 1. The one new file

`data/generate.py` (full contents at the end). In plain words, it:

1. **Holds the reference data at the top**, written by hand: 3 plans with their costs and visit limits, 27 procedure codes and 12 diagnosis codes with our own short descriptions, 6 denial codes, and 15 prior auth rules with their criteria checklists. Read this part first; it's the "business rules" of Acme Health Plan.
2. **Generates the bulk rows** with a random generator seeded with 42: 200 members, 40 providers, 1,500 claims (with claim lines) and 60 prior auth requests. Same seed means the same data every run, so test answers never change.
3. **Plants the demo cases** by hand, so the stories have known right answers (table below).
4. **Writes 10 Markdown policy documents** into `data/policies/`. The numbers in them (deductibles, visit limits, criteria) come from the same Python values as the database, so the documents and the tables can't disagree.
5. **Checks itself** and prints a scorecard: row counts, planted cases, Silver PT limit in both table and document, and the `is_synthetic` flag on every row.

Some choices worth knowing:

- **Denials are made consistent with the data.** A CO-197 (no prior auth) denial is only put on a procedure that needs prior auth, a CO-242 (out of network) only on an out-of-network provider, and a CO-29 (timely filing) only when the claim arrived more than 90 days after the service.
- **Money is simplified.** Allowed is 60% of billed, and the plan pays allowed minus the member's coinsurance. The yearly deductible is not tracked claim by claim. The docstring says so, and it goes in the README's limits in milestone 7.
- **All dates are relative to a fixed "today", 15 Nov 2026,** so a member who is active today stays active when you rerun it next month.
- **Structured facts go in the database, prose goes in the documents.** Claims, members and rules live in tables that tools will query. Only the policy text will go into the vector index (milestone 4).
- **IDs:** members run M-00101 to M-00300 so that the design's M-00217 exists, and claims run CLM-10001 to CLM-11500 so that CLM-10482 exists.

## 2. Planted demo cases

| Story | Planted data | Right answer later |
| --- | --- | --- |
| 1. Claim denial explained | CLM-10482: member M-00142 (Silver, active), lower spine MRI 72148, 12 Sep 2026, billed $1,240.00, denied CO-197 | Denied for missing prior auth. Next steps: retro authorization within 30 days, or appeal within 180 days (imaging policy and appeals procedure). |
| 2. Coverage question | Silver plan: 30 physical therapy visits per year, in both the `plans` table and `silver_coverage_summary.md` | Covered, 30 visits per year, citing the Silver coverage summary. Acupuncture appears in no document, so you can test the "documents are silent" case. |
| 3. Prior auth pre-check | M-00217 (Silver, active): 8 weekly PT visits from 4 Aug, a knee X-ray on 20 Oct, an orthopedics visit on 3 Nov, no knee MRI, no earlier auth requests | Knee MRI 73721 needs prior auth on Silver. Its 5 criteria can be checked against this history. |
| Eval case | M-00250 (Gold), eligibility ended 30 Jun 2026 | Lapsed coverage. |

## 3. Commands

```bash
cd ~/Projects/payer-copilot
uv run python data/generate.py
```

Expected output:

```text
Wrote payer.db and policies/ (all data is synthetic)

Row counts:
  [OK] plans                3 (design: 3)
  [OK] members              200 (design: 200)
  [OK] providers            40 (design: 40)
  [OK] claims               1500 (design: 1500)
  [OK] denial_codes         6 (design: 6)
  [OK] prior_auth_requests  60 (design: 60)
  [OK] auth rule procedures 15 (design: 15)
  [OK] procedure+diag codes 39 (design: about 30)
  [OK] denied share         20.9% (design: about 20%)
  [OK] denial reasons used  6 (design: 6)
  [OK] policy documents     10 (design: 10)
  [OK] is_synthetic flags   11 tables, all rows flagged
Planted demo cases:
  [OK] story 1: CLM-10482 denied CO-197 ('M-00142', 'denied', 'CO-197', 1240.0)
  [OK] story 2: Silver PT limit in table and doc agree 30 visits
  [OK] story 3: M-00217 active Silver, knee MRI needs auth, X-ray on file ('Silver', None)
  [OK] eval: M-00250 lapsed 2026-06-30

Milestone 1 check: PASSED
```

Your numbers should match exactly, including 20.9%, because the data is seeded.

### Look inside the database

macOS comes with `sqlite3`. Try these, one at a time:

```bash
sqlite3 -header -column data/payer.db "SELECT * FROM claims WHERE claim_id = 'CLM-10482';"
sqlite3 -header -column data/payer.db "SELECT * FROM claim_lines WHERE claim_id = 'CLM-10482';"
sqlite3 -header -column data/payer.db "SELECT * FROM denial_codes;"
sqlite3 -header -column data/payer.db "SELECT claim_id, service_date, status FROM claims WHERE member_id = 'M-00217';"
sqlite3 -header -column data/payer.db "SELECT * FROM auth_criteria WHERE procedure_code = '73721';"
sqlite3 -header -column data/payer.db "SELECT status, COUNT(*) FROM claims GROUP BY status;"
```

`.tables` inside `sqlite3 data/payer.db` lists every table; `.quit` leaves. If you prefer clicking, the free app "DB Browser for SQLite" opens the same file.

### Read the documents

```bash
ls data/policies
open data/policies/silver_coverage_summary.md
```

**The check passes** when the script ends with `Milestone 1 check: PASSED` and you've opened the database and read one policy document. If anything shows FAIL or an error, send me the full text.

## 4. Check your understanding

1. Why do claims, members and rules live in SQLite while the policy documents become Markdown files? What would go wrong if we put the claims table into the vector index instead?
2. The script uses a fixed seed and a fixed "today". What would break in the tests if either one changed on every run?
3. Claim CLM-10482 is denied CO-197. Which table and which document would a correct answer use to explain it, and what makes the documents and tables agree with each other?

Then add your 5 lines under Milestone 1 in `LEARNINGS.md`.

## 5. Full contents of `data/generate.py`

````python
"""Generate all synthetic data for Payer Copilot.

Run:  uv run python data/generate.py

It writes two things next to this file:
- payer.db        a SQLite database with plans, members, providers, claims,
                  denial codes, prior auth rules and prior auth requests
- policies/*.md   10 plan and policy documents (prose, for RAG later)

Everything is made up. The random generator is seeded, so every run gives
exactly the same data. A few rows are hand-written ("planted") so the demo
stories have known right answers. The script ends by checking row counts,
planted cases and doc-versus-table consistency, and prints the result.
"""

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

SEED = 42
DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "payer.db"
POLICY_DIR = DATA_DIR / "policies"

# All dates are relative to this fixed "today", so eligibility never drifts.
TODAY = date(2026, 11, 15)
YEAR_START = date(2026, 1, 1)
TIMELY_FILING_DAYS = 90
APPEAL_DAYS = 180

BANNER = "> Synthetic document for Acme Health Plan, a fictional payer. Not real coverage information."

# ---------------------------------------------------------------- reference data

PLANS = {
    # plan_id: deductible, coinsurance, out-of-pocket max, visit limits per year
    "Bronze": {"deductible": 7000, "coinsurance": 40, "oop_max": 9200, "pt_visits": 20, "chiro_visits": 0, "specialist_copay": 90},
    "Silver": {"deductible": 4000, "coinsurance": 30, "oop_max": 8000, "pt_visits": 30, "chiro_visits": 12, "specialist_copay": 60},
    "Gold": {"deductible": 1500, "coinsurance": 20, "oop_max": 6000, "pt_visits": 40, "chiro_visits": 20, "specialist_copay": 40},
}

# Procedure codes with our own short descriptions (not official descriptor text).
# code: (description, category, typical billed amount)
PROCEDURES = {
    "99203": ("New patient office visit", "office", 180),
    "99213": ("Follow-up office visit, routine", "office", 130),
    "99214": ("Follow-up office visit, more complex", "office", 190),
    "80053": ("Blood chemistry panel", "lab", 60),
    "85025": ("Complete blood count", "lab", 35),
    "83036": ("Blood sugar control test (A1c)", "lab", 45),
    "71046": ("Chest X-ray, two views", "imaging", 120),
    "73562": ("Knee X-ray, three views", "imaging", 140),
    "72148": ("MRI of the lower spine", "imaging", 1240),
    "73721": ("MRI of the knee", "imaging", 1150),
    "70450": ("CT scan of the head", "imaging", 900),
    "74177": ("CT scan of the abdomen and pelvis", "imaging", 1600),
    "78815": ("PET scan, skull base to mid-thigh", "imaging", 4200),
    "97161": ("Physical therapy evaluation", "physical_therapy", 160),
    "97110": ("Physical therapy exercise session", "physical_therapy", 95),
    "97140": ("Physical therapy hands-on treatment", "physical_therapy", 85),
    "98940": ("Chiropractic spine adjustment", "chiropractic", 70),
    "29881": ("Knee arthroscopy with cartilage trim", "surgery", 6800),
    "27447": ("Total knee replacement", "surgery", 32000),
    "63030": ("Lower back disc surgery", "surgery", 21000),
    "43239": ("Upper endoscopy with biopsy", "surgery", 2100),
    "45378": ("Screening colonoscopy", "surgery", 1900),
    "95810": ("Overnight sleep study in a lab", "sleep", 2600),
    "E0601": ("CPAP breathing machine", "equipment", 950),
    "J0135": ("Adalimumab injection (specialty drug)", "specialty_drug", 5800),
    "J1745": ("Infliximab infusion (specialty drug)", "specialty_drug", 4700),
    "J9035": ("Bevacizumab infusion (specialty drug)", "specialty_drug", 7400),
}

# Diagnosis codes with our own short descriptions.
DIAGNOSES = {
    "M25.561": "Right knee pain",
    "M17.11": "Wear-and-tear arthritis, right knee",
    "M54.50": "Low back pain",
    "M51.26": "Lower back disc problem",
    "E11.9": "Type 2 diabetes",
    "I10": "High blood pressure",
    "J45.909": "Asthma",
    "G47.33": "Obstructive sleep apnea",
    "K21.9": "Acid reflux",
    "M06.9": "Rheumatoid arthritis",
    "R51.9": "Headache",
    "Z00.00": "Routine adult checkup",
}

# Denial codes modeled on standard adjustment reasons, with our own wording.
# code: (short name, plain meaning, usual next step, share of denials)
DENIAL_CODES = {
    "CO-197": ("No prior authorization", "The service needed prior authorization and none was on file.", "Provider can request a retro authorization or the member can appeal with medical records.", 0.25),
    "CO-50": ("Not medically necessary", "The plan's review found the service was not medically necessary for the diagnosis given.", "Appeal with a letter of medical necessity and supporting records.", 0.20),
    "CO-29": ("Timely filing", f"The claim reached the plan more than {TIMELY_FILING_DAYS} days after the service date.", "Provider can appeal only with proof the claim was sent on time.", 0.15),
    "PR-1": ("Deductible", "The amount counts toward the member's deductible, so the member owes it.", "No appeal needed; the member pays the provider directly.", 0.15),
    "CO-97": ("Bundled service", "The service is included in the payment for another service on the same day.", "Usually no action; provider can appeal if the services were separate.", 0.15),
    "CO-242": ("Out of network", "The provider is not in the member's network and the plan has no out-of-network benefit.", "Member can appeal if no in-network provider was available.", 0.10),
}

# Prior auth rules: 15 procedures. "plans" lists plans where auth is required.
# Each has a 3 to 5 item criteria checklist, used by both the DB and the docs.
AUTH_RULES = {
    "72148": (["Bronze", "Silver", "Gold"], "imaging", ["Low back pain for at least 6 weeks", "At least 6 weeks of conservative treatment (physical therapy or medication) tried", "Neurological symptoms such as leg weakness or numbness, or a red-flag finding", "No MRI of the lower spine in the past 12 months"]),
    "73721": (["Bronze", "Silver", "Gold"], "imaging", ["Knee pain for at least 6 weeks", "At least 6 weeks of conservative treatment (physical therapy or medication) tried", "Knee X-ray done within the past 60 days", "Ordered by an in-network provider", "No MRI of the same knee in the past 12 months"]),
    "70450": (["Bronze", "Silver"], "imaging", ["New or worsening headache with a neurological finding, or recent head injury", "Ordered after an in-person exam", "No head CT in the past 30 days"]),
    "74177": (["Bronze", "Silver"], "imaging", ["Abdominal symptoms not explained by lab tests or ultrasound", "Ordered after an in-person exam", "No abdominal CT in the past 90 days"]),
    "78815": (["Bronze", "Silver", "Gold"], "imaging", ["Confirmed or strongly suspected cancer diagnosis", "Result will change the treatment plan", "Ordered by an oncologist"]),
    "29881": (["Bronze", "Silver", "Gold"], "surgery", ["MRI shows a cartilage tear", "Mechanical symptoms such as locking or catching", "At least 6 weeks of physical therapy tried"]),
    "27447": (["Bronze", "Silver", "Gold"], "surgery", ["X-ray shows severe arthritis of the knee", "Pain limits daily activities", "At least 3 months of conservative treatment tried", "No active infection"]),
    "63030": (["Bronze", "Silver", "Gold"], "surgery", ["MRI shows a disc problem that matches the symptoms", "At least 6 weeks of conservative treatment tried", "Ongoing leg pain or weakness"]),
    "43239": (["Bronze", "Silver"], "surgery", ["Symptoms for at least 4 weeks despite medication", "Ordered by a gastroenterologist", "Patient age or warning signs support the procedure"]),
    "95810": (["Bronze", "Silver"], "sleep", ["Home sleep test was not possible or was inconclusive", "Symptoms such as loud snoring or daytime sleepiness", "Ordered after an in-person exam"]),
    "E0601": (["Bronze", "Silver"], "equipment", ["Sleep study confirms sleep apnea", "Member agrees to a 90-day use check", "Ordered by the treating provider"]),
    "J0135": (["Bronze", "Silver", "Gold"], "specialty_drug", ["Diagnosis of rheumatoid arthritis or another approved condition", "Tried at least one standard medication first", "Negative tuberculosis screening in the past 12 months", "Prescribed by a rheumatologist or other specialist"]),
    "J1745": (["Bronze", "Silver", "Gold"], "specialty_drug", ["Diagnosis of an approved inflammatory condition", "Tried at least one standard medication first", "Negative tuberculosis screening in the past 12 months"]),
    "J9035": (["Bronze", "Silver", "Gold"], "specialty_drug", ["Confirmed cancer diagnosis for an approved use", "Prescribed by an oncologist", "Treatment plan attached", "Recent lab results attached"]),
    "97110": ([], "physical_therapy", ["Visits are within the plan's yearly limit", "Visits beyond the limit need a progress note showing improvement", "Ordered by a treating provider"]),
}

FIRST_NAMES = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Quinn", "Rowan", "Harper", "Emerson", "Sawyer",
               "Reese", "Dakota", "Skyler", "Parker", "Finley", "Hayden", "Logan", "Kendall", "Peyton", "Blake",
               "Marisol", "Tobias", "Ingrid", "Desmond", "Priya", "Mateo", "Yuki", "Amara", "Lennart", "Noor"]
LAST_NAMES = ["Calloway", "Brightwater", "Ashford", "Penhallow", "Vantreese", "Okonkwo-Lane", "Marchetti",
              "Thornbury", "Delacroix", "Quillfeather", "Sandoval-Reyes", "Holloway", "Fairbanks", "Westergaard",
              "Lindqvist", "Abernathy", "Castellano", "Whitlock", "Ravenscroft", "Kowalczyk"]
PROVIDER_NAMES = ["Riverbend", "Maple Grove", "Harborview", "Summit Ridge", "Cedar Point", "Lakeshore",
                  "Pinecrest", "Northgate", "Willow Creek", "Stonebridge"]
SPECIALTIES = ["Family Medicine", "Orthopedics", "Radiology", "Physical Therapy", "Gastroenterology",
               "Rheumatology", "Oncology", "Sleep Medicine", "Chiropractic", "Internal Medicine"]

# ---------------------------------------------------------------- schema

SCHEMA = """
CREATE TABLE plans (
    plan_id TEXT PRIMARY KEY, deductible INTEGER, coinsurance_pct INTEGER, oop_max INTEGER,
    pt_visit_limit INTEGER, chiro_visit_limit INTEGER, specialist_copay INTEGER,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE members (
    member_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, date_of_birth TEXT,
    plan_id TEXT REFERENCES plans(plan_id), eligibility_start TEXT, eligibility_end TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE providers (
    provider_id TEXT PRIMARY KEY, name TEXT, specialty TEXT, in_network INTEGER,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE procedures (
    procedure_code TEXT PRIMARY KEY, description TEXT, category TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE diagnoses (
    diagnosis_code TEXT PRIMARY KEY, description TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE denial_codes (
    code TEXT PRIMARY KEY, name TEXT, meaning TEXT, next_step TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY, member_id TEXT REFERENCES members(member_id),
    provider_id TEXT REFERENCES providers(provider_id), service_date TEXT, received_date TEXT,
    status TEXT CHECK (status IN ('paid', 'denied', 'pending')),
    billed_amount REAL, allowed_amount REAL, paid_amount REAL, member_owes REAL,
    denial_code TEXT REFERENCES denial_codes(code),
    is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE claim_lines (
    claim_id TEXT REFERENCES claims(claim_id), line_no INTEGER,
    procedure_code TEXT REFERENCES procedures(procedure_code),
    diagnosis_code TEXT REFERENCES diagnoses(diagnosis_code), units INTEGER, billed_amount REAL,
    is_synthetic INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (claim_id, line_no));
CREATE TABLE auth_rules (
    procedure_code TEXT REFERENCES procedures(procedure_code), plan_id TEXT REFERENCES plans(plan_id),
    auth_required INTEGER, policy_document TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (procedure_code, plan_id));
CREATE TABLE auth_criteria (
    procedure_code TEXT REFERENCES procedures(procedure_code), item_no INTEGER, criterion TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (procedure_code, item_no));
CREATE TABLE prior_auth_requests (
    auth_id TEXT PRIMARY KEY, member_id TEXT REFERENCES members(member_id),
    procedure_code TEXT REFERENCES procedures(procedure_code), request_date TEXT,
    status TEXT CHECK (status IN ('pending', 'approved', 'denied')),
    recommendation TEXT, rationale TEXT, decided_by TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1);
"""

# Policy document file for each auth rule category.
POLICY_FOR_CATEGORY = {
    "imaging": "prior_auth_imaging.md",
    "surgery": "prior_auth_imaging.md",  # this document covers imaging and other procedures
    "sleep": "prior_auth_imaging.md",
    "equipment": "prior_auth_imaging.md",
    "specialty_drug": "prior_auth_specialty_drugs.md",
    "physical_therapy": "prior_auth_physical_therapy.md",
}

# ---------------------------------------------------------------- generators


def rand_date(rng: random.Random, start: date, end: date) -> date:
    """A random date between start and end, inclusive."""
    return start + timedelta(days=rng.randint(0, (end - start).days))


def make_members(rng: random.Random) -> list[tuple]:
    """200 members, M-00101 to M-00300. About 10% have lapsed eligibility."""
    rows = []
    for n in range(101, 301):
        member_id = f"M-{n:05d}"
        plan = rng.choices(list(PLANS), weights=[3, 5, 2])[0]
        dob = rand_date(rng, date(1950, 1, 1), date(2004, 12, 31))
        start = rand_date(rng, date(2022, 1, 1), date(2025, 12, 1))
        end = rand_date(rng, date(2026, 3, 1), date(2026, 10, 31)) if rng.random() < 0.10 else None
        rows.append([member_id, rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES), dob.isoformat(),
                     plan, start.isoformat(), end.isoformat() if end else None])
    planted = {
        "M-00142": ["Silver", "2024-01-01", None],   # demo story 1: owner of claim CLM-10482
        "M-00217": ["Silver", "2023-05-01", None],   # demo story 3: knee MRI pre-check
        "M-00250": ["Gold", "2022-02-01", "2026-06-30"],  # eval case: lapsed eligibility
    }
    for row in rows:
        if row[0] in planted:
            row[4], row[5], row[6] = planted[row[0]]
    return [tuple(r) for r in rows]


def make_providers(rng: random.Random) -> list[tuple]:
    """40 providers, about 1 in 5 out of network."""
    rows = []
    for n in range(1, 41):
        specialty = SPECIALTIES[(n - 1) % len(SPECIALTIES)]
        name = f"{PROVIDER_NAMES[(n - 1) // 4]} {specialty}"
        in_network = 0 if rng.random() < 0.2 else 1
        if n in (2, 3, 4):  # providers used by the planted demo claims are in network
            in_network = 1
        rows.append((f"P-{n:03d}", name, specialty, in_network))
    return rows


def make_claims(rng: random.Random, members: list[tuple], providers: list[tuple]) -> tuple[list, list]:
    """1,500 claims, CLM-10001 to CLM-11500, about 20% denied.

    Planted members get only their planted claims, so their history is exact.
    Each denial reason is paired with data that makes it true: CO-197 only on
    procedures that need auth, CO-242 only on out-of-network providers, CO-29
    only when the claim arrived after the filing limit.
    """
    planted_members = {"M-00142", "M-00217"}
    random_members = [m for m in members if m[0] not in planted_members]
    in_net = [p for p in providers if p[3] == 1]
    out_net = [p for p in providers if p[3] == 0]
    plan_of = {m[0]: m[4] for m in members}
    auth_codes = [c for c, rule in AUTH_RULES.items() if rule[0]]
    common_codes = [c for c in PROCEDURES if c not in auth_codes]
    diag_codes = list(DIAGNOSES)
    denial_list = list(DENIAL_CODES)
    denial_weights = [DENIAL_CODES[c][3] for c in denial_list]

    claims, lines = [], []
    planted_ids = {"CLM-10482"} | {f"CLM-{n}" for n in range(11491, 11501)}
    for n in range(10001, 11501):
        claim_id = f"CLM-{n}"
        if claim_id in planted_ids:
            continue
        member = rng.choice(random_members)
        status = rng.choices(["paid", "denied", "pending"], weights=[72, 20, 8])[0]
        denial = rng.choices(denial_list, weights=denial_weights)[0] if status == "denied" else None
        provider = rng.choice(out_net if denial == "CO-242" else in_net)
        main_code = rng.choice(auth_codes if denial == "CO-197" else common_codes)
        service = rand_date(rng, YEAR_START, TODAY - timedelta(days=5))
        delay = rng.randint(TIMELY_FILING_DAYS + 5, TIMELY_FILING_DAYS + 60) if denial == "CO-29" else rng.randint(2, 40)
        if denial == "CO-29":
            service = rand_date(rng, YEAR_START, date(2026, 7, 1))
        received = min(service + timedelta(days=delay), TODAY)

        codes = [main_code]
        if rng.random() < 0.4:
            codes.append(rng.choice(["99213", "80053", "85025"]))
        claim_lines = []
        for line_no, code in enumerate(codes, start=1):
            billed = round(PROCEDURES[code][2] * rng.uniform(0.9, 1.15), 2)
            claim_lines.append((claim_id, line_no, code, rng.choice(diag_codes), 1, billed))
        billed_total = round(sum(line[5] for line in claim_lines), 2)
        claims.append(price_claim(claim_id, member[0], provider[0], service, received,
                                  status, billed_total, denial, plan_of[member[0]]))
        lines.extend(claim_lines)

    p_claims, p_lines = planted_claims()
    return claims + p_claims, lines + p_lines


def price_claim(claim_id: str, member_id: str, provider_id: str, service: date, received: date,
                status: str, billed: float, denial: str | None, plan: str) -> tuple:
    """Fill in allowed, paid and member-owes amounts with simple rules.

    Allowed is 60% of billed. Paid claims: plan pays allowed minus the
    member's coinsurance. PR-1 (deductible): member owes all of allowed.
    Other denials and pending claims: nothing paid yet.
    """
    allowed = round(billed * 0.60, 2)
    coins = PLANS[plan]["coinsurance"] / 100
    if status == "paid":
        paid, owes = round(allowed * (1 - coins), 2), round(allowed * coins, 2)
    elif denial == "PR-1":
        paid, owes = 0.0, allowed
    else:
        paid, owes = 0.0, 0.0
        allowed = 0.0 if status == "denied" else allowed
    return (claim_id, member_id, provider_id, service.isoformat(), received.isoformat(),
            status, billed, allowed, paid, owes, denial)


def planted_claims() -> tuple[list, list]:
    """Hand-written claims with known right answers for the demo stories."""
    claims, lines = [], []
    # Demo story 1: lower spine MRI denied because no prior auth was on file.
    claims.append(price_claim("CLM-10482", "M-00142", "P-003", date(2026, 9, 12), date(2026, 9, 18),
                              "denied", 1240.00, "CO-197", "Silver"))
    lines.append(("CLM-10482", 1, "72148", "M54.50", 1, 1240.00))
    # Demo story 3 history for M-00217: knee X-ray recently, 8 PT visits, no knee MRI.
    pt_dates = [date(2026, 8, 4) + timedelta(days=7 * i) for i in range(8)]
    for i, d in enumerate(pt_dates):
        claim_id = f"CLM-{11491 + i}"
        claims.append(price_claim(claim_id, "M-00217", "P-004", d, d + timedelta(days=6),
                                  "paid", 95.00, None, "Silver"))
        lines.append((claim_id, 1, "97110", "M25.561", 1, 95.00))
    claims.append(price_claim("CLM-11499", "M-00217", "P-003", date(2026, 10, 20), date(2026, 10, 24),
                              "paid", 140.00, None, "Silver"))
    lines.append(("CLM-11499", 1, "73562", "M25.561", 1, 140.00))
    claims.append(price_claim("CLM-11500", "M-00217", "P-002", date(2026, 11, 3), date(2026, 11, 7),
                              "paid", 190.00, None, "Silver"))
    lines.append(("CLM-11500", 1, "99214", "M25.561", 1, 190.00))
    return claims, lines


def make_auth_requests(rng: random.Random, members: list[tuple]) -> list[tuple]:
    """60 prior auth requests with mixed statuses. None for the planted members,
    so demo story 3 starts with an empty history for M-00217."""
    eligible = [m for m in members if m[0] not in {"M-00142", "M-00217", "M-00250"}]
    codes = [c for c, rule in AUTH_RULES.items() if rule[0]]
    reviewers = ["Reviewer A. Lindqvist", "Reviewer J. Marchetti", "Reviewer P. Holloway"]
    rows = []
    for n in range(1, 61):
        status = rng.choices(["pending", "approved", "denied"], weights=[3, 5, 2])[0]
        rec = {"pending": "needs_more_info", "approved": "approve", "denied": "deny"}[status]
        rationale = {"approve": "All criteria met per submitted records.",
                     "deny": "Conservative treatment not documented.",
                     "needs_more_info": "Waiting for recent imaging report."}[rec]
        rows.append((f"PA-{n:04d}", rng.choice(eligible)[0], rng.choice(codes),
                     rand_date(rng, YEAR_START, TODAY).isoformat(), status, rec, rationale,
                     None if status == "pending" else rng.choice(reviewers)))
    return rows


# ---------------------------------------------------------------- policy documents


def criteria_section(code: str) -> str:
    """Markdown section listing one procedure's criteria, from AUTH_RULES."""
    plans, _, criteria = AUTH_RULES[code]
    needed = ", ".join(plans) if plans else "no plan"
    items = "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, start=1))
    return (f"## {PROCEDURES[code][0]} ({code})\n\n"
            f"Prior authorization is required on: {needed}.\n\nCriteria:\n\n{items}\n")


def coverage_summary(plan: str) -> str:
    """Coverage summary for one plan, built from the PLANS table values."""
    p = PLANS[plan]
    chiro = (f"Chiropractic care is covered up to {p['chiro_visits']} visits per calendar year."
             if p["chiro_visits"] else "Chiropractic care is not covered on the Bronze plan.")
    auth_codes = sorted(c for c, rule in AUTH_RULES.items() if plan in rule[0])
    auth_list = "\n".join(f"- {PROCEDURES[c][0]} ({c})" for c in auth_codes)
    return f"""# {plan} Plan Coverage Summary

{BANNER}

## Overview

The {plan} plan is an Acme Health Plan product for individuals and families. This summary explains what the plan pays and what the member pays. The plan year runs from January 1 to December 31.

## Costs

- Deductible: ${p['deductible']:,} per person per year.
- Coinsurance after the deductible: the member pays {p['coinsurance']}% and the plan pays {100 - p['coinsurance']}%.
- Out-of-pocket maximum: ${p['oop_max']:,} per person per year.
- Specialist visit copay: ${p['specialist_copay']}.

## Physical therapy

Physical therapy is covered up to {p['pt_visits']} visits per calendar year, combined across all therapists. An evaluation visit counts toward the limit. Visits beyond {p['pt_visits']} need a medical necessity review; see the Physical Therapy Prior Authorization Policy.

## Chiropractic care

{chiro}

## Imaging

X-rays are covered without prior authorization. Advanced imaging such as MRI, CT and PET scans is covered when medically necessary and may require prior authorization; see the Imaging and Procedures Prior Authorization Policy.

## Specialty drugs

Specialty drugs given by injection or infusion are covered when prior authorization is approved; see the Specialty Drug Prior Authorization Policy.

## Services that need prior authorization

{auth_list}

## Not covered

- Cosmetic procedures
- Weight loss programs
- Services from out-of-network providers, except emergencies
"""


def policy_documents() -> dict[str, str]:
    """All 10 Markdown documents, keyed by file name."""
    docs = {f"{plan.lower()}_coverage_summary.md": coverage_summary(plan) for plan in PLANS}
    imaging_codes = [c for c, r in AUTH_RULES.items() if r[1] == "imaging"]
    other_codes = [c for c, r in AUTH_RULES.items() if r[1] in ("surgery", "sleep", "equipment")]
    drug_codes = [c for c, r in AUTH_RULES.items() if r[1] == "specialty_drug"]
    pt_limits = ", ".join(f"{plan} {p['pt_visits']} visits" for plan, p in PLANS.items())

    docs["prior_auth_imaging.md"] = (
        f"# Imaging and Procedures Prior Authorization Policy\n\n{BANNER}\n\n"
        "## Purpose\n\nThis policy lists the imaging tests, surgeries and related services that need prior "
        "authorization, and the criteria a request must meet. A request that meets every criterion is "
        "recommended for approval. A request that misses a criterion goes to a clinical reviewer.\n\n"
        "## Services done without prior authorization\n\nIf a service on this list is done without an "
        "approved prior authorization, the claim is denied with code CO-197. The provider may request a "
        "retro authorization within 30 days of the denial, or the member may file an appeal.\n\n"
        + "\n".join(criteria_section(c) for c in imaging_codes + other_codes))
    docs["prior_auth_specialty_drugs.md"] = (
        f"# Specialty Drug Prior Authorization Policy\n\n{BANNER}\n\n"
        "## Purpose\n\nSpecialty drugs need prior authorization on all plans. Approvals last 12 months "
        "and must be renewed with an update from the prescriber.\n\n"
        + "\n".join(criteria_section(c) for c in drug_codes))
    docs["prior_auth_physical_therapy.md"] = (
        f"# Physical Therapy Prior Authorization Policy\n\n{BANNER}\n\n"
        "## Visit limits\n\nPhysical therapy does not need prior authorization while the member is within "
        f"the plan's yearly visit limit: {pt_limits}.\n\n"
        "## Visits beyond the limit\n\nExtra visits need a medical necessity review. The therapist sends "
        "a progress note showing measurable improvement and a plan for the extra visits.\n\n"
        + criteria_section("97110"))
    docs["appeals_procedure.md"] = f"""# Appeals Procedure

{BANNER}

## Who can appeal

A member, or a provider acting for the member, can appeal any denied claim or prior authorization.

## Deadline

An appeal must be filed within {APPEAL_DAYS} days of the date on the denial notice.

## What to include

- The claim ID or prior authorization ID
- The reason the member or provider disagrees
- Supporting records, such as a letter of medical necessity, office notes or imaging reports

## How appeals are decided

A reviewer who was not part of the first decision looks at the appeal. Standard appeals are decided within 30 days. Urgent appeals are decided within 72 hours.

## Appeals for missing prior authorization

For a CO-197 denial, the appeal should show that the service met the prior authorization criteria at the time it was done. If it did, the claim can be reprocessed.
"""
    docs["timely_filing.md"] = f"""# Timely Filing Rule

{BANNER}

## Filing limit

In-network providers must submit claims within {TIMELY_FILING_DAYS} days of the service date. Claims received later are denied with code CO-29.

## Exceptions

A late claim can be paid if the provider shows proof of an earlier on-time submission, such as a clearinghouse report, or if another insurer was billed first in good faith.

## Member impact

Members cannot be billed for claims denied for timely filing by in-network providers.
"""
    docs["out_of_network.md"] = f"""# Out-of-Network Services Policy

{BANNER}

## General rule

Acme Health Plan products do not cover services from out-of-network providers. Such claims are denied with code CO-242.

## Emergencies

Emergency care is covered at in-network cost sharing, at any provider.

## Network gaps

If no in-network provider can offer a needed service within a reasonable distance, the member can ask for a network exception before the service. A member who did not ask in advance can still appeal.
"""
    docs["eligibility_and_enrollment.md"] = f"""# Eligibility and Enrollment Policy

{BANNER}

## Active coverage

A member is eligible on a date of service if the date falls between their eligibility start date and end date. A member with no end date is currently active.

## Lapsed coverage

Claims and prior authorization requests for dates after the eligibility end date are not covered. The analyst should tell the member to check their enrollment status.

## Changing plans

Members can change between Bronze, Silver and Gold during open enrollment, from November 1 to December 15, for coverage starting January 1.
"""
    return docs


# ---------------------------------------------------------------- write and check


def write_database(rng: random.Random) -> None:
    """Create payer.db from scratch and fill every table."""
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    members = make_members(rng)
    providers = make_providers(rng)
    claims, lines = make_claims(rng, members, providers)
    con.executemany("INSERT INTO plans VALUES (?,?,?,?,?,?,?,1)",
                    [(k, v["deductible"], v["coinsurance"], v["oop_max"], v["pt_visits"],
                      v["chiro_visits"], v["specialist_copay"]) for k, v in PLANS.items()])
    con.executemany("INSERT INTO members VALUES (?,?,?,?,?,?,?,1)", members)
    con.executemany("INSERT INTO providers VALUES (?,?,?,?,1)", providers)
    con.executemany("INSERT INTO procedures VALUES (?,?,?,1)",
                    [(c, d, cat) for c, (d, cat, _) in PROCEDURES.items()])
    con.executemany("INSERT INTO diagnoses VALUES (?,?,1)", list(DIAGNOSES.items()))
    con.executemany("INSERT INTO denial_codes VALUES (?,?,?,?,1)",
                    [(c, n, m, s) for c, (n, m, s, _) in DENIAL_CODES.items()])
    con.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,1)", claims)
    con.executemany("INSERT INTO claim_lines VALUES (?,?,?,?,?,?,1)", lines)
    con.executemany("INSERT INTO auth_rules VALUES (?,?,?,?,1)",
                    [(code, plan, int(plan in rule[0]), POLICY_FOR_CATEGORY[rule[1]])
                     for code, rule in AUTH_RULES.items() for plan in PLANS])
    con.executemany("INSERT INTO auth_criteria VALUES (?,?,?,1)",
                    [(code, i, text) for code, rule in AUTH_RULES.items()
                     for i, text in enumerate(rule[2], start=1)])
    con.executemany("INSERT INTO prior_auth_requests VALUES (?,?,?,?,?,?,?,?,1)",
                    make_auth_requests(rng, members))
    con.commit()
    con.close()


def write_policies() -> None:
    """Write the 10 Markdown policy documents."""
    POLICY_DIR.mkdir(exist_ok=True)
    for name, text in policy_documents().items():
        (POLICY_DIR / name).write_text(text)


def check() -> bool:
    """Print row counts and planted-case checks. Return True if all pass."""
    con = sqlite3.connect(DB_PATH)
    ok = True

    def q(sql: str):
        """Run a query that returns one value."""
        return con.execute(sql).fetchone()[0]

    def report(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'OK' if passed else 'FAIL'}] {label} {detail}")

    print("Row counts:")
    expected = {"plans": 3, "members": 200, "providers": 40, "claims": 1500,
                "denial_codes": 6, "prior_auth_requests": 60}
    for table, want in expected.items():
        got = q(f"SELECT COUNT(*) FROM {table}")
        report(f"{table:<20}", got == want, f"{got} (design: {want})")
    rules = q("SELECT COUNT(DISTINCT procedure_code) FROM auth_rules")
    report(f"{'auth rule procedures':<20}", rules == 15, f"{rules} (design: 15)")
    codes = q("SELECT COUNT(*) FROM procedures") + q("SELECT COUNT(*) FROM diagnoses")
    report(f"{'procedure+diag codes':<20}", 30 <= codes <= 45, f"{codes} (design: about 30)")
    denied_pct = 100 * q("SELECT AVG(status = 'denied') FROM claims")
    report(f"{'denied share':<20}", 15 <= denied_pct <= 25, f"{denied_pct:.1f}% (design: about 20%)")
    reasons = q("SELECT COUNT(DISTINCT denial_code) FROM claims WHERE status = 'denied'")
    report(f"{'denial reasons used':<20}", reasons == 6, f"{reasons} (design: 6)")
    docs = len(list(POLICY_DIR.glob("*.md")))
    report(f"{'policy documents':<20}", docs == 10, f"{docs} (design: 10)")
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    not_flagged = sum(q(f"SELECT COUNT(*) FROM {t} WHERE is_synthetic != 1") for t in tables)
    report(f"{'is_synthetic flags':<20}", not_flagged == 0, f"{len(tables)} tables, all rows flagged")

    print("Planted demo cases:")
    row = con.execute("SELECT member_id, status, denial_code, billed_amount FROM claims "
                      "WHERE claim_id = 'CLM-10482'").fetchone()
    report("story 1: CLM-10482 denied CO-197", row == ("M-00142", "denied", "CO-197", 1240.0), str(row))
    silver_pt = q("SELECT pt_visit_limit FROM plans WHERE plan_id = 'Silver'")
    in_doc = f"up to {silver_pt} visits" in (POLICY_DIR / "silver_coverage_summary.md").read_text()
    report("story 2: Silver PT limit in table and doc agree", silver_pt == 30 and in_doc, f"{silver_pt} visits")
    row = con.execute("SELECT plan_id, eligibility_end FROM members WHERE member_id = 'M-00217'").fetchone()
    needs_auth = q("SELECT auth_required FROM auth_rules WHERE procedure_code = '73721' AND plan_id = 'Silver'")
    xray = q("SELECT COUNT(*) FROM claims c JOIN claim_lines l USING (claim_id) "
             "WHERE c.member_id = 'M-00217' AND l.procedure_code = '73562'")
    report("story 3: M-00217 active Silver, knee MRI needs auth, X-ray on file",
           row == ("Silver", None) and needs_auth == 1 and xray == 1, str(row))
    lapsed = q("SELECT eligibility_end FROM members WHERE member_id = 'M-00250'")
    report("eval: M-00250 lapsed", lapsed == "2026-06-30", str(lapsed))
    con.close()
    return ok


def main() -> None:
    rng = random.Random(SEED)
    write_database(rng)
    write_policies()
    print(f"Wrote {DB_PATH.name} and {POLICY_DIR.name}/ (all data is synthetic)\n")
    passed = check()
    print("\nMilestone 1 check:", "PASSED" if passed else "FAILED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
````
