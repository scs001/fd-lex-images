---
name: 识律 Lex (fd-lex web)
description: 法律 B2B 官网与能力目录——法典蓝档案世界，宋体显示、台账行式、宿主标注如实
colors:
  statute-navy: "#12305b"
  navy-deep: "#0c2140"
  cool-paper: "#f6f7f9"
  cool-mist: "#ebeff4"
  ink-slate: "#1b2a42"
  ink-muted: "#4e5f7b"
  hairline: "#d9dfe8"
  hairline-strong: "#b6c1d1"
  seal-vermilion: "#a6402f"
  seal-wash: "#f4e5e1"
typography:
  display:
    fontFamily: "Noto Serif SC, Source Han Serif SC, Songti SC, STSong, SimSun, Georgia, serif"
    fontSize: "clamp(2rem, 4vw, 3rem)"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Noto Serif SC, Source Han Serif SC, Songti SC, serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Segoe UI, Roboto, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.8
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, PingFang SC, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    letterSpacing: "0.14em"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
  2xl: "16px"
  pill: "9999px"
spacing:
  section-y: "80px (desktop 96px)"
  container-x: "24px"
  container-max: "72rem"
components:
  button-primary:
    backgroundColor: "{colors.statute-navy}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  button-primary-on-dark:
    backgroundColor: "#ffffff"
    textColor: "{colors.statute-navy}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink-slate}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  badge-host:
    backgroundColor: "transparent"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  badge-host-private:
    backgroundColor: "{colors.seal-wash}"
    textColor: "{colors.seal-vermilion}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
---

# Design System: 识律 Lex

## Overview

**Creative North Star: "法典与台账" (The Statute Book and Its Register)** — the site performs its
own deliverable: a legal capability catalog typeset with the discipline of a statute register, where
a buyer audits capabilities the way they would audit a legal document.

The world is a cool, quiet archive: a statute-navy field opens and closes the page (hero, footer),
between them sections sit on cool paper. Depth comes from rules, not shadows — 1px hairlines and
2px strong rules organize every list into a ledger. There is exactly one ornament with a license:
the seal vermilion, which appears in two meanings only — the brand seal, and the truthful
"on-prem only" marking whose visibility is the point. Display voice is a Songti-lineage serif
(self-hosted Noto Serif SC); body is the system CJK sans. Motion is a single restrained staged
entrance in the hero, skipped entirely under reduced motion.

**Key Characteristics:**
- Statute-navy owns whole regions; body sections stay on cool paper — never scatter navy accents.
- Ledger rows with ruled borders instead of card grids.
- Seal vermilion: brand seal + honest limitation marks, nothing else.
- One authored motion moment (hero reveal); otherwise static and calm.

## Colors

A restrained cool palette: two navy fields, two paper grounds, ink text, hairline rules, and a
single vermilion accent with a guarded meaning.

