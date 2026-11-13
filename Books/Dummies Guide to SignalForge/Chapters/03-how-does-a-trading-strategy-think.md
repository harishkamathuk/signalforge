# Chapter 3 — How Does a Trading Strategy Think?

*Robo puts on a detective's hat, examines the clues, and discovers why a perfect checklist is not the same as a crystal ball.*

## Robo becomes a detective

Imagine Robo sitting at its computer, wearing a tiny detective's hat.

There's a magnifying glass on the desk.

A notebook lies open.

And on the screen, the price of a company share is climbing.

Robo is excited.

*"The price is going up! Should I buy?"*

Not so fast, Robo.

Imagine a detective arriving at a mysterious house.

The detective spots a muddy footprint outside the front door.

*"Aha!"* says the detective. *"I've solved the case!"*

Really?

One muddy footprint?

What if it belongs to the postman?

A good detective examines several clues before reaching a conclusion.

A trading strategy works in a similar way.

It doesn't have to predict what tomorrow will bring.

Instead, it checks whether the information available now satisfies a particular set of rules.

And that's how Robo begins thinking like a trading strategist.

## First, what is a strategy?

In Chapter 1, we met the idea of a trading strategy.

In Chapter 2, we watched Robo recognise an opportunity and wait for an entry condition.

But where did those decisions come from?

From the strategy.

Think about a recipe for baking a cake.

It might tell you to use two eggs, add flour, mix the ingredients and bake at a particular temperature.

Following the recipe doesn't guarantee a delicious cake.

Your ingredients could be poor.

Your oven might be unreliable.

Or the recipe itself might be terrible.

But at least the instructions are clear enough that somebody else can follow them.

A trading strategy is a recipe for making trading decisions.

It specifies what information to examine, which conditions must be satisfied, and what should happen next.

SignalForge's accepted initial strategy for Indian shares has a rather technical name:

**intraday_momentum_v1 / 1.0.0**

Don't worry about remembering that.

For our story, let's call it **Robo's Rulebook**.

The important thing is that the rulebook has a name and a version.

If somebody changes the rules tomorrow, we shouldn't pretend we're still using exactly the same recipe.

## The clue that starts everything

Robo watches one company share on India's National Stock Exchange.

As we learned earlier, its strategy decisions use completed five-minute market reports called **candles**.

Each finished candle tells Robo what happened during that period.

But one candle isn't enough.

Robo also needs information from earlier candles.

Why?

Imagine trying to judge whether today's weather is unusually hot.

If somebody tells you the temperature is 27°C, that gives you one piece of information.

But is 27°C unusually hot?

That depends on the season, location and recent weather.

Market prices are similar.

A share trading at ₹500 doesn't automatically mean it's expensive, cheap or likely to rise.

Robo needs context.

That's where **indicators** come in.

Indicators are measurements calculated from market information.

They help describe what prices have been doing.

They do not tell us with certainty what prices will do next.

## Clue number one: Which way is the market leaning?

Our detective begins by examining the direction of recent prices.

One tool used by SignalForge's initial strategy is called an **Exponential Moving Average**, or EMA.

What a mouthful.

Let's make that simpler.

Imagine a schoolteacher who wants to see whether a pupil's performance is improving.

The teacher looks at a series of test results, giving more importance to recent results while still taking earlier performance into account.

An EMA works on a broadly similar principle.

It's a calculated average that responds to price changes, with greater weight placed on more recent observations.

The exact calculation involves earlier EMA values too. It doesn't simply forget everything before a fixed number of candles.

Robo looks at two particular averages.

**EMA20** responds more quickly to recent price changes.

**EMA50** responds more slowly.

The numbers describe the calculation periods. They don't mean 20 or 50 minutes, and they don't mean the indicators ignore all older prices.

Robo's first rule is:

**EMA20 must be greater than EMA50.**

In plain English:

*"The faster-moving average must be above the slower-moving average."*

That provides one clue about the price trend.

It doesn't guarantee that the price will continue rising.

It's simply the first condition in Robo's rulebook.

If EMA20 isn't above EMA50, this strategy's trend condition fails.

No arguing.

No saying, *"But it looks promising!"*

The detective marks the clue as missing.

## Clue number two: What do the movement gauges say?

Next, Robo examines two different measurements.

Imagine a cyclist travelling along a road.

One instrument might help describe how the cyclist has been moving.

Another might help describe the strength of the overall movement.

