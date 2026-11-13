# Chapter 5 — The Trading Time Machine

*Robo builds a machine that can revisit yesterday's markets. But there is one very important rule: no peeking at tomorrow.*

## A mysterious machine in the classroom

Robo has had an extraordinary week.

First, it learned to think like a detective.

Then, it went back to school and discovered why missing market information is such a serious problem.

Now it has a new ambition.

"I want to travel through time!" announces Robo.

The teacher looks up from her desk.

"Why?"

"Because I want to know whether my trading strategy would have worked yesterday!"

The teacher considers this.

Then she opens a cupboard.

Inside stands a rather peculiar machine.

It has a clock, a computer screen, a large red button and a sign:

**THE TRADING TIME MACHINE**

Robo gasps.

"Is it real?"

"It's a teaching machine," replies the teacher. "It can help us study records of the past."

"Brilliant! So I can find out which shares went up, travel backwards and buy them!"

The teacher folds her arms.

"No, Robo."

"Why not?"

"Because that would be cheating."

And so begins Robo's most important lesson about studying historical markets.

## Rule number one: No peeking into the future

Imagine Robo travels back to Monday morning.

It's 10:00.

On Monday afternoon, a company's share price will rise sharply.

But Robo must not know that yet.

If Robo makes its Monday-morning decision using Monday-afternoon information, the experiment is unfair.

That's like giving a pupil tomorrow's examination answers today.

The pupil might achieve a perfect score.

But the score wouldn't tell us how well the pupil understands the subject.

Historical trading experiments face the same problem.

It's called **look-ahead bias**.

A trustworthy experiment must respect what information would have been available at each decision point.

For SignalForge's initial NSE strategy, that means using the appropriate completed five-minute candles and the indicator history available at the time.

Suppose a candle covers 10:00 to 10:05.

At 10:02, the candle isn't finished.

Robo cannot use its eventual 10:05 closing price to justify a decision supposedly made at 10:02.

It also cannot use the next hour's prices to decide whether a signal should have appeared five minutes earlier.

There's another rule.

Imagine the completed 10:00–10:05 candle creates a new trading opportunity.

Robo cannot then travel backwards inside that same candle and claim it entered the trade because the price touched its trigger at 10:03.

At 10:03, the completed-candle opportunity didn't exist yet.

SignalForge's accepted historical-execution rules therefore do not allow the one-minute records that formed a completed signal candle to be reused as later execution evidence for the opportunity it created.

Robo must look to eligible subsequent market evidence, under the accepted strategy and execution rules.

"Even if the earlier price would have made me money?" asks Robo.

"Especially then," replies the teacher.

The time machine may know how the day eventually ended.

**The Robo inside the experiment must not.**

"That sounds difficult," says Robo.

"That's why we have rules," replies the teacher.

## What does replay actually mean?

The teacher turns a dial on the machine.

A screen displays a sequence of historical market observations.

"Now imagine that we feed suitable records into SignalForge in their proper order," she says.

"One observation at a time?"

"Where we have an appropriate event-level replay source, yes."

As those inputs are processed, SignalForge can construct candles, calculate indicators and apply the registered strategy's rules.

This is the idea behind **replay**.

Instead of waiting for the market to unfold in real time, the system processes an already recorded sequence.

Think of watching a recording of a football match.

The match has finished, but you can watch the action unfold from the beginning.

You can pause at a particular moment and ask:

"What would a player have known right now?"

Or:

"What decisions would the rules have allowed at this point?"

But Robo needs to remember something.

A football recording is useful only for what it actually shows.

If the camera missed part of the match, watching the video again cannot reveal those missing events.

The same applies to historical market information.

A replay can only establish what its accepted input evidence supports.

And if the data was invented merely for a software test, replaying it does not magically turn it into genuine historical market evidence.

## Two different notebooks from the past

The teacher places two notebooks on the desk.

