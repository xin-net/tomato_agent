# Issue tracker: GitHub

Issues and PRDs for this repo live in GitHub Issues for `xin-net/tomato_agent`. Use the `gh` CLI for issue tracker operations.

## Repository

```text
xin-net/tomato_agent
```

## Conventions

- Create an issue: `gh issue create --repo xin-net/tomato_agent --title "..." --body "..."`
- Read an issue: `gh issue view <number> --repo xin-net/tomato_agent --comments`
- List issues: `gh issue list --repo xin-net/tomato_agent --state open --json number,title,body,labels,comments`
- Comment on an issue: `gh issue comment <number> --repo xin-net/tomato_agent --body "..."`
- Apply or remove labels: `gh issue edit <number> --repo xin-net/tomato_agent --add-label "..."` / `--remove-label "..."`
- Close an issue: `gh issue close <number> --repo xin-net/tomato_agent --comment "..."`

Use heredocs or temporary files for multi-line issue bodies when needed.

## Pull requests as a triage surface

PRs as a request surface: no.

Do not include external pull requests in the triage queue for this repo. Triage workflows should operate on GitHub Issues only.

## When a skill says "publish to the issue tracker"

Create a GitHub issue in `xin-net/tomato_agent`.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo xin-net/tomato_agent --comments`.