They aren't necessarily answering the same question.

The stock market has different gauges too.

### The RSI gauge

The first is called the **Relative Strength Index**, or RSI.

RSI is calculated from the balance of recent upward and downward price movements.

For our purposes, think of it as a number that helps describe the character of recent price changes.

Robo's rulebook requires the 14-period RSI to be **between 58 and 65, including both ends**.

Why those numbers?

Because they're the values chosen for this particular strategy version.

They're not universal laws of the stock market.

An RSI of 57 doesn't mean a company is bad.

An RSI of 66 doesn't mean a crash is coming.

It simply means that Robo's chosen RSI condition has not been satisfied.

And because both ends are included, a reading of exactly 58 or exactly 65 passes that particular test.

### The ADX gauge

The second measurement is called the **Average Directional Index**, or ADX.

ADX helps describe how strong a trend is.

But here's the important part.

**ADX doesn't tell Robo whether the trend points upwards or downwards.**

That's why Robo also needs its separate trend-direction rule.

For SignalForge's initial strategy, **ADX14 must be greater than 22**.

Notice the word *greater*.

A reading of exactly 22 fails.

A reading of 23 passes.

Robo checks both momentum-related conditions.

RSI must be in its chosen range.

ADX must be above its chosen threshold.

*"This detective business involves rather a lot of paperwork,"* Robo observes.

Quite right.

Good evidence often does.

## Clue number three: Where did the latest candle finish?

Robo has examined the broader price trend.

It has checked the two movement gauges.

Now it turns to the latest completed candle.

Remember EMA20 and EMA50?

There's another EMA in the rulebook: **EMA9**.

This one responds more quickly to recent prices.

For the setup condition, the candle's closing price must be **greater than EMA9**.

Not equal to it.

Greater than it.

Suppose the candle closes at ₹101 and EMA9 is ₹100.

That condition passes.

If both are ₹100, it fails.

Why be so fussy about such a small distinction?

Because a strategy is only repeatable when the rules mean the same thing every time.

If the rule says *greater than*, we don't quietly change it to *greater than or equal to* just because we like how the chart looks.

Changing that comparison could change which opportunities the software recognises.

And that means changing the strategy.

## Robo examines the complete case file

Now our detective has four numerical checks to perform.

Let's imagine Robo examining a completed candle.

The readings below are fictional, independently chosen to illustrate the comparisons. They are not values calculated from a real or reconstructed price history.

| Clue | Fictional reading | Verdict |
|---|---|---|
| EMA20 above EMA50? | 101 > 100 | Pass |
| RSI14 between 58 and 65? | 60 | Pass |
| ADX14 greater than 22? | 21 | Fail |
| Candle close above EMA9? | 102 > 101 | Pass |

Robo looks at the results.

Three passes.

One failure.

*"But surely three out of four is good enough?"*

Not for this strategy.

Every required numerical condition must pass.

ADX is 21.

The rule requires a number greater than 22.

So the numerical qualification fails.

There is no qualifying opportunity from this case.

Robo cannot make an exception because the share looks exciting.

**A strategy is only repeatable if it applies the same rules every time.**

## What if all the clues agree?

Now let's change just one detail.

Suppose ADX14 reads 23 instead of 21.

Everything else remains the same.

The trend condition passes.

RSI is in range.

ADX is above 22.

The closing price is above EMA9.

Robo straightens its detective's hat.

*"All four clues agree! Case solved!"*

Almost.

There's one more distinction.

**Passing the numerical checklist doesn't automatically mean Robo is allowed to act.**

Imagine a detective who has found several convincing clues.

But just as the detective prepares to make a decision, the radio connection to the investigation team fails.

The detective can still describe the clues already collected.

But it would be foolish to pretend that new information is arriving normally.

Something similar can happen in SignalForge.

Suppose every numerical condition passes, but the incoming market-data feed has become stale.

The strategy can still record that the numerical conditions qualify.

However, a separate safety check prevents the decision from becoming **actionable**.

Robo's response is straightforward:

*"The numbers pass, but I cannot safely proceed."*

Other checks also matter, including whether the necessary indicator history is ready, whether market information remains continuous, and whether the decision falls within the permitted signal window.

For this strategy, numerical qualification and permission to act are separate decisions.

Think of it this way:

**Qualification asks:** *"Do the clues match the rulebook?"*

**Actionability asks:** *"Are the operating conditions acceptable for using this opportunity?"*

