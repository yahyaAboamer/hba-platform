# Monitoring and account security: what the owner sets up

Written 25 October 2026 for Phase 1, Batch 1
(`docs/plans/2026-10-25-phase-1-foundations.md`). Everything here is done by
the owner, in the owner's own accounts. **No password, token or key is ever
sent to an engineer or an agent**; none is needed.

---

## 1. Sentry (error alerts)

**What it does for HBA:** when the platform or a browser hits an error, Sentry
emails you once per new kind of error, with where in the code it happened and
how often. Nothing personal is sent: the code removes cookies, headers, request
bodies, addresses, user details, and the tokens in reset and invitation links
before anything leaves the platform.

**What you do (about 15 minutes):**

1. Create an account at sentry.io.
2. When it asks where to store data, choose **European Union**. This cannot be
   changed later.
3. Turn on two-step sign-in for yourself: your avatar → *User settings* →
   *Security* → *Two-factor authentication* → an authenticator app. Save the
   recovery codes somewhere safe.
4. Require it for everyone you ever invite: *Settings* (the organization) →
   *Security & Privacy* → turn on *Require Two-Factor Authentication*.
5. On the same page, leave *Data Scrubber* and *Use Default Scrubbers* on, and
   turn on *Prevent Storing of IP Addresses*.
6. Create two projects:
   - platform **FastAPI**, named `hba-platform-backend`;
   - platform **React**, named `hba-platform-frontend`.

   When asked about alerts, choose to be alerted on every new issue, by email.
7. Open each project → *Settings* → *Client Keys (DSN)* and copy its DSN, the
   address that starts `https://`.
8. In Railway (workspace `HBA_Server`, project `hba-platform`), add two
   variables to **both** services, `hba-platform` (production) and
   `hba-platform-staging` (staging):

   | Variable | Value |
   |---|---|
   | `SENTRY_DSN` | the backend project's DSN |
   | `SENTRY_FRONTEND_DSN` | the frontend project's DSN |

   On staging you can use references to production's values, as the other
   variables there already do (`${{hba-platform.SENTRY_DSN}}`, ADR 0034).
   Staging and production are told apart automatically, from Railway's own
   environment name. Adding a variable restarts that service, so choose the
   moment. Until Batch 1's code is merged and deployed, the variables are simply
   ignored.

**What the engineers need from you:** nothing secret. A DSN is not a password
(the browser one is public by design), but there is no need to send it; you set
it in Railway yourself. No access to Sentry or Railway is needed.

**Later, optional:** readable browser stack traces need a Sentry *auth token*
at build time. That one is a real secret; it is not part of Batch 1.

**How to see it work, once deployed:** the engineers trigger one test error on
staging, and you confirm the email arrived.

---

## 2. Uptime check: UptimeRobot (recommended)

**Why this one:** it's the simplest choice that does the job. The free plan
checks every 5 minutes, emails you, and supports two-step sign-in. Better Stack
is a good alternative with a nicer dashboard, but it takes more to set up and
nothing here needs it.

**What it watches:** `/api/health/ready`. That address answers 200 only when
the platform is up **and** can reach its database, and 503 otherwise. It's the
same check Railway uses before it lets a new deployment take traffic.

**What you do (about 10 minutes):**

1. Create an account at uptimerobot.com.
2. Turn on two-step sign-in in the account's security settings.
3. *Add New Monitor*:
   - type: **HTTP(s)**;
   - name: `HBA production`;
   - URL: your production address followed by `/api/health/ready`;
   - interval: **5 minutes**;
   - alert contact: your email.
4. Optional: a second monitor for staging,
   `https://hba-platform-staging-staging.up.railway.app/api/health/ready`.
5. To see an alert arrive once, add a temporary monitor for your production
   address followed by `/api/health/not-a-page`. It answers 404, so it reads as
   down within minutes. When the email arrives, delete that monitor.

**What the engineers need from you:** only to be told it's done. No code
changes are needed for this.

---

## 3. Two-step sign-in: where to turn it on

An engineer or agent cannot turn these on. Account security settings belong to
the account holder, so **every item below is done by you**. Use an
authenticator app (or a passkey where offered), not text messages, and keep
each account's recovery codes.

| Account | Where | Can you require it for others? |
|---|---|---|
| **GitHub**: both accounts signed in on this machine, `yahyaAboamer` and `hbaaesthetics-lgtm` | *Settings* → *Password and authentication* | Only for an organization. This repository belongs to a personal account, and you are its only collaborator, so turning it on for your own accounts covers it. |
| **Railway** | Account settings → *Security* | If Railway offers it for the `HBA_Server` workspace, turn it on |
| **Sentry** | See section 1 | Yes: *Require Two-Factor Authentication* |
| **UptimeRobot** | See section 2 | Single user |
| **Shopify** | Your account → *Security* | At least for every staff account with admin access; ask each person to turn it on |
| **Meta Business** (WhatsApp) | *Business settings* → *Security Center* | Yes: require two-factor authentication for everyone, or at least admins |
| **ChatGPT** (where Production is hosted until it moves) | *Settings* → *Security* | Single user |
| **Email sending** (the provider whose key is in Railway, e.g. Brevo) | Account security settings | Per account |
| **File storage** (the provider behind the chat-media bucket) | Account security settings | Per account |
| **Google accounts** used for HBA email and sign-ins | Google Account → *Security* | Per account |
| **Bosta, E-stebdal** | Their dashboards, if they offer it | — |
| **The domain registrar**, if HBA has its own domain | Account security settings | — |

The platform's own two-step sign-in, for HBA staff signing in to HBA OS, is
Batch 3 (ADR 0067). It is not something you turn on here.

---

## 4. Branch protection: needs a decision

On 25 October 2026, GitHub refused branch protection and rulesets for this
repository. Its answer was *"Upgrade to GitHub Pro or make this repository
public to enable this feature"*. On GitHub's free plan, protection is only
available on public repositories.

- **With GitHub Pro** (check the current price on GitHub's pricing page;
  it is a few dollars a month): the engineers apply it in two steps.
  1. Straight away: nobody can force-push to `main` or `production`, or delete
     them.
  2. Once the CI pull request is merged: `main` and `production` refuse any
     commit whose `backend` and `frontend` checks have not passed. This applies
     to administrators too, so it also covers work pushed from your own
     account. Turning it off in an emergency stays one setting away for you.
- **Without it:** CI still runs on every pull request and shows red or green;
  GitHub just does not stop a merge itself. The rule *no merge on red* is then
  kept by process (`CLAUDE.md`), not enforced.

Applying step 2 before CI exists on `main` would block every push to `main`
and `production`, including urgent fixes. That is why it waits for the CI
merge.

---

## 5. GitHub Actions minutes

Private repositories on the free plan include a monthly allowance of Actions
minutes; public repositories did not count. The first CI run's length is
recorded in `docs/plans/2026-10-25-phase-1-progress.md`, so the allowance can
be checked against real numbers before it matters.
