# PayPilotLabs HRMS

PayPilotLabs HRMS manages your people and their pay: who works for you, when they work, what they are owed, and how you hire and review them.

By [PayPilotLabs](https://paypilotlabs.com). Support and requests: https://paypilotlabs.com/roadmap/

## What it does

- Keeps employee records, departments, designations, branches and grades.
- Tracks attendance and check-ins, shifts, shift requests and holiday lists.
- Handles leave: policies, allocations, applications, approvals and encashment.
- Runs payroll: salary structures, salary slips, payroll runs, taxes, gratuity, bonuses and arrears.
- Processes expense claims, employee advances and travel requests.
- Manages hiring: job requisitions, openings, applicants, interviews and job offers.
- Guides onboarding and separation, including exit interviews and final settlement.
- Runs appraisals: goals, KRAs, appraisal cycles and performance feedback.
- Records training events, grievances, promotions and transfers.
- Includes a mobile app (PWA) where employees check in, apply for leave and claim expenses.

## How it helps your business

- One place for every employee record, so nothing lives in scattered spreadsheets.
- Leave balances and attendance are always current, so there is no dispute about who was off when.
- Payroll is built from attendance and leave, so salary slips match the days people worked.
- Expense claims and advances follow an approval path, so you can see who has claimed what.
- Every candidate stays on one hiring trail, from opening to offer.
- Employees help themselves from their phones, which saves HR time.

## How it fits with other PayPilotLabs products

PayPilotLabs HRMS runs on paypilotlabs-framework, the base all PayPilotLabs products share. It needs no other PayPilotLabs app and runs on its own. It can work alongside PayPilotLabs ERP when you use both on one site.

## Run it

PayPilotLabs HRMS runs as a PayPilotLabs framework v16 site in Docker: MariaDB 11.8, Redis, and an image holding the framework + HRMS.

1. Push this repo and its companions (`paypilotlabs-framework`) to `github.com/paypilotlabs` (private is fine).
2. Build the image: `./docker/build.sh` (while the repos are private: `GITHUB_TOKEN=<token with read access> ./docker/build.sh`; the token is then stored in the image history, so never push that image) It tags `paypilotlabshrms:<git commit>` (push that one to ECR) and `paypilotlabshrms:latest`.
   The token ends up in the image's build arguments (`docker history` shows it), so use a short-lived, read-only token and never push this image to a registry.
3. Start it: `docker compose -f docker/docker-compose.yml up -d`
4. Watch the first-run setup: `docker compose -f docker/docker-compose.yml logs -f create-site` (wait for it to exit 0).
5. Open http://hrms.localhost:8080 and log in as `Administrator` / `admin`. Change the password straight away.

Stop with `docker compose -f docker/docker-compose.yml down` (add `-v` to delete the data).

## Licence

GPL-3.0. See [license.txt](license.txt) for the full terms. Based on open-source work by others; see [NOTICE.md](NOTICE.md) for credits.
