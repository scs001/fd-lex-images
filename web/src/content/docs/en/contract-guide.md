---
title: Contract Intelligence User Guide
description: The LawBench contract intelligence user guide for legal professionals — assembling contract drafts from a clause library, with triple AI review, measurable quality and statute grounding.
---

> This guide describes the intended actions and workflows of the platform's contract-intelligence capabilities. It is deliberately not tied to specific interface controls; the interface as delivered prevails.
> Numbers tagged in the [N1] style are taken from the Lex numbers ledger; the tag is the row ID of that figure in the ledger.

## 1. What this guide covers

A guide for legal professionals: those who draft and review contracts day to day, in corporate legal departments and law firms.

Contract intelligence on the Lex platform (LawBench) rests on one core idea: **a contract is not invented by a model — it is assembled from a clause library.** Drafting is not left to one-shot free generation. The platform selects clauses from a library rooted in the Civil Code and the practical contract taxonomy, and assembles them into a draft according to the type, stance and scenario you choose. Every draft therefore has traceable grounding — where its clauses come from and which statutes they correspond to.

Around this idea the platform offers six capabilities, each covered in this guide:

- **Contract generation** — pick the type, stance and scenario; assemble a complete draft (see "Generate a contract draft");
- **Triple AI review** — legal, commercial and completeness dimensions reviewed in parallel (see "Triple AI review");
- **Quality scoring and version comparison** — criterion-by-criterion scoring against a rubric; improvement is measurable (see "Quality scoring and version comparison");
- **Statute grounding** — finished contracts can carry article-level citations (see "Statute grounding");
- **Built-in legal models** — separate purpose-built models for drafting and review (see "Built-in legal models");
- **Agent access** — the entire capability is exposed as MCP tools, callable by AI agents inside a conversation (see "Agent access").

## 2. Before you begin

One prerequisite:

- **Access to the Lex platform** — accounts and credentials are provided once the platform is provisioned for you; if it is not yet, please contact us first.

With access in place, two assets back the drafting work:

- **Contract template library** — 5,000+ model templates [N12], from the official contract-template library of the State Administration for Market Regulation (SAMR), organized by the 19 typical named contracts of the Civil Code and the practical contract taxonomy, up to six levels deep, updated daily;
- **Statute library** — 32,296 laws and regulations of the People's Republic of China [N1]; see "Statute grounding".

## 3. Generate a contract draft

Drafting comes down to three intended actions: choose the contract type, choose your stance and scenario tags, then assemble and export the draft.

### Choose the contract type

Pick the type in the contract taxonomy that best matches the transaction at hand. The taxonomy is rooted in the typical named contracts of the Civil Code and practical contract classification (see "Before you begin"); common transaction types each have their place. If you are unsure, start with the closest type by the substance of the transaction.

### Choose your stance and scenario tags

The same contract type reads differently depending on which side you are on. Select the stance you represent and apply scenario tags for this transaction; the platform then selects, from the clause library, the clause combination that fits the situation.

### Assemble and export the draft

The platform assembles a draft with a complete clause set from the clause library and renders it as Markdown, Word or PDF: Markdown flows into review and version management, Word continues under your existing drafting conventions, PDF suits finalization and distribution.

## 4. Triple AI review

Once a draft is assembled, you can send it for review. Review runs along three dimensions in parallel:

- **Legal** — how clauses correspond to, and comply with, the statutes behind them;
- **Commercial** — findings on the commercial terms themselves;
- **Completeness** — whether the clause set is complete, with nothing missing.

The three dimensions run in parallel and report independently, none blocking another. Findings can be precise to the individual clause — which clause, which dimension — instead of staying at the level of generalities. For legal teams this means review conclusions translate directly into clause-level edits.

## 5. Quality scoring and version comparison

Beyond review findings, quality is measured. The platform turns "is this draft good" into checkable scores and records:

- **Criterion-by-criterion scoring** — every draft is scored clause by clause against a rubric: an explicit standard first, a score second;
- **Version comparison** — different versions of the same contract can be compared side by side, with changes plainly visible;
- **Regression testing** — rubrics are manageable and evaluations run in batches; after a change, re-running the evaluation set confirms quality has not regressed.

For a legal team the practical value is this: improvement in drafting quality is measured, not felt.

## 6. Statute grounding

A draft's grounding goes beyond the clause library to the statute library behind it.

- **Statute retrieval** — the platform retrieves across 32,296 laws and regulations of the People's Republic of China [N1]; the library holds 364,916 article-level statute slices [N2], backing article-level retrieval and citation resolution;
- **Article-level citations** — generated contracts can embed article-level citations, tying key wording in the contract to the exact article of the exact statute — traceable and checkable.

For legal professionals this means the key clauses in a draft are not isolated text: the statutes behind them can be opened and checked directly.

## 7. Built-in legal models

Underneath these capabilities sit two purpose-built legal models built into the platform: one for contract drafting, one for contract review. Both are fine-tuned on legal-domain data on top of a general-purpose LLM, and both are provided as built-in platform capabilities.

Measured head-to-head on our own evaluation set, the legal domain model against the general-purpose baseline:

| Metric | General-purpose baseline | Legal domain model |
|---|---|---|
| Review accuracy | 10.9% | 84.4% [N8] |
| Structured-output validity | 38.5% | 100% [N9] |
| Per-item latency | 27.3 s | 10.2 s [N10] |

Three implications for legal users:

- **Conclusions are consumable by software** — structured-output validity of 100% [N9]: findings follow the agreed structure and flow straight into scoring, version comparison and regression testing, rather than arriving as prose a person must reorganize;
- **The baseline's failure modes are gone** — the general-purpose baseline's typical failures were emitting generic reasoning, never producing valid structure, and exhausting the output limit; after fine-tuning these no longer occur;
- **Faster** — per-item latency down from 27.3 s to 10.2 s [N10], and the waiting cost of batch review falls with it.

## 8. Agent access

Beyond direct human operation, the platform's entire capability is also exposed as **52 MCP tools** [N14], covering contract generation, clause retrieval, multi-dimensional review, rubric management and batch evaluation.

MCP (Model Context Protocol) is the standard protocol for AI agents to call external capabilities. Once an MCP-capable agent client is connected, an AI agent can draft and review contracts inside a conversation: assemble a draft, follow up on review findings, or wire batch evaluation into an automated workflow. For connection details and credentials, refer to the platform's MCP integration documentation.

## 9. Frequently asked questions

### The interface does not match this guide — which one wins?

This guide describes intended actions and workflows (such as "choose the contract type", "send for review"), not specific interface controls. The interface as delivered prevails; where wording differs from the current version, what the platform actually shows wins.

### Do the template library and statutes get updated?

Yes. The contract template library is updated daily; statutes update as daily increments. The definitions and as-of dates behind every figure in this guide are in the Lex numbers ledger; figures advance as data updates, and the latest ledger prevails.

### What is the status of the court-judgment corpus?

Contract drafting and review rely mainly on the statute library and the contract template library. Within the Lex legal data estate, the court-judgment corpus is currently primarily a historical full corpus: incremental collection is affected by the source sites' access policies, and new material is being backfilled. We state data status plainly and do not overpromise.

### Can review findings replace a lawyer's judgment?

No. The platform provides traceable review findings and statutory grounding to improve the efficiency and consistency of drafting and review; the final legal judgment remains with a licensed lawyer.

### Where do the numbers in this guide come from?

All from the Lex numbers ledger, tagged in the text with [N1]-style row IDs; the ledger is the single source of every figure in Lex-facing material. This guide contains no pricing and no usage statistics; for commercial matters, please contact us directly.