The first contains an accepted, ordered collection of event-level replay inputs.

The second contains price summaries.

Robo recognises the second notebook immediately.

"Candles! Open, high, low, close and volume!"

"Correct."

The teacher explains that SignalForge has different ways to study these two kinds of information.

### Notebook one: Event-based replay

Suppose Robo has a suitable sequence of market-event records.

SignalForge's event-based replay and backtesting path can consume those records through its canonical replay interface.

It can use the existing trading runtime and lifecycle rules rather than inventing a separate strategy for historical study.

That matters because we want the rulebook to mean the same thing in different settings.

But there's a catch.

Having a well-formed collection of replay inputs does not automatically prove that the records are a complete account of actual exchange trades.

A reproducible source identity proves which accepted input records were used in that experiment. It does not, by itself, prove that the provider captured every event or that the underlying observations have been independently authenticated.

Remember Chapter 4?

Sometimes a provider supplies snapshots rather than a complete sequence of exchange trades.

Giving those observations an identity doesn't create the missing events.

An event-based research source therefore needs suitable identity, ordering, timestamps, boundaries and provenance. Its suitability for a particular historical claim needs separate evidence.

A fictional test file may be excellent for checking software behaviour without proving that any real market traded that way.

### Notebook two: Historical-bar research

Now suppose Robo has only historical one-minute price summaries.

Each summary reports the open, high, low, close and volume for its interval.

After the applicable data checks, SignalForge can combine qualifying one-minute bars into completed five-minute candles.

Those candles can feed the indicator engine and the strategy's completed-candle evaluation.

This helps Robo investigate questions such as:

"Would the available completed-candle information have satisfied the strategy's signal conditions?"

But this particular historical-bar research path does not, by itself, recreate every market event after the signal.

It doesn't automatically establish actual entries, exits or broker fills.

"Why can't we just make up the events between the high and low?" asks Robo.

"Because then we'd be studying your imagination," replies the teacher, "not the evidence."

## The puzzle of two possible journeys

The teacher brings out a fresh report card.

It contains a fictional one-minute price summary.

| Measurement | Price |
|---|---:|
| Open | ₹100 |
| High | ₹104 |
| Low | ₹96 |
| Close | ₹100 |

"Tell me what happened," she says.

Robo studies the numbers.

"The price started at ₹100, reached ₹104, fell to ₹96 and finished at ₹100."

"Are you sure it reached ₹104 before ₹96?"

Robo thinks.

"Actually, no."

Exactly.

The price might have risen to ₹104 first, then fallen to ₹96.

Or it might have fallen to ₹96 first, then climbed to ₹104.

Both journeys are consistent with the same OHLC summary.

Now imagine a fictional position was already open before this one-minute interval began.

It has a stop at ₹97 and a target at ₹103.

Both levels are inside the candle's price range.

But which one was reached first?

Robo cannot tell from these four prices alone.

If the target came first, one possible story is a successful exit.

If the stop came first, another possible story is a losing exit.

The teacher asks:

"Which story should the time machine choose?"

Robo smiles.

"The profitable one!"

The teacher raises an eyebrow.

"Sorry. I mean neither one unless the evidence and the accepted rules justify it."

Much better.

**When historical evidence supports several materially different outcomes, a responsible simulation must not silently choose its favourite.**

## What if we still want to study possible trades?

Robo looks disappointed.

"So historical price summaries are useless for studying trading outcomes?"

"Not at all," says the teacher. "We just need to be precise about what we're doing."

SignalForge has a separate capability for **historical bar-evidence execution simulation**.

That's a long name, but the basic idea is manageable.

The simulator takes suitable historical bar evidence, the strategy's accepted trading intentions, and explicitly stated execution assumptions.

It can then investigate what outcomes the available evidence supports.

The important word is **supports**.

For example, a historical bar can establish that a price level was reachable during that interval.

But if the bar contains both a stop and a target, the simulator may not know which came first.

