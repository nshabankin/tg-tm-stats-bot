# Changelog

All notable changes to this project will be documented in this file.

## v1.0.2 - 2026-09-01

### Updated

- refreshed complete `2026/27` snapshots for all nine supported European
  competitions: six domestic leagues plus the Champions League, Europa League,
  and Conference League
- regenerated 2026 standings, squads, player stats, matches, UEFA brackets,
  refresh-state summaries, and PDF exports
- updated season examples and operating notes from `2025/26` to `2026/27`

### Improved

- global refreshes now resolve competition-specific default seasons, keeping
  World Cup 2026 on Transfermarkt season key `2025`
- UEFA table ranks now follow displayed row order when every club is tied before
  league-phase matches begin
- the cookie diagnostic now uses the correct source page for domestic, UEFA,
  and tournament competitions

### Fixed

- repaired the cookie diagnostic after refresh helpers moved modules
- detect Transfermarkt HTTP 202 JavaScript/WAF challenges instead of accepting
  them as empty football pages
- abort player-stat refreshes immediately on site-wide verification challenges,
  preventing partial blank snapshots from being written
- reject empty standings before any season snapshot can replace valid data

## v1.0.1 - 2026-04-21

This release turns the revived bot into a much more complete football snapshot
browser, with a stronger Telegram Mini App experience and broader competition
coverage.

### Added

- UEFA competition support for:
  - Champions League
  - Europa League
  - Conference League
- Mini App browsing for:
  - dense league tables
  - collapsible team squads
  - player stat cards
  - domestic matchday results
  - UEFA league-phase results
  - UEFA knockout playoff brackets
- league and competition logo support in the picker and club views
- local match JSON snapshots alongside existing table and player snapshots

### Improved

- default Mini App flow is now browse-first instead of file-download-first
- domestic and UEFA match views now open on the latest stage with played matches
- match rows normalize club names so logos and full names stay aligned
- bracket rendering is cleaner and more readable for UEFA knockouts
- recent-form league table display is now part of the revived snapshot flow
- refresh progress output is more useful while running long snapshot refreshes

### Fixed

- several Transfermarkt parsing issues that caused match rows to show clubs
  against themselves because short aliases and full names were treated as
  different teams
- missing or inconsistent club logos in Mini App match rows
- domestic match parsing issues where away-team labels were resolved
  incorrectly
- Railway and Mini App deployment issues around base URL handling and startup
  flow

### Operational Notes

- the bot remains a manual, throttled, gentle scraper
- local snapshots are still the source of truth for Telegram browsing
- full refreshes and lighter logo-only refreshes are both supported
