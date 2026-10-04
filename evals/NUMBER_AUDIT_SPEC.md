# What counts as a number in an answer (spec for the independent audit)

Written 2026-10-03, before `evals/number_audit.py`, which implements it. The auditor is the
measurement behind hallucination figure 1(b) in `evals/HELDOUT_PROTOCOL.md` 6a. It exists because the
pipeline's own verifier (`ledgerql/verify.py`) cannot be both the defence and the yardstick: on the
same inputs its post-verifier rate is 0% by construction.

**Independence.** The auditor is written from this document. It imports nothing from `ledgerql/`
and does not read or reuse `verify.py`'s extraction code, nor `evals/year_audit.py` (which imports
`verify`). Its only inputs are the answer text, the executed result (column names and rows), the
executed SQL text, and, optionally, a read-only connection to the database for labels. Where this
spec and `verify.py` choose differently, that is deliberate: the differences are what the comparison
is for. The SQL is parsed (sqlglot) for one purpose only: to read which company it names (section 3).

## 1. Claims

A **numeric claim** is a stretch of the answer that states a quantity, a year, a date or a period
label. Each claim has a value and a stated precision (section 2). The kinds:

1. **Digit numbers.** Digits with an optional sign (`-` or `−`, only when it stands at the start of
   a word, so the hyphen in `2024-2025` is not a minus), optional currency symbol (`$`, `US$`,
   `€`, `£`), optional thousands commas in groups of three, optional decimals (`3.14`, `.5`), optional
   exponent (`1.2e9`). `1,234,567.8` is one number; `1,2,3` is three.
2. **Percentages.** A number followed by `%`, `percent`, `per cent`, `percentage point(s)` or `pp`.
   The claim is a percentage.
3. **Magnitudes.** A number followed by a scale word: `thousand`, `million`, `billion`, `trillion`
   (also `mil`, `mln`, `bil`, `tril`), or an abbreviation: `bn`, `mn`, `mm` (any case), `tn`, `trn`,
   and the single letters `k`, `m`, `b`, `t` (any case) **only when attached** to the number with no
   space (`391B`, `4.4T`, `5k`). A multi-letter word or abbreviation may follow after one space
   (`391 billion`, `391 bn`). A letter that is followed by another letter or digit is not a
   magnitude. The claim's value is the number times the scale.
4. **Spelled-out numbers.** `zero`, `two` to `nineteen`, `twenty` to `ninety`, hyphenated or
   space-joined compounds (`forty-two`, `twenty one`), `hundred`, `thousand`, `million`, `billion`,
   `trillion`, with an optional `and` (`three hundred and five`), `a hundred`/`a thousand`/`a million`/
   `a billion`/`a trillion`, a decimal in words (`two point five`), and a trailing `percent`.
   `one` counts only inside a compound or next to a scale word (`twenty-one`, `one hundred`, `one
   point five`); a bare `one` is a pronoun and is not a claim.
5. **Years.** A four-digit number from 1900 to 2099 with no comma, decimal, sign, currency or
   suffix; and `FY` followed by a two- or four-digit year (`FY24` is 2024), and `'24`. A year-shaped
   number is grounded if it is grounded **either** as a year **or** as an ordinary quantity (a result
   that contains 2024 as a count grounds "2024").
6. **Dates.** `June 30, 2025`, `Jun. 30 2025`, `30 June 2025`, `2025-06-30`, `6/30/2025`
   (month first), `June 2025` (month and year) and `June 30` (month and day, no year). A date is **one**
   claim: its day, month and year are not separate claims. Month names are capitalised, so the verb "may"
   is not a month.
7. **Period labels.** `Q1` to `Q4`, `H1`, `H2`. A label with a year after it (`Q3 2025`) is a label
   plus a year claim.

