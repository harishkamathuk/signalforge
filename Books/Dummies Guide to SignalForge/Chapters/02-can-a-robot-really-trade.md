# Chapter 2 — Can a Robot Really Trade?

*Meet a very obedient employee who never gets bored, never panics, and still needs someone to explain exactly what to do.*

## Meet your newest employee

Imagine hiring someone to watch the stock market for you.

They arrive at work exactly on time.

They don't need coffee, never take lunch breaks, and can watch prices change all day without getting bored.

Sounds like an excellent employee.

There's just one small detail.

Your new employee is a computer.

Let's call our imaginary assistant **Robo**.

Robo is punctual, patient and astonishingly obedient.

Unfortunately, Robo doesn't know which shares are good investments. It cannot see the future. And if you give it terrible instructions, it may follow them with impressive dedication.

So here's our question.

**Can Robo actually trade shares?**

Yes. Computers can be programmed to participate in financial markets.

But there's quite a difference between spotting an opportunity, deciding to act, asking to buy something and actually completing a purchase.

Let's follow Robo through an imaginary trading day to understand how it works.

## The world's most patient employee

It's a weekday morning in India.

The regular trading session on the National Stock Exchange, or NSE, begins at 9:15.

Robo is watching the price of one company share.

Prices change as buyers and sellers respond to the market.

Robo watches.

And watches.

And watches.

Nothing particularly interesting happens.

Ten minutes pass.

Then twenty.

Still nothing.

A human trader might become restless.

*"Surely I should do something by now?"*

But Robo has an advantage.

It doesn't get bored.

Imagine a security guard whose instructions are to open a gate only when an authorised visitor arrives.

If nobody arrives, the guard shouldn't open the gate just for entertainment.

A trading robot works on a similar principle.

It waits for the conditions defined by its trading strategy.

There might be several opportunities today.

There might be none.

**Doing nothing is sometimes exactly the right decision.**

## What exactly is Robo watching?

Let's imagine that Robo is monitoring a share whose price is around ₹1,000.

The price moves up and down throughout the morning.

But a changing price doesn't automatically mean it's time to buy.

Robo needs rules.

As we learned in Chapter 1, SignalForge's initial NSE strategy uses completed five-minute periods of market information, called **candles**.

Each candle summarises what happened during those five minutes.

It includes the opening price, highest price, lowest price and closing price. Volume can also be recorded.

Think of a candle as a little market report card.

For its strategy decisions, Robo waits until the report card is complete.

It then examines the finished candle alongside earlier market information.

Why wait?

Imagine checking a cricket score halfway through an over and pretending you already know the final result.

You might be right.

But you might be very wrong.

A completed candle gives the strategy a definite set of information to evaluate.

The robot can then apply its rules consistently, without quietly peeking into the future.

## A possible opportunity appears

Now imagine the clock reaches 10:05.

Another five-minute candle has finished.

Robo checks the measurements used by its trading strategy.

Some help describe the direction of prices.

Others help describe the strength of the movement.

These measurements are called **indicators**.

They're rather like instruments on a car dashboard: useful information, but not a guarantee that the journey will go well.

For our imaginary example, suppose all the required conditions are satisfied.

Robo announces:

*"I've found something interesting!"*

Excellent.

But has Robo bought anything?

No.

What has happened is that the strategy has **qualified a possible trading opportunity**.

Think of it as a security guard recognising someone who has the correct invitation.

The visitor may be eligible to enter.

But the gate isn't open yet.

In SignalForge's accepted initial NSE strategy, a qualifying opportunity can move into a waiting state called **ARMED**.

That's a technical word for something quite simple.

It means:

*"The conditions were satisfied. Now watch for the specific event that would permit the next action."*

Robo is ready.

But it hasn't acted.

## An opportunity doesn't last forever

Here's something important.

Robo cannot keep an old trading opportunity in its pocket indefinitely.

Imagine buying a cinema ticket for Friday evening.

You can't turn up three weeks later and expect it to admit you to the same screening.

Trading opportunities can also have a limited lifetime.

In SignalForge's accepted initial NSE strategy, the opportunity is valid during the immediately following five-minute candle.

During that period, the system watches for the strategy's entry-trigger conditions and applies its rules for invalidation and expiry.

If the appropriate trigger occurs while the opportunity remains valid, the system can progress towards an entry.