SignalForge's accepted historical-execution contract distinguishes three broad results.

**Determinate:** The available evidence and accepted assumptions lead to one supported lifecycle and economic outcome.

**Bounded ambiguous:** The evidence supports a limited set or range of materially different possible outcomes.

**Unresolved:** The available information and current simulation rules cannot safely establish the material outcome possibilities.

In our fictional stop-and-target example, the outcome can be bounded ambiguous rather than automatically called a win or a loss—provided the other accepted lifecycle and execution conditions support those alternatives.

"That sounds less exciting than announcing a winner," says Robo.

"Perhaps," replies the teacher. "But it's more useful than an invented answer."

### Can the time machine keep going?

The teacher gives Robo another puzzle.

"Suppose the records show two possible endings. Can you continue the experiment?"

"Always?" asks Robo.

"Not always."

Imagine one possible history ends with the position closed at its stop.

Another possible history ends with it closed at its target.

The money result is uncertain, but both possibilities leave the position **CLOSED**.

Under SignalForge's accepted historical-execution rules, that kind of bounded stop-versus-target case may allow the research run to continue because the future lifecycle state is the same.

Now imagine one possible history says a trading opportunity expired without entry.

Another says an entry happened and a position may still be open.

Those histories leave Robo in different situations.

It cannot choose one and carry on as though the other had never been possible.

**When different possible histories would lead to different future trading states, Robo must not invent a single history just to keep the machine running.**

Under the current execution contract, such ambiguity can terminate the run.

And sometimes the correct result really is **unresolved**.

If a required historical minute is missing while an entry opportunity or modeled position is active, SignalForge's current historical-execution runner can record missing execution evidence and terminate rather than invent what happened.

A trading time machine must know when to stop.

## The difference between a fact and a guess

The teacher draws two columns on the board.

Under the first, she writes:

**WHAT THE RECORDS SUPPORT**

Under the second:

**WHAT THE SIMULATION ASSUMES**

Robo helps fill them in.

A historical bar's high, low and interval boundaries belong in the first column, provided the source has passed the required checks.

A chosen slippage rule belongs in the second.

"So what's slippage?" asks Robo.

Imagine a trader wants to buy at one price, but the assumed or actual execution happens at a less favourable price.

That difference can affect the result.

Historical simulations need an explicit model when they assign execution prices.

SignalForge's accepted bar-evidence simulator requires an identified execution-assumption profile and applicable tick-size rules.

A zero-slippage reference profile is still an assumption.

It doesn't prove real orders would have executed without slippage.

And a modeled fill isn't the same thing as a broker-confirmed fill.

The teacher makes Robo write this down in large letters:

**SIMULATED DOES NOT MEAN OBSERVED.**

Historical simulation can be useful precisely because its assumptions are declared and repeatable.

But a model shouldn't claim to have witnessed a trade that never took place.

## The experiment needs a name tag

Robo presses the red button again.

The time machine produces a result.

Then Robo runs the experiment a second time.

The result is the same.

"Hooray! My strategy is profitable!"

"Not so fast," says the teacher.

"What have you actually proved?"

Robo considers the question.

"That the machine repeated the same experiment and got the same answer?"

"Correct."

This property is called **reproducibility**.

Imagine a science experiment.

To repeat it properly, you need to know which ingredients were used, what equipment was involved and what procedure was followed.

Trading research needs similar information.

SignalForge records identities and provenance for material research inputs, including the registered strategy and version, its configuration, the data being studied, and the relevant calculation and execution settings.

The exact details vary with the research path.

For example, event-based replay needs an identity for its exact canonical event source.

Historical-bar research needs suitable dataset identity, expected coverage and timestamp interpretation.

Historical execution additionally records its assumptions, tick-rule identity and simulator calculation version.

Think of it as giving the experiment a fingerprint.