**Not claims** (masked before extraction): (a) a company name or ticker from the database, or a
string in the result, that contains a digit (`3M`); (b) an SEC form code from a fixed list (`10-K`,
`10-K/A`, `10-KT`, `10-Q`, `8-K`, `20-F`, `40-F`, `6-K`, `11-K`, `S-1`, `S-3`, `S-4`, `F-1`, `DEF 14A`);
anything else shaped like a form code (`5-K`) is an ordinary number followed by a letter; (c) a digit
ordinal (`1st`, `2nd`, `3rd`, `4th`); (d) a list marker at the start of a line (`1.`, `2)`); (e) an
identifier in which digits are glued to letters and that is not a magnitude or label above
(`H2O`, `COVID19`, `x86`).

## 2. Value and precision

- **Value:** the number times its scale (`4.4 billion` is 4.4e9, `12.5%` is the percentage 12.5).
  Spelled-out numbers are converted. The sign is kept.
- **Precision:** the number of decimals the claim states (`391.0 billion` has one, `4 billion` has
  none; a spelled-out number has none unless it says `point`). A claim is a correct statement of a
  result number if it equals that number **rounded to the stated precision**: within half a unit of
  the last stated place, times the scale. So `about 4 billion` is correct for 4.42e9 (it rounds to
  4 billion) and wrong for 4.62e9 (which rounds to 5); `4.4 billion` is correct for 4.43e9 and
  wrong for 4.46e9 (which rounds to 4.5). There is no percentage-style slack beyond half a unit.
- **Coarse rounding (reported separately), for a hedged round number only.** Trailing zeros in a
  whole-number claim leave its precision unstated **only when the answer hedges the figure**: directly
  after `about`, `approximately`, `roughly`, `around`, `nearly` or `~`, `about 420 billion` may mean
  420 to the billion or 42 tens of billions. Such a claim that fails the rule above but is a correct
  rounding of a result number to its last **non-zero** place (`about 420 billion` for 416.161 billion)
  is `weak`, source "coarse rounding": not counted as ungrounded, never counted as strongly grounded.
  Fewer than ten (`about 4 billion`) has no such reading. **Without a hedge, trailing zeros are stated
  digits**: `420 billion` for 416.161 billion is `ungrounded`. (Amended 2026-10-03: unhedged, the
  trailing-zero reading accepts most of what a flat 1% tolerance did.)

## 3. Grounding: where a claim may come from

A claim is **grounded** if it is correct (section 2) for:

1. **a number in the result**: any numeric cell; also the cell times a scale when its column name
   names a scale (`revenue_in_billions` holds billions; `thousands`, `millions`, `trillions`, `_bn`,
   `_mm`, `_k`); a percentage claim matches the cell as it is or the cell times 100; the sign is
   ignored (a "fell 5%" statement over a −5 cell);
2. **the number of rows** in the result (a count of what was returned: "the ten companies");
3. **a numeral inside a string cell** (a date, `FY2024`, a ticker with digits);
4. for a **year**: a year in a result cell or date, or a year or date literal in the executed SQL
   (`fiscal_year = 2025`, `'2024-09-28'`);
5. for a **date**: the same date in a result cell or SQL literal (a month-year or month-day claim
   needs a date with that month and year, or month and day);
6. for a **period label**: the same label in a result string or the SQL.

7. for a **year or date** that is in none of the above: a label the database holds **for the
   company the SQL names** (a `filings.fiscal_year`, a `filings.period_end_date` or a
   `financial_facts.ddate` of that company). The framing's "fiscal year 2025 (period ended June 30,
   2025)" is grounded this way.

**Which company the SQL names** (amended 2026-10-04; until then it was any string literal in the SQL
text equal to a ticker or a name). The SQL is parsed (sqlglot, DuckDB dialect) and its **company
predicates** are read. A company predicate compares a column called `cik`, `ticker` or `name` with a
value, anywhere in the statement: the `WHERE` clause, a join condition, a subquery, a CTE. The
column may be wrapped in `lower`, `upper`, `trim`, a cast or parentheses. Two things are not company
predicates, because neither restricts the query to a company: a comparison of two columns (a join
key, `f.cik = c.cik`) and a null test (`cik IS NULL`, an anti-join).