If the opportunity expires or is invalidated, the system cannot simply pretend it is still active.

That is one reason trading robots need more than a single instruction saying "BUY".

They need to know:

- When an opportunity becomes valid.
- What must happen before an entry can proceed.
- When the opportunity is no longer valid.

The exact price calculations belong in Chapter 3.

For now, let's imagine Robo's entry condition is satisfied while its opportunity remains valid.

*"The entry condition has been triggered!"* Robo announces.

But there's another catch.

**A triggered opportunity is still not proof that a real share has been purchased.**

## Why Robo can't simply shout "BUY!"

Let's leave the stock market for a moment and visit a bakery.

You decide you'd like two chocolate cakes.

That's your intention.

You walk into the bakery and ask for them.

That's your request.

The baker checks what's available.

Perhaps both cakes are ready.

Perhaps only one remains.

Perhaps the bakery has sold out.

Asking for something and receiving it are two different events.

Trading works in a similar way.

A trading system may identify a possible opportunity and determine that an entry condition has triggered.

In a system connected and authorised for real trading, that decision may lead to an **order**.

An order is a request to buy or sell a specified quantity under particular conditions.

A **broker** provides access to market trading, while an **exchange** operates a marketplace in which eligible buying and selling interests can meet.

But sending an order doesn't guarantee that a trade has happened.

The order could be rejected.

It could remain unfilled.

It could be completed only partly.

Or the requested quantity could be fully purchased.

When a trade is actually executed, traders call that a **fill**.

So here's the important journey:

**Signal:** The strategy has identified a qualified opportunity.

**Trigger:** The additional entry condition has occurred while the opportunity is valid.

**Order:** A real trading system may submit a request through an authorised execution route.

**Fill:** Some or all of that requested trade has actually been executed.

In practice, trading venues have detailed order types, prices and execution rules.

Our bakery analogy is only a starting point.

But it teaches us something essential.

An order acknowledgement isn't the same as a completed fill.

And an internal trading signal isn't automatically an instruction sent to a broker.

## The paper cake and the real cake

Now we arrive at one of the most important distinctions in this book.

Imagine two versions of Robo.

The first is working in a simulator.

The second is connected to a properly authorised real trading system.

Both might recognise the same trading opportunity.

Both might detect the same entry trigger.

But what happens next is very different.

### Robo in paper mode

Paper trading means practising trading decisions without placing real-money orders.

A paper-trading system can record a **simulated fill** according to its execution model.

It might use observed market prices and predefined assumptions to decide what price to assign to the imaginary purchase.

For example, imagine a simulated purchase recorded at ₹1,002.

That number may be useful for evaluating the strategy.

But it does not prove that a real broker bought shares at ₹1,002.

No real exchange purchase has occurred merely because the paper system recorded one.

### Robo in real trading

In a real trading system, an authorised broker order would need to be accepted and executed.

The actual result could differ from the paper simulation.

There might not be enough shares available at the expected price.

The market might move while the order is being processed.

The order might be partially filled or rejected.

And the system needs trustworthy confirmation of what actually happened.

**A simulated fill is a modelled trading event. A real fill is an actual execution event.**

They must never be confused.

SignalForge's documented live PAPER operator works in paper mode and does not provide an option to place real broker orders.

That distinction isn't a limitation to hide.

It is an important safety boundary.

## What happens after a purchase?

Let's imagine an alternative outcome in Robo's fictional trading day.

In this version, Robo's execution mode has recorded a fill at ₹1,002.

If it is running in paper mode, that is a simulated fill.

If we're discussing an authorised real trading system, the corresponding real fill would require actual execution evidence.

Either way, the trading strategy needs to know what happens next.

The price might rise.

It might fall.

It might move sharply in both directions.

A responsible trading strategy therefore needs exit rules.

One familiar concept is a **stop-loss**.

A stop-loss is intended to limit the loss when a trade goes against us.

But how does a stop-loss work?

There isn't just one possible arrangement.

In some systems, software watches market information and decides when an exit condition has been reached.

In others, a suitable protective order may be submitted to a broker or exchange.

Neither arrangement guarantees an exit at the intended price.

Suppose the intended stop level is ₹990.

If the market suddenly moves below it, the eventual exit might occur at a worse price.