Both must be satisfied before the system can proceed towards an entry.

## What about MACD?

There's one more indicator hiding in Robo's notebook.

It's called **MACD**.

Another impressive collection of letters.

For SignalForge's initial strategy, MACD is calculated and recorded as diagnostic information.

That means it can help researchers examine the measurements associated with a trading decision.

But it is **not one of the conditions that decides whether an opportunity qualifies**.

Imagine the detective photographs the street outside the mysterious house.

The photograph might be useful when reviewing the case.

But the detective's actual checklist doesn't require the photograph to show a red car.

It would be wrong to invent a new rule saying:

*"The case only passes if there's a red car in the photograph."*

The same applies here.

Robo records MACD but must not secretly give it an extra deciding vote.

Otherwise, it's no longer following the approved rulebook.

## Once the clues agree, what happens next?

Suppose Robo has a qualified, actionable opportunity.

That still isn't an instant purchase.

As Chapter 2 explained, the opportunity can become **ARMED** — ready to watch for a further entry condition.

For SignalForge's initial NSE strategy, the entry-trigger price starts with a simple calculation:

**The qualifying candle's closing price multiplied by 1.001.**

That's 0.1% above the signal close before applying the relevant exchange price-step rules.

Robo's opportunity is valid only during the immediately following five-minute candle.

It can also be invalidated before an entry.

If the trigger doesn't occur while the opportunity remains valid, the robot can't save it for another day.

And even when a trigger occurs, Robo hasn't necessarily purchased shares.

As we learned in Chapter 2, execution depends on the operating mode, and a fill must be distinguished from the trigger.

Our detective has found a possible opportunity.

Whether that opportunity leads to a recorded trade is another stage of the process.

## The stop, the target and the possibility of being wrong

Now imagine Robo's trading process records an entry fill.

The strategy needs a plan for what happens next.

In SignalForge's initial strategy, the **stop reference** is the low of the candle that produced the qualifying signal.

The defined risk per share is the fill price minus that stop.

If the resulting risk is zero or negative, it isn't an acceptable positive-risk long entry.

For a valid entry, the raw target is set **1.5 times that per-share risk above the fill price**.

Suppose a fictional trade has ₹10 of defined risk per share.

Its raw target would be ₹15 above the fill price.

That's all *1.5R* means here.

It isn't a prediction that the price will rise by ₹15.

It isn't a promise of profit.

It's simply the strategy's rule for calculating a target.

The system also applies the appropriate price-step rules when turning raw calculated levels into valid tradable prices.

And remember: reaching a planned stop or target doesn't guarantee an exit at exactly that price.

Markets are not obliged to cooperate with Robo's notebook.

## A perfectly obedient detective can still be wrong

By now, Robo is rather proud of itself.

It knows which clues to check.

It knows which comparisons are strict.

It knows when a clue doesn't count.

It can explain why an opportunity qualified or failed.

It can also distinguish a good-looking set of numbers from an opportunity it is actually permitted to use.

That's useful.

But does it mean Robo's strategy is profitable?

No.

Imagine a detective who follows an investigation checklist perfectly.

Every document is filed.

Every question is asked.

Every clue is recorded.

And yet the detective reaches the wrong conclusion because the checklist itself is inadequate.

A trading strategy can have the same problem.

The software might implement every rule correctly.

Its decisions might be completely reproducible.

But the strategy could still produce losing trades.

That's why SignalForge must answer two different questions:

**Did Robo follow the strategy correctly?**

**Is the strategy actually worth using?**

The first is largely an engineering question.

The second requires trading research and convincing evidence.

We need to investigate both.

## Remember this

Robo's detective notebook now contains a proper case file.

Completed market candles.

Trend measurements.

Momentum-related gauges.

A setup condition.

A clear explanation of what passed and what failed.

And separate checks for whether the system is permitted to act.

That's what a rule-based strategy does.

It examines information and makes repeatable decisions.

But a complete case file doesn't guarantee the detective's conclusion is correct.

And a qualifying trading opportunity doesn't guarantee a profitable trade.

**A strategy doesn't know what will happen next. It only knows what its rules say about the information available now.**

Our detective can follow every clue perfectly and still be wrong about the market.

So where does Robo get the information needed for all these calculations?

And how can we tell whether that information is reliable?

**That's where Chapter 4 begins: Teaching the Robot About Markets.**
