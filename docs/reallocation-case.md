# What a five per cent reallocation would buy

**Status:** arithmetic demonstration on a public snapshot. Not a proposal, not a recommendation,
and not a claim about any one agency's portfolio.

## The question

The country view in this repository ranks 217 countries on two ranks: need, from the SDG series,
and delivery, from active commitment per person. Countries with a large negative gap are
better financed than their measured need; countries at the top of the short list are the
reverse. A review meeting usually ends with the same sentence — *"so what would moving money
actually buy?"* This page answers it for one share, so that the answer is a number rather than
an adjective.

## How it is computed

1. **The pool.** Five per cent of the value still live at the snapshot date:
   `0.05 × $331.9bn = $16.6bn`. Commitment, not disbursement — see the caveat below.
2. **Who pays.** Countries with a negative allocation gap *and* a live portfolio: 58 countries
   holding $115.1bn of active value. Each contributes in proportion to its live value, so no
   country is asked for more than a twentieth of what it already holds.
3. **Who receives.** The 25 countries at the top of the short list, 981 million people.
4. **How much per person.** Distributed in proportion to population, so the gain per person is
   identical in every recipient country by construction — the model is deliberately blind to
   which country is which once a country is on the list.

## The result

| Quantity | Value |
|---|---|
| Value moved | **$16.6bn** (5.0% of $331.9bn live) |
| Gain per person, 25 recipient countries | **$16.92** |
| People covered | 981m |
| Cost per person, 58 contributing countries | **$6.95** |
| Contributors' population | 1.02bn |

Two numbers, one ratio: a person in a recipient country gains about $27, a person in a
contributing country gives up about $16. The asymmetry is population, not generosity — the
recipients are poorer and more populous per dollar of live portfolio.

## What this does not buy

- **Approved financing is not money that arrived.** The pool is commitment. Reallocating
  commitment changes what a country may draw, not what it has drawn; the delivery constraint
  sits downstream of this arithmetic.
- **It does not fix absorption.** A country that cannot spend its current portfolio will not
  spend a larger one faster. The need index measures service gaps, not implementation capacity.
- **It is not a legal instrument.** Commitments are bound to specific operations, approved by a
  board, and run for years. A real reallocation is a sequence of decisions on individual
  operations across several replenishment cycles, not a single transfer.
- **The gain is small per person.** $27 is roughly a month of a household's water bill. The
  argument for reallocation has to rest on direction and on the compounding effect of repeated
  cycles, not on the size of one round.

## What would falsify this

- If the need index and the delivery measure were not independent — if thin portfolios simply
  reflected recent approval rather than neglect — the donor and recipient sets would be arbitrary.
  Test: rebuild the ranking on value approved before 2015 only; the two sets should overlap
  substantially.
- If the 5% were taken from operations that are already fully disbursed, the cost would fall on
  closed books rather than live ones. Test: recompute the donor base on undisbursed balance
  instead of commitment, which this snapshot does not carry.
- If gains per person did not survive weighting by population, the "identical by construction"
  property would be the artefact rather than the finding. It is a property of the formula, and
  the page states it as one.

## If someone wanted to act on it

Three decisions, in order: whether the short list should be the unit of review at all; whether a
pilot round should be a smaller share (1–2%) over one replenishment cycle; and which evidence —
disbursement, not commitment — would be required before any round is judged. This repository
supplies the first two as arithmetic and the third as a gap in the data.

## Reproduce

```
make build                       # staging, warehouse, 11 models
python pipeline/dq.py            # 14 checks, including the pool reconciliation
python pipeline/site.py          # page; move the slider to change the share
```

Mart: `data/marts/mart_reallocation.csv`. Model: `models/27_mart_reallocation.sql`.
The page recomputes gain and cost per person from the slider value with the same formula, so
`0.05` on the slider reproduces the numbers above.