And if there is no real broker order, reaching a stop condition does not magically sell actual shares.

SignalForge's accepted initial strategy defines a specific stop using the low of the qualifying signal candle.

It also defines how the target is calculated after a fill.

We don't need those formulas just yet.

What matters is that **the actual or simulated fill, the stop, the target and the eventual exit must be represented honestly according to the operating mode**.

A trading system should never confuse an intended exit with a completed sale.

## What if Robo loses the internet?

Back to our main story.

Robo is watching the market.

Everything seems normal.

Suddenly...

The connection disappears.

No new prices arrive.

What should Robo do?

Carry on pretending everything is fine?

Guess what the market probably did?

Invent the missing prices?

Absolutely not.

Imagine a pilot flying through thick cloud when an important instrument stops working.

The pilot doesn't solve the problem by making up a comforting reading.

A trading robot needs the same discipline.

It must recognise when information is missing, outdated or unreliable.

If the computer restarts, it must also establish what was happening before the interruption.

Was an opportunity waiting to trigger?

Had the permitted trading period already expired?

Was a position open?

Had an exit been recorded?

SignalForge's engineering approach puts considerable importance on reliable records, continuity checks and safe recovery.

Its documented live PAPER operating process includes safeguards that can refuse to proceed when required information or prior state cannot be trusted.

That might sound inconvenient.

But there is a good reason.

**A robot that stops when it doesn't know what happened is safer than one that confidently invents an answer.**

We'll return to failures and recovery in Chapter 11.

## Why practise without real money?

So why go to the trouble of creating paper trading at all?

Think about learning to fly an aeroplane.

Nobody sensible would hand a beginner the controls of a passenger aircraft after one successful computer simulation.

A simulator is valuable because it lets us practise and investigate problems without immediately risking people's lives.

Paper trading has a similar purpose.

It lets researchers observe trading strategies and exercise software under controlled assumptions without sending real-money orders.

But paper trading is not proof of profitability.

Its simulated fills may differ from real executions.

Market conditions can change.

Connections can fail.

And even a system that behaves exactly as programmed may be following a strategy with no genuine advantage.

So paper trading helps answer important questions.

Does the software follow the intended rules?

Does it respond sensibly to market events?

Can it record and recover its state?

Do the simulated results justify further investigation?

It does not automatically answer the much bigger question:

*"Should we trust this system with real money?"*

That requires additional evidence, safeguards and explicit authorisation.

## So what can SignalForge actually do?

Our imaginary Robo helps us understand how trading automation works.

But we should separate the fictional story from SignalForge's documented capabilities.

SignalForge has software for replaying market information, evaluating strategies, managing signal and trading lifecycles, and recording decisions.

It also has a documented live PAPER operator for its accepted initial NSE strategy.

That operator works under specific readiness and safety conditions.

It does not offer broker-order placement.

Having the software implemented is important.

But it doesn't prove that every operational validation requirement has been satisfied.

And it doesn't prove that the strategy makes money.

Those are different questions.

The project's longer-term ambition includes carefully controlled real trading, but only where the required evidence and permissions justify it.

Until then, a paper fill remains a paper fill.

## Does this mean Robo will make money?

Eventually, someone is bound to ask:

*"All right, but will it make a profit?"*

We can't answer that simply because Robo exists.

Computers can follow instructions consistently.

They can monitor markets without becoming tired or emotional.

They can record decisions and process information quickly.

But none of those abilities guarantees a profitable trading strategy.

A perfectly functioning robot could lose money with remarkable consistency if its instructions were poor.

The real challenge isn't just making the robot trade.

It's finding out whether the rules deserve our confidence — and whether the software can operate them safely.

## Remember this

A trading robot can watch prices, identify opportunities, wait for entry conditions and manage what happens next.

But the stages matter.

**A qualified opportunity is not yet a triggered entry.**

**A triggered entry is not necessarily a broker order.**

**An order is not necessarily a fill.**

**A simulated fill is not a real trade.**

And none of these guarantees a profit.

A good trading robot isn't one that trades constantly.

It's one that follows its rules, knows what actually happened, and refuses to guess when the evidence is missing.

Now that we understand what a trading robot can do, there's another fascinating question.

How does it decide that something is worth trading in the first place?

**That's where Chapter 3 begins: How Does a Trading Strategy Think?**
