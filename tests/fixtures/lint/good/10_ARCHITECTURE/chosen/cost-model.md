# Cost model

## Assumptions

| id | assumption | value | source |
|---|---|---|---|
| CA-1 | active nurses in the pilot | 300 | [ASSUMPTION: one hospital with 300 night-shift nurses] |
| CA-2 | SMS per nurse per month | 8 | [ESTIMATE: 5-10; two swaps a month] |

## Monthly run cost

| item | MVP | 10x | 100x |
|---|---|---|---|
| containers | $120 | $360 | $2,400 |
| database | $180 | $540 | $3,600 |
| SMS | $120 | $1,200 | $12,000 |
| total | $420 | $2,100 | $18,000 |

## Per active user

At the MVP scale the run cost is about $1.40 per active nurse per month, falling with scale because the database and
container costs grow slower than the number of users.

## LLM and API costs

The MVP uses no language model. The only per-use API is the SMS gateway, which dominates the cost at every scale.

## Build cost

The build takes 6 to 10 person-weeks for two developers, including the roster integration and the pilot support.

## Sensitivity

If SMS use is 50 percent higher than assumed, the monthly MVP cost rises from $420 to $480; if it is 50 percent lower,
the cost falls to $360. No other driver moves the total by more than ten percent.
