# PRODUCT.md — 良律 LiangLü (fd-lex)

> Inferred from the lex-platform-v1 proposal and specs (openspec/changes/lex-platform-v1) by the
> frontend apply agent, because no interview was held. Every claim below traces to a spec; nothing
> here is invented. Update it when product decisions land outside specs.

## What this is

良律（LiangLü）is FindData's (寻数) legal-technology platform, a member of the 识律 (Lex) family:
the vertical platform that turns four layers of real assets — legal data (statute library,
judgments, guiding cases, corpora), applications (LawBench contract intelligence), in-house
models (judge_c / drafter_a), and the 壹座 execution base — into one commercially available
platform. Law is not only for practitioners: LiangLü also aims to help everyone understand why
the law is as it is, how it used to be, whether it is reasonable, and what harms it carries
(lex-family-rebrand, 2026-10-30).

Line-level invariant: **every customer-visible lex component ships inside the versioned
distribution package and can run in the customer's machine room.** Cloud and on-premises are two
host forms of the same deliverable, produced by the same builder.

## Single domain, four entries (`lex.finddatatech.cloud`)

- `/` — official site + capability catalog (bilingual zh/en): marketing, pricing, deployment docs
- `/console` — customer self-service (register, credentials, usage, billing)
- `/mcp` — MCP protocol endpoint (reverse proxy to the registry lex entry)
- `/deploy` — private deployment delivery information

Any entry failing must not take down the others.

## Truth constraints the site must keep

- The capability catalog annotates each capability's real availability per host. v1 does NOT
  include cloud GPU inference or a model API (planned v1.x): the models are on-premises only, and
  the catalog says so plainly.
- Pricing is never pre-filled: plan numbers are backend-configurable and fixed at first contract.
  The public site shows billing dimensions and "quote on request".
- No invented contact endpoints, hardware specs, prices, or customers. Placeholders say they are
  placeholders.

## Audience

Enterprise legal departments, legal-tech procurement, and integrators evaluating private
deployment. Register: restrained, credible, legal-industry B2B. Chinese primary, English equal.
