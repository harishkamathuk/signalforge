# Chapter 4 — Teaching the Robot About Markets

*Robo goes back to school and discovers that a missing page can be more dangerous than a difficult question.*

## Robo's first day at school

After solving several imaginary market mysteries in Chapter 3, Robo is feeling rather clever.

It has learned to examine clues.

It knows how to check a trading strategy's rules.

It even has a little detective's hat.

But today, Robo has a new assignment.

**Back to school.**

The teacher hands Robo a report card.

"Here are your marks," she says. "Please calculate the average."

Robo examines the page.

Mathematics: 90.

Science: 85.

English: 88.

History: ...

Hang on.

The History mark is missing.

"No problem!" announces Robo. "I'll put down 90. That seems reasonable."

The teacher nearly drops her cup of tea.

"You can't invent a mark because one is missing!"

"But then I can't finish the calculation," complains Robo.

"Exactly," replies the teacher. "Sometimes the correct answer is that you don't have enough information."

And that is one of the most important lessons Robo will ever learn about financial markets.

**A computer that calculates perfectly from unreliable information can still produce an unreliable result.**

## Where does market information come from?

Let's imagine we're watching shares being traded on India's National Stock Exchange.

People submit orders to buy and sell.

Trades happen when compatible orders are matched.

The exchange records information about market activity.

Market-data providers can then deliver information about prices, quantities, trades, quotes and other observations.

But there's an important difference between something happening in the market and a computer receiving a message about it.

Imagine a teacher looking through a classroom window.

Sometimes the teacher sees a pupil complete an exercise.

Sometimes another teacher sends a summary saying, "The pupil has finished three exercises."

Those are different kinds of evidence.

One describes something directly observed.

The other reports a snapshot of what is known at a particular moment.

SignalForge can receive live market information through a provider called OpenAlgo.

In its accepted live PAPER setup, ordinary provider messages can be **quote snapshots**, rather than a complete list of individually identified exchange trades.

A snapshot tells Robo something about the market information being reported.

It doesn't automatically prove that Robo has received every individual market event.

Nor does it necessarily come with a unique event identifier and a sequence that could be replayed later without gaps.

That's why SignalForge must not pretend the provider supplied evidence it didn't actually supply.

Robo has several questions to ask:

Which company share is this information about?

What kind of observation is it?

When does the source say the information belongs?

When did Robo's computer receive it?

And is there enough evidence to trust its place in the market's history?

Suppose a school examination finishes at noon, but the teacher doesn't receive the papers until half past twelve.

The papers don't suddenly become half-past-twelve examinations.

In the same way, **when something happened or was observed in the market** may differ from **when Robo received the message**.

Different providers can also describe timestamps in different ways.

SignalForge needs explicit rules and supporting source evidence to interpret them.

Otherwise, Robo might place the right number in the wrong period.

And the teacher would not be pleased.

## Five minutes in a little report card

In Chapter 3, Robo examined something called a *candle*.

Now it's time to understand what that means.

Imagine the market is open and Robo wants a summary of what happened during five minutes.

Rather than describing every individual observation, it can use a report with five familiar headings.

These are usually called **OHLCV**.

That stands for:

- **Open:** the first price in the interval, according to the accepted data source and construction rules.
- **High:** the highest price recorded for that interval.
- **Low:** the lowest price recorded for that interval.
- **Close:** the final price recorded for that interval.
- **Volume:** the quantity of trading activity represented by the accepted data.

Think of a schoolteacher preparing a short report about a running race.

The report might tell us where a runner began, the furthest and nearest points reached, where the runner finished and how much activity occurred.

It's a summary.

It isn't a recording of every second of the race.

Let's invent a five-minute market report for Robo.

| Measurement | Fictional value |
|---|---:|
| Open | ₹100 |
| High | ₹104 |
| Low | ₹99 |
| Close | ₹102 |
| Volume | 1,500 shares |

These figures are fictional. They aren't measurements from an actual NSE trading session.

The report tells us that the price started at ₹100 and finished at ₹102, with a highest recorded price of ₹104 and a lowest of ₹99.

But here's a question.

**Did the price reach ₹104 before falling to ₹99, or did it fall to ₹99 before climbing to ₹104?**

The report doesn't tell us.

Both journeys could produce exactly the same summary.

That's why a completed candle is useful, but it doesn't establish the full order of events inside the interval.

And that matters more than Robo might think.

## Why must the candle be finished?

Robo glances at its computer.

It's 10:02.

A five-minute candle covering 10:00 to 10:05 is still forming.

The latest price shown is ₹103.

"Excellent!" Robo announces. "I'll use ₹103 as the closing price."

Not so fast.

The period hasn't finished.

The price could change before 10:05.

The final high, low, close and volume might be different from the figures Robo sees at 10:02.

Imagine a teacher writing a pupil's final examination mark while the pupil is still answering questions.

That wouldn't make sense.

