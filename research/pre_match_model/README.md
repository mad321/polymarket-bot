# Can we predict which pre-match favourite wins? (2026-10-24)

The owner asked for a predictive model to pick the best match of the day.

## Data

**Market data** (`build.py` → `market.json`): every finished match of the seven watched leagues since 2025-08-01 (1,895 games). For each team we have:

- its "Will <team> win?" Yes price 15–60 minutes before kickoff (CLOB price history);
- the match volume;
- home or away;
- whether the team won.

That gives 3,788 team rows. Draws count as a loss for both teams.

**The owner's own history**: 147 settled "win Yes" trades since March (activity feed and Gamma resolutions). These are not in the repo, because they are private.

## Results

1. **The market is well calibrated.** In every price band, the share of teams that won is within the noise of the price (|z| < 2 everywhere). Buying every team priced 55–72¢ and holding to the end returns +1.5% ± 6.4% per trade after fees, which is indistinguishable from zero.
2. **No feature beats the price.** For 55–72¢ teams, none of these differs from the price by more than noise:
   - home vs away;
   - elite list vs not;
   - volume ≥ $15k vs below;
   - league.
3. **The model does not beat the price.** We trained a logistic model on the first 70% of matches (logit of price, home, elite list, log volume, league) and tested it on the last 30% (from 2026-08-11). Out-of-sample log-loss was −0.5438 for the model vs −0.5428 for the price alone. The price coefficient is 1.03, i.e. the price is already the right probability.
4. **Pick-of-the-day rules on the 3.0 candidates (118 days)** are all within noise of zero:

   | Pick rule | Return per trade |
   | - | - |
   | Lowest price | −0.5% ± 14 |
   | Home first | −2.0% ± 14 |
   | Highest price | −3.6% ± 14 |
   | Most volume | −6.8% ± 14 (the first 3.1 rule) |
   | Model's largest "edge" | +24% ± 22.5, on only 33 test days — and since the model loses to the price overall, this is not a signal |

5. **The owner's 147 trades** won 71.4% against 67.3% implied by the entry prices (z = +1.1). That is not distinguishable from luck.

## What this means

There is no predictable edge in **pre-match** prices of these leagues with this data. A pick rule only decides which zero-expectation bet to take. The money is lost or kept in the **exits**: selling at −20% or at +20% cost the owner more than holding (see `LESSONS.md`).

Strategy 3.1 therefore picks the in-range candidate with the **lowest price**:

- it has the best (still zero) backtest;
- the most volume was the worst;
- with $5 trades, depth of book does not matter.

Edge, if any, has to come from elsewhere. Candidates:

- in-play reactions (`live_feed.py` is measuring goal-to-price timing);
- smaller markets;
- other bet types.

## Re-running

```bash
python research/pre_match_model/build.py 2025-08-01   # network, ~10 minutes
python research/pre_match_model/analyze.py
python research/pre_match_model/model.py              # needs numpy
```