If Robo changes the strategy version, uses different historical records or changes a material execution assumption, it may no longer be running the same experiment.

The output needs to remain traceable to what was actually used.

And this raises a very important point.

**Getting the same answer twice proves consistency under the chosen inputs and rules. It does not prove that the answer describes a profitable real-world trading strategy.**

A classroom test can demonstrate that the machine works.

It isn't proof that the machine can make money.

## Can we believe the results?

Robo is beginning to understand.

"Suppose the time machine shows several successful trades," it says. "Can I celebrate?"

"You may celebrate that the experiment produced a result," replies the teacher. "But first you need to understand what that result means."

Were the historical records genuinely qualified for the intended research?

Did the strategy use only information available at each decision time?

Were any outcomes ambiguous?

Which execution assumptions were applied?

Were the figures gross, before costs, or did the model actually include the relevant expenses?

Did the reported statistics describe the whole set of opportunities—or only those whose outcomes could be determined?

SignalForge's event-based research example includes a deterministic *golden experiment*.

That example is valuable for proving that the research machinery can reproduce the same outputs under the same inputs.

But the fixture is not evidence that the strategy is profitable.

Similarly, the historical bar-evidence simulator may report statistics for the **determinate subset** of outcomes.

If some opportunities remain ambiguous or unresolved, the statistics must not be presented as though every opportunity produced a known win or loss.

The report must also make the coverage limitation visible.

And even a perfectly reproduced historical result tells us nothing certain about tomorrow.

Robo sighs.

"There seem to be quite a lot of warnings attached to this time machine."

"There are," says the teacher.

"Is that because trading is difficult?"

"Partly. But mostly because it's very easy to confuse an impressive-looking result with trustworthy evidence."

## One last trip through time

The teacher gives Robo a final assignment.

"Tell me what you've learned."

Robo closes its eyes and imagines travelling back to the beginning of a trading day.

First, it checks which historical records are available and whether they meet the experiment's requirements.

Then it makes sure it doesn't peek ahead.

Where suitable event-level replay inputs exist, it can process their accepted chronology through SignalForge's existing runtime—without claiming more about the real market than the source evidence establishes.

Where it has qualified price summaries, it can investigate completed-candle signals without manufacturing missing events.

If it wants to examine possible historical trade outcomes from bars, it must use the separate execution model, identify its assumptions and respect uncertainty.

It must not use a price movement inside the signal candle as if that movement happened after the signal.

It must also stop rather than invent a future path when the possible lifecycle states cannot safely be reconciled.

It must keep track of the strategy, data and calculation versions used.

And whatever the result says, it must not confuse a simulation with a real trade—or reproducibility with profitability.

"Excellent," says the teacher.

"So can I have a real time machine now?" asks Robo.

"No."

"A small one?"

"No."

"One shaped like a toaster?"

"Go and finish your homework."

Robo smiles.

It has discovered something more useful than a magical machine that predicts winning trades.

It has learned how to ask careful questions about the past.

## Remember this

Historical replay lets SignalForge study what its accepted rules would do with suitable recorded inputs.

Historical-bar research can examine completed-candle signals without pretending that OHLCV summaries contain every market event.

Historical bar-evidence execution simulation can investigate possible trade outcomes under declared assumptions, but it must preserve ambiguity.

No experiment may use future information as though it were known earlier.

A completed signal cannot claim execution evidence from the price history used to create that signal.

A modeled fill isn't a real broker fill.

A repeated result isn't proof of profitability.

A reproducible event source doesn't automatically establish complete exchange history.

And missing or uncertain evidence must remain visible rather than being quietly turned into a convenient answer.

The trading time machine helps Robo investigate the past.

**It does not give Robo permission to rewrite the past.**

But now a new question arises.

Suppose Robo runs a historical experiment and gets a beautiful set of results.

How can it tell whether those results deserve to be trusted?

**That's where Chapter 6 begins: Can We Trust the Results?**