SignalForge's initial NSE strategy uses **completed five-minute candles** for its indicator-based decisions.

Robo must not treat a partly written report as the final version.

The time boundaries matter too.

A candle covering 10:00 to 10:05 contains observations assigned to that particular interval.

The next interval begins at 10:05.

SignalForge uses explicit time boundaries so that observations are grouped consistently.

If two computers construct different candles from the same underlying evidence, they could arrive at different decisions while claiming to follow the same strategy.

A reliable report card needs a reliable timetable.

## The day a page went missing

Now the teacher has another exercise.

Suppose Robo receives historical market information organised into one-minute reports.

It must build a five-minute report covering 09:15 to 09:20.

For this particular historical-data process, that means checking five expected one-minute records.

Robo examines the folder.

| One-minute interval | Report available? |
|---|---|
| 09:15–09:16 | Yes |
| 09:16–09:17 | Yes |
| 09:17–09:18 | **No** |
| 09:18–09:19 | Yes |
| 09:19–09:20 | Yes |

"Oh dear," says Robo. "The middle page is missing."

"Perhaps nothing happened during that minute," suggests a classmate.

Perhaps.

But perhaps trades happened and the data provider failed to supply the report.

The missing page doesn't tell us which explanation is correct.

**Missing information is not proof that nothing happened.**

Robo must not invent a flat price for the missing minute.

It must not borrow the previous minute's price and pretend that a genuine record has been found.

Under SignalForge's accepted historical one-minute-to-five-minute aggregation rules, this five-minute result is **INCOMPLETE**.

Four valid pieces out of five do not make a valid, complete five-minute research candle.

And there is an important consequence.

In SignalForge's implemented historical-bar research workflow, encountering this incomplete candle makes the run report a continuity failure.

**Robo stops the research run rather than skip the gap and quietly continue as though the history were complete.**

The teacher nods.

"Correct. A missing page is something to investigate, not something to hide."

One important detail: this five-out-of-five requirement applies to this specific historical aggregation process.

It does **not** mean that every live five-minute candle must contain a separate market event in every one of its five minutes.

Historical one-minute bars and live provider observations have different evidence contracts.

We shouldn't pretend they're interchangeable.

## Not every report card deserves a gold star

Robo's teacher introduces four labels used when working with historical candle information.

**VALID:** The particular record or derived candle has passed the checks required for its stated purpose and construction.

**INCOMPLETE:** Some required information for the aggregate is absent.

**MISSING:** No source observation is available for the expected interval, so there are no legitimate prices or volume to invent.

**CORRUPT:** The available information violates an important rule or contradicts other evidence.

Consider a report saying:

Opening price: ₹100.

Highest price: ₹98.

Closing price: ₹101.

Robo scratches its head.

How could the highest price be ₹98 if the closing price was ₹101?

It couldn't.

Something about the report is wrong.

Robo must not pick whichever number looks most convenient.

But the teacher has another question.

"If one report is marked VALID, does that prove the whole school has kept perfect records?"

"Of course not," says Robo.

Exactly.

**VALID is not a magic certificate declaring an entire historical dataset trustworthy.**

A particular one-minute bar might pass its structural checks while other questions remain unanswered.

Are all the expected periods covered?

Do we know where the data came from?

Were the provider's timestamps interpreted correctly?

Are the instrument details reliable?

Has the dataset satisfied the separate evidence requirements for the research someone wants to perform?

Those questions need their own answers.

A VALID record isn't automatically a validated trading experiment.

And it certainly isn't proof that an order could have been executed at a particular historical price.

Robo adds a note to its folder:

*"Passing one test doesn't mean passing every test."*

## What happens when news arrives late?

The school day continues.

Now the teacher starts sending Robo updates through a classroom radio.

For a while, the radio works beautifully.

Robo receives its messages.

Then the sound crackles.

Silence.

A few minutes later, the connection returns.

"Everything is fine!" says Robo.

"Is it?" asks the teacher.

"The radio works again."

"But what happened while you couldn't hear me?"

Robo pauses.

It doesn't know.

And that's the problem with a live market-data interruption.

SignalForge distinguishes three things: whether the connection is working, whether the market history is complete enough to trust, and what the last authoritative saved trading state says.

They are not interchangeable.

A connection can recover successfully while leaving an interval of market activity that Robo cannot reconstruct reliably.

Under SignalForge's accepted live PAPER contract, when a genuine interruption makes that chronology unprovable, the system must **fail closed**.

That means it must not simply resume price-sensitive decisions as though nothing happened.

Suppose Robo had an **ARMED** trading opportunity.

It cannot guess whether the entry trigger was reached during the interruption.

Or suppose a PAPER position was already **OPEN**.

Robo cannot invent whether its stop or target was reached during the gap.

It also must not automatically close or erase the saved position merely because the connection was interrupted.