### Primary
- **Statute Navy** (#12305b): owns the hero band and (deeper, #0c2140) the footer. White text on
  it carries the brand's authority; never use it as scattered text accent on paper.

### Tertiary
- **Seal Vermilion** (#a6402f): the brand seal mark, and host-availability badges/notes marking
  "on-prem only" capability. Its appearance signals either identity or an honest limitation.
- **Seal Wash** (#f4e5e1): pill background behind vermilion badge text on light ground.

### Neutral
- **Cool Paper** (#f6f7f9): default page ground. Deliberately cool, never warm cream.
- **Cool Mist** (#ebeff4): alternating section ground (pricing) for pacing.
- **Ink Slate** (#1b2a42): all body text on paper.
- **Ink Muted** (#4e5f7b): secondary text, ledger bullets, inactive controls. Tinted from the
  ink hue — never gray.
- **Hairline** (#d9dfe8) / **Hairline Strong** (#b6c1d1): 1px row rules / badge borders and the
  lang-toggle border.

### Named Rules
**The Two Meanings Rule.** Vermilion appears only as the seal or as an on-prem-only annotation. If
vermilion shows up for decoration, the annotation has lost its voice.
**The Field Rule.** Navy is a field color (hero, footer, primary button fill), never a text
accent inside body sections.

## Typography

**Display Font:** Noto Serif SC (self-hosted via @fontsource; fallbacks Songti SC, SimSun, Georgia)
**Body Font:** system CJK sans stack (PingFang SC, Microsoft YaHei, …)

**Character:** the Songti display voice carries legal/official-document gravity; the sans body
keeps UI quiet. Latin register labels are set small, uppercase, tracked (+0.14em).

### Hierarchy
- **Display** (600, text-3xl–5xl, leading tight, -0.01em): page and section headings only.
- **Headline** (600, 1.25rem): ledger row capability names.
- **Body** (400, 0.9375rem, 1.8 line-height, ~36 CJK chars measure): paragraphs and list points.
- **Small** (0.875rem / 0.8125rem): ledger points, notes.
- **Label** (500, 0.75rem, tracked, uppercase Latin only): register column headers, Latin
  capability subtitles, footer section labels.

## Layout

Single page, five blocks (hero / capabilities / pricing / docs / footer) with sticky top
navigation and anchor scrolling (`scroll-mt-20` under the 64px header). One container:
max-width 72rem, 24px side padding. Sections breathe at 80px vertical (96px desktop). The
capability ledger is a 12-column register: name (4) / points (5) / host (3), collapsing to a
single column under `lg`; the docs block is a two-column ruled definition grid collapsing under
`md`.

## Elevation & Depth

Flat by doctrine: zero shadows. Structure and hierarchy come from rules — 2px ink rules bound the
register top and bottom, 1px hairlines divide rows; on navy, translucent white (4–6% fills,
15% borders) layers the stack diagram. Hover states change color, never elevation.

## Shapes

Small radii only: 6px on buttons, 8px on diagram nodes, 12–16px on the two framed panels (stack
diagram), full pills reserved for host badges and the language toggle. Lists end in rules, not
rounded cards.

## Components

### Buttons
- **Shape:** 6px radius, 10px/20px padding, 0.875rem medium text.
- **Primary on paper:** statute-navy fill, white text; hover deepens to #0c2140.
- **Primary on navy:** white fill, navy text; hover shifts to cool mist.
- **Outline:** 1px border (hairline-strong on paper, 30% white on navy); hover strengthens border.
- **Focus:** 2px statute-navy outline with 2px offset, site-wide via `:focus-visible`.

### Host badge (signature component)
Pill with 1px border, 12px medium text, and a two-dot glyph: two filled dots = dual-host (muted
ink on paper, 80% white on navy); dashed hollow dot + filled dot = on-prem only, vermilion text on
seal wash (light) or vermilion-on-navy tint (dark). The glyph is drawn SVG, never emoji.

### Ledger row
12-column ruled row: serif capability name + tracked Latin subtitle + one-line description;
square-bulleted point list; host badge plus (for on-prem-only rows) a vermilion note line.

### Navigation
Sticky paper header, 64px, hairline bottom border: seal mark + wordmark left; anchors, console
link, language pill right. Anchor links hide under `md`; console stays reachable via hero CTA.

## Do's and Don'ts

### Do:
- **Do** keep body line-length near 36 CJK characters (`max-w-[36rem]`) and line-height 1.8.
- **Do** bound registers with a 2px ink rule and divide rows with 1px hairline.
- **Do** restate both languages with identical key structure — the site is bilingual by contract.
- **Do** mark every capability's host availability honestly; limitations in vermilion.

### Don't:
- **Don't** use shadows, gradients, or glass for depth; use rules and tonal fields.
- **Don't** introduce icon fonts or emoji; draw the few glyphs as SVG.
- **Don't** publish price numbers, hardware specs, or contact endpoints — quote-on-request chips
  and labeled placeholders only.
- **Don't** animate beyond the hero reveal; the register stays still.
