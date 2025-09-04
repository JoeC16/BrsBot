# BRS Bot

Deployable multi-user bot for swapping BRS golf tee times.

Features:
- Multi-user login/register
- Club resolver: type any UK club name → slug discovered
- Live player picker: searches members via club autocomplete
- Worker polls every 20s, capped at 2h
- Designed for Render (Web + Worker + Postgres)

## Deploy
1. Push repo to GitHub
2. Render → New → Blueprint → select repo
3. Render provisions:
   - Free Postgres
   - Free Web service
   - Starter Worker (~£5.50/mo)

## Usage
- Open Web UI → Register/Login
- Create job: select club, course, login, PIN, date, window
- Pick up to 4 players
- Worker auto-swaps if a slot appears