A company predicate **names a company** when it is `=`, `IN` with a list of literals, or `LIKE` /
`ILIKE` with no wildcard, and every literal in it is found in the `companies` table: a string equal
to a ticker or a name (case-insensitive) or, against `cik`, a number or a string of digits equal to
a `cik`. A comparison with a subquery names whatever the subquery's own company predicates name
(`cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')` names Apple). Every other company
predicate is one the auditor **cannot resolve**: a pattern with a wildcard, a range, a negation
(`<>`, `NOT IN`: the literal is excluded, not named), a subquery with no company predicate of its
own (`cik IN (SELECT cik FROM companies WHERE gics_sector = ...)`), a literal that is no company in
the table. SQL that does not parse is treated as one unresolvable predicate.

**A year or date that is in none of 1 to 7** falls into one of four cases (the third added
2026-10-04):

- **The database holds it for no company:** `ungrounded`, whatever the SQL. It cannot be right for
  any company.
- **The database holds it, and the SQL has no company predicate at all** (a cross-company query):
  `ungrounded`. A single company's period label is tied to nothing in the answer.
- **The database holds it, and the SQL has a company predicate the auditor cannot resolve:**
  **`unresolved`**. The label may be right for the company the SQL means, and the auditor cannot
  tell. This is its own status: reported separately, never counted as ungrounded and never as
  grounded (the same principle as a timeout not scoring as a wrong answer).
- **The database holds it, every company predicate is resolved, and no named company has it:**
  `ungrounded` (amended 2026-10-03; it was `weak`). That it is a real label does not make it this
  answer's: another company's period attached to this company's figure is the misattributed period
  the year rule exists to catch.

In the two database-holds-it `ungrounded` cases and in the `unresolved` case the claim's source says
so, so a reader can tell them from a label that exists nowhere. A label a resolved part of the SQL
does name is grounded even if another part is unresolved (`ticker = 'AAPL' OR name LIKE '%Amazon%'`
grounds Apple's labels and leaves any other company's `unresolved`). Only years and dates can be
`unresolved`; a number or a period label never is. **`weak` is coarse rounding only** (section 2).
Numbers get no weak grounding.

**Derived:** a claim not grounded by 1 to 6 but equal to the sum, difference, ratio, or percentage
change of two numeric cells in the result. It was not invented from nothing, but the result does not
state it. Reported separately, not counted as ungrounded. Only genuine numeric cells are operands (not
the row count, not a year-valued cell), and only a claim that states at least three significant digits
can be derived: with fewer, an accidental match is too likely (the first draft let "about a hundred"
pass as the percentage change between a row count and a year).

**Ungrounded:** everything else. This is an invented (or mis-scaled, or mis-transcribed) number.

## 4. What the audit reports

Per answer: its claims, each with kind, text, value, stated precision, and its status (`grounded`,
`weak`, `derived`, `unresolved`, `ungrounded`) and what grounded it. An answer is **clean** if none of
its claims is ungrounded. Headline: the share of audited answers that are not clean, with the
ungrounded claims listed; unresolved, weak and derived counts beside it, and every unresolved claim
listed with its answer and SQL so it can be judged by reading.

## 5. Stated limits

Not counted: a bare `one`, `half`, `a third`, `a dozen`, ordinals in words, "twice" and the like
(relative statements); a quantity hidden in a word the lists do not know. Abbreviation `m`/`b`/`t`/`k`
attached to a number is read as a magnitude even if it meant minutes or bytes. The company is read
only from predicates on columns called `cik`, `ticker` or `name` (section 3): a company restricted
through a column under another name (an alias, `company_name`) is not seen, so its query reads as
cross-company and a year or date that is right for it is `ungrounded`, the audit's own false positive
to look for when reading the list. An `unresolved` claim is not a finding in either direction: an
invented year that happens to be some other company's label is `unresolved`, not caught, whenever the
SQL's company cannot be resolved. A number that happens to equal the row count or any unrelated cell is
grounded by it: the audit cannot tell a coincidence from a transcription.
