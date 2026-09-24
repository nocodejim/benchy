# Choosing AI coding models: how we test and what the results mean

We can use AI coding models from four vendors: Microsoft (MAI), OpenAI, Google (Gemini) and
Anthropic (Claude). Each one also has a "thinking level" setting: how long the model reasons
before it acts. More thinking usually means better answers, but it also costs more and takes
longer. This page explains how we compare those options on our own kind of work, and how to read
the results.

## Why we test instead of trusting vendor claims

Vendor benchmarks are like a car's official fuel economy: measured honestly, but on a test
track, not on your commute. They mostly use public puzzles and open-source projects. Our work is
different: build pipelines, container setups, deployments, security rules, and our own code. The
only way to know which model does *our* work well is to give it our work and check the result.

## What one "run" is

A run is one model, at one thinking level, doing one realistic work ticket from start to finish,
with nobody helping it. For example: *"Our release pipeline broke. Fix it."*

Think of it as a practical driving test with a hidden checklist:

1. The model gets a copy of a real project and the ticket, in a sealed practice room (a
   *container*: an isolated, disposable computer environment).
2. It works alone until it says it's done, or until time runs out.
3. We then grade its work with checks it never saw. Did it actually fix the problem? Did it
   break anything that used to work? Did it stay within what the ticket asked? Did it leave a
   password lying in a file?

A run counts as **resolved** only if every must-have check passes. We also record how long it
took, how much it cost, and keep a full copy of what it changed so a person can review it.

## Why we repeat the same test

AI models are not perfectly consistent. Ask the same model the same thing twice and you can get
two different answers, one right and one wrong. So we run every ticket at least three times for
each model. A model that solves a ticket every time is worth more to a team than one that solves
it sometimes, even if their averages look similar.

## The three questions the report answers

**1. Does it work?** The *resolve rate* is the share of runs that were fully correct. This is
the headline number.

**2. What does it cost?** We report *cost per resolved task*: everything spent, including
failed attempts, divided by the number of successes. A cheap model that fails half the time
isn't cheap, because you pay for the failures too (and a person has to redo the work).

**3. How reliable is it?** *pass^k* ("pass every time") is the share of tickets the model
solved on **every** repeat. It answers: can a team count on this daily?

The report also shows how long each run took, and how much text the model read and wrote
(*tokens*, the unit AI usage is billed in).

## Reading the headline chart and scorecard: a worked example

> **The numbers below are made up for illustration only. They are not real results.**

Imagine three options, each run on 6 tickets × 3 repeats = 18 runs:

| Option (illustrative) | Resolve rate | pass^k | Cost per resolved task | Typical time |
|---|---|---|---|---|
| Model A · high thinking | 83% (15 of 18) | 67% | $1.20 | 6 min |
| Model A · low thinking | 61% (11 of 18) | 33% | $0.95 | 3 min |
| Model B · medium thinking | 78% (14 of 18) | 67% | $0.55 | 4 min |

How to read it:

- **Model A at high thinking** solves the most, but costs the most per success.
- **Model A at low thinking** is cheaper *per run*, but because it fails more often its cost per
  success is not much lower, and it is least reliable (pass^k 33%). Poor value.
- **Model B** is nearly as good as A-high, just as reliable, and costs less than half as much
  per success. For most teams this would be the recommended default.
- The difference between 83% and 78% is **one run out of 18**. With this few runs, that is
  within normal variation. The report shows ranges (lowest to highest) next to medians for
  exactly this reason; when ranges overlap, treat the options as tied.

In the report, the headline chart shows these as bars (longer is better for resolve rate,
shorter is better for cost and time). A dash "—" means "not reported", never zero.

## What the results can and cannot tell us

**They can tell us:**

- Which models reliably finish realistic tickets of a given kind, on our tools and standards.
- The real cost of a successful result, including failures.
- Whether paying for more thinking actually buys better results for a given kind of work.
- *How* models fail: timing out, breaking existing features, touching unrelated files, or
  leaking a password.

**They cannot tell us:**

- How the model feels to use in day-to-day conversation. We test it working alone.
- Anything about stacks we haven't written tickets for. The starter set covers a few DevOps
  topics and one small app; it is a starting point, not a verdict.
- Permanent truths. Models, prices and tools change monthly. Results carry a date and go stale.
- Whether the code is *good* beyond our checks. A person should still review a sample.

## How recommendations per team and stack will be made

1. **Start with the shared starter set** to produce a first, company-wide default.
2. **Each team adds a few tickets from its own backlog** (for example Java, .NET, Terraform or
   front-end work). Each new ticket is proven fair before use: it must fail when nothing is
   done, and pass with a known-good answer.
3. **Run all four vendors at two or more thinking levels**, at least three repeats, on the same
   tools, same limits and same tickets, so only the model changes.
4. **Recommend per stack** from the *per-task* results: the option with the best mix of resolve
   rate and reliability, then the lowest cost per resolved task among options that are
   effectively tied.
5. **Re-run quarterly** or when a major new model arrives, and compare only like with like.

The detailed engineering guide is in [user-manual.md](user-manual.md).
