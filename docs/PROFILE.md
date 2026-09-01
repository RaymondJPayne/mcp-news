# The profile: your algorithm, as a file you can read

`config/profile.yaml` decides what surfaces and in what order. It is the entire
ranking model. There is no second, hidden model.

## Design commitments

1. **Inspectable.** Every score decomposes into named rules that fired. The
   dashboard shows them on each article; `mcpnews explain <id>` prints them.
2. **Deterministic.** The same article and the same profile always produce the
   same score. No randomness, no personalisation drift, no A/B bucket.
3. **No model required.** Scoring is weighted string matching over title, body and
   metadata. It runs identically with no AI configured.
4. **Freshness is not relevance.** The stored score answers "does this match what
   I care about". How recent it is stays a separate, query-time concern.

## Schema

```yaml
version: 1

identity:
  name: Your Name
  aliases: [Y. Name]
  weight: 5

interests:
  - name: Semiconductor policy
    match: [export control, lithography, ASML, TSMC, fab]
    must_include: []          # all of these must also appear
    exclude: [semiconductor stocks]
    weight: 5                 # 1 = mildly interesting, 5 = tell me now
    in_title_multiplier: 2.0  # a headline match means the piece is about it

places:
  - name: Brazil
    match: [Brazil, Brasil, Brasilia, Sao Paulo]
    weight: 5
  - name: Ontario
    weight: 4

organisations:
  - name: Example Corp
    aliases: [ExampleCo]
    must_include: [technology]   # disambiguate a common word
    weight: 4

sources:
  boost:
    reuters.com: 1.2
  penalty:
    example-aggregator.com: 0.5

mute:
  domains: [example-clickbait.com]
  keywords: [horoscope, celebrity gossip]

scoring:
  min_score: 1.0        # below this, an article is stored but not shown
  cap_per_rule: 16.0    # one rule cannot dominate
  # Query-time decay defaults. NOT applied to the stored score.
  default_half_life_h: 36
  # What in_title_multiplier is when a rule does not state one.
  default_in_title_multiplier: 2.0
```

Every field has a default, so the shortest useful profile is a name and a few
words to match. `aliases` on any rule is merged into `match`; they are two ways
of saying the same thing and the scorer treats them identically.

## How a score is built

1. Match each rule against title, body and metadata on **word boundaries** — so a
   rule for "Ace" does not match "space", "surface" and "peace".
2. Title matches multiply by `in_title_multiplier`.
3. Sum the hits per rule, then cap at `cap_per_rule` so one repeated name cannot
   swamp everything.
4. Apply source boost or penalty. A domain in the table matches its subdomains
   too, so `reuters.com` covers `uk.reuters.com`.
5. Drop to zero if any `mute` rule matches.
6. Store the result as `interest_score`, with the list of rules that fired.

Recency is applied when a view asks for it — the feed uses a 36-hour half-life by
default, historical search uses none. Same stored score, different lens.

## Why not learn it?

A learned model would rank better in the short run and would cost the thing the
project exists to protect. You could no longer read why something appeared, could
no longer edit it directly, and it would drift toward whatever you clicked rather
than what you value — which is precisely the failure mode of the feeds this
replaces. Thumbs up and down exist, but they produce *suggested edits to this
file* which you accept or reject. The file stays the source of truth.