Instead, SignalForge preserves the last trusted durable trading state and blocks further same-run price-sensitive progression until the uncertainty is addressed through reconciliation.

That's rather technical.

Here's the classroom version:

**Keep the last report card you can trust. Mark the missing period as uncertain. Don't invent what happened.**

And remember: getting the radio working again doesn't fill in the missing pages.

This is an account of SignalForge's accepted PAPER operation. It is not a claim that future live-capital trading already has every necessary broker-reconciliation or emergency-protection mechanism.

## Robo needs yesterday's homework too

There's another problem.

Imagine Robo arrives at school with a perfectly working computer.

The latest five-minute candle is complete.

The market-data source is healthy.

Everything seems ready.

"Let's calculate all my indicators!" says Robo.

But some indicators need enough earlier price information before their readings can be trusted for strategy evaluation.

One completed candle is not enough.

Think of a teacher asked to decide whether a pupil has been improving for several weeks.

The teacher needs earlier marks too.

SignalForge's initial NSE strategy has a specific warmup condition: **at least 250 completed regular-session candles** must have been counted.

But that count is not the only requirement.

The indicators must also be ready, their history must have acceptable continuity, and the other safeguards must pass.

It's like having 250 pages of homework.

The number of pages matters.

But the teacher still needs to know that the pages belong to the correct pupil and have not been scrambled or damaged.

For its live PAPER operation, SignalForge prepares the required indicator history before the target trading session.

A separate preparation step checks or builds suitable indicator state from completed historical candles and preserves a trustworthy checkpoint.

Those historical preparation candles are not quietly turned into fake live market events.

They are also not passed through the trading lifecycle to generate pretend historical trades.

Robo must arrive at school with properly prepared notes.

If those notes are missing, incompatible or unreliable, it cannot simply declare itself ready.

## Can Robo use an old report as a fresh event?

The teacher brings out a large box of old report cards.

"Here's a record of previous school years," she says.

Robo brightens.

"Excellent! I can recreate every conversation that happened in those classrooms!"

"Can you?" asks the teacher.

Robo looks at one card.

It records a pupil's final mark.

But it doesn't show which questions were answered first.

It doesn't record when the pupil changed an answer.

It doesn't show everything the teacher said.

A summary can tell us **what the result was** without telling us **the exact order in which everything happened**.

Historical market candles are similar.

A candle can show its high and low.

But it doesn't necessarily tell us which price came first.

Imagine a historical candle that reached both a hypothetical trading target and a hypothetical stop.

Without suitable evidence about the order of events, Robo cannot simply choose whichever outcome makes its strategy look better.

SignalForge therefore distinguishes two ways of studying the past.

**Historical-bar research** works with properly qualified price summaries. It can calculate indicators and investigate completed-candle strategy signals.

**Market-event replay** works with event-level information where the ordering and evidence of those events matter.

The two approaches may share strategy calculations, but their source evidence is not automatically equivalent.

And a historical price summary must not be transformed into a made-up stream of trades.

Robo closes the old report-card box.

"I understand," it says. "A summary helps me study the past. It doesn't tell me every moment of the past."

Exactly.

In Chapter 5, we'll explore how a trading time machine can study historical information without pretending to know things the records never revealed.

## The teacher's final examination

At the end of the day, Robo's teacher places three folders on the desk.

The first contains complete records that have passed their applicable checks, with the supporting evidence needed for the exercise.

The second contains records with missing pages.

The third contains contradictory numbers.

"Which folder can you use for the assignment?" she asks.

"The first, provided it also meets the assignment's wider evidence requirements," Robo replies.

"Very good. And what about the others?"

"Record the problems. Don't invent missing information. Don't pretend contradictory figures are correct."

"Excellent."

"Can I go home now?"

"One more question," says the teacher.

"Suppose you follow every calculation perfectly using trustworthy market information. Will your trading strategy make money?"

Robo thinks carefully.

"No. Reliable data helps me make reproducible decisions. It doesn't guarantee that those decisions will be profitable."

The teacher smiles.

**Top marks.**

## Remember this

Markets produce activity.

Providers deliver observations and summaries about that activity.

Those messages don't automatically provide a complete, replayable account of every market event.

SignalForge must interpret the information using explicit timestamps, identities, quality rules and source evidence.

Completed candles summarise accepted market observations.

Indicators need sufficient trustworthy history.

Missing, incomplete or contradictory records must be handled honestly.

A recovered connection doesn't prove that nothing was missed during an interruption.

And a historical price summary doesn't reveal the exact sequence of every price movement inside its interval.

Robo has learned to ask a new question before trusting a calculation:

**"Do I actually know enough about this information to use it?"**

That's much more useful than merely asking whether the numbers look interesting.

But now Robo has an idea.

If it has suitable records from the past, perhaps it can revisit those markets and investigate how its strategy would have behaved.

Almost like travelling backwards through time.

**That's where Chapter 5 begins: The Trading Time Machine.**
