# Source bundles

One file per topical bundle. Every entry carries its own lifecycle dates so a
stale list is visible rather than silent. Format and curation policy:
[`../../docs/SOURCES.md`](../../docs/SOURCES.md).

`local.yaml` is gitignored — put your private sources there and they will survive
`git pull`.

Run `mcpnews sources check` to see what is failing or past its `expires` date.
