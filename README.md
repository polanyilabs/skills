<p align="center">
  <img src="assets/banner.svg" width="100%" alt="Polanyi Labs: AI shoppers that turn your store into training data for recommendation systems">
</p>

<p align="center">
  <a href="https://agentskills.io/specification"><img src="https://img.shields.io/badge/agent%20skills-spec-C44B1E?labelColor=8B1A1A&style=flat-square" alt="Agent Skills"></a>
  <img src="https://img.shields.io/badge/npx%20skills%20add-polanyilabs%2Fskills-C44B1E?labelColor=8B1A1A&style=flat-square" alt="npx skills add polanyilabs/skills">
  <img src="https://img.shields.io/badge/license-Apache--2.0-C44B1E?labelColor=8B1A1A&style=flat-square" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/status-v0%20preview-E07030?labelColor=8B1A1A&style=flat-square" alt="Status: v0 preview">
  <a href="https://polanyilabs.com"><img src="https://img.shields.io/badge/polanyilabs.com-F9F3EE?labelColor=8B1A1A&style=flat-square" alt="polanyilabs.com"></a>
</p>

# Polanyi Labs Skills

Give your recommender behavioural data before real users arrive, from your AI coding agent: Claude Code, Codex,
Cursor, GitHub Copilot and other agents that support skills.

This repository provides agent skills for [Polanyi](https://polanyilabs.com). Polanyi sends AI shoppers, each built
from a synthetic persona, to browse your store and records what they search, view, compare, shortlist and choose as
recommender events. The skills tell your agent how to aim those shoppers at the products your data is missing and how
to merge the results into your own interaction logs.

> **Status: v0, early preview.** Expect changes to the workflow and file formats.

## Why

<p align="center">
  <img src="assets/cold_start.svg" width="100%" alt="A grid of shoppers by products. Three real shoppers have only a few interactions; synthetic shoppers are added row by row with many interactions.">
</p>

Recommenders learn from history: who viewed, compared and chose what. New stores, new products and new categories
have almost none, so recommendations fall back to bestsellers. Polanyi adds sessions from synthetic shoppers aimed at
the products your data is missing, flagged so you can always tell them apart from real customers.

## Installation

```bash
npx skills add polanyilabs/skills
```

[`skills`](https://github.com/vercel-labs/skills) detects the coding agents on your machine and copies each skill into
the right place (for example `~/.claude/skills/` for Claude Code).

**Manual install:** copy a folder from [`skills/`](./skills/) into your agent's skills directory.

### Requirements

| | |
|---|---|
| Python | 3.11+, with `pandas` and `pyarrow` |
| Polanyi | `pip install polanyi` |
| API key | `POLANYI_API_KEY` from [polanyilabs.com](https://polanyilabs.com), set in your environment or `.env`. Never paste keys into the agent chat. |
| A store you run | Shoppers browse your live site. Only point them at sites you own or operate. |

## Available Skills

- **polanyi-augment**: finds products with little interaction data, runs persona shoppers on your store aimed at them,
  and merges the events onto your own item IDs with a coverage report. Asks before every run and shows the estimated
  time and cost first.

Try it by asking your agent:

```text
Augment my dataset. The catalog is data/catalog.csv and the interactions are data/events.parquet.
```

## Structure

Each skill follows the [Agent Skills specification](https://agentskills.io/specification):

```
skill-name/
├── SKILL.md       # Frontmatter + instructions the agent reads
├── scripts/       # Deterministic helpers the agent runs instead of writing code
└── references/    # Extra documentation, loaded only when needed
```

## Data and responsible use

- Every synthetic row is marked `is_synthetic=True` and uses synthetic user IDs, so it can be filtered out or
  down-weighted and never joins to real customers.
- Shoppers stop before sign-in, personal details and payment. They do not create accounts or buy anything.
- Synthetic sessions add coverage; they do not prove your recommender improved. Measure that by training with and
  without the synthetic rows and testing on held-out real data.

## Development

```bash
pip install pandas pyarrow pytest
pytest tests/
```

- `tests/` covers the deterministic scripts.
- `evals/evals.json` lists the behaviours each skill must show (for example: asks before running, never invents item
  IDs). Run them with Haiku, Sonnet and Opus before a release.

### Adding a skill

Create `skills/<name>/SKILL.md` with `name` (lowercase, hyphens, matching the folder) and a `description` that says
what the skill does and when to use it. Keep `SKILL.md` under 500 lines and move detail into `references/`. Add at least
three evals to `evals/evals.json` before opening a pull request.

## Security

Please do not report vulnerabilities in public issues. Open an issue titled "Security contact" without any details,
and a maintainer will reply with a private channel.

## Contributing

Issues and pull requests are welcome. Every change is reviewed by a maintainer before merging.

## License

[Apache 2.0](./LICENSE)
