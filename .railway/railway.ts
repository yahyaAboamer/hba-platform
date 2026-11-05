// Railway Infrastructure as Code for hba-platform (workspace HBA_Server).
//
// Replaces Config as Code (railway.json), which Railway stops reading on
// 2026-12-01. Written from `railway config pull` of each environment on
// 2026-11-05 plus the settings the root railway.json supplied to production;
// `railway config migrate` was run as a dry run only, because its output
// guessed service names from folder names and dropped the restart policies.
//
// WHY THE ROOT railway.json IS STILL THERE. Production's app service still
// gets its health check and restart policy from it, not from its own settings.
// It stays until this file has been applied to production; it can then be
// deleted. It must go no later than 2026-12-01, when Railway stops reading it
// anyway. (ops/backup/railway.json was deleted: no service ever read it.)
//
// HOW THIS FILE TAKES EFFECT. Railway does NOT read it on deploy. It changes
// nothing until someone runs `railway config apply` against an environment.
// Applying is a change to that environment: production needs the owner's
// explicit word, like a deploy.
//
// OMITTING A RESOURCE DELETES IT. This file is the whole project for the
// environment it is evaluated against. Every service, database, volume and
// bucket of an environment must be listed in that environment's branch, and
// every variable a service has must stay listed (as preserve(), which keeps
// the stored value without writing it here). Before any apply, run
// `railway config plan` against that environment and read every line; a
// variable or service added in the dashboard since this file was written
// would show as a deletion.
//
// Commands (from the repository root, CLI 5.42.1 or newer):
//   npm --prefix .railway ci                      (once; installs the SDK)
//   railway environment <production|staging>     (choose the environment)
//   railway config plan                           (read-only)
//   railway config apply                          (owner's word required)
// In Git Bash on Windows the SDK's CLI version check fails because `$_` is the
// npm shell shim; run the CLI as  env _="$(cygpath -m "$(which railway.exe)")" railway.exe config plan
// or point `_` at railway.exe another way.

import { bucket, defineRailway, github, postgres, preserve, project, service, volume } from "railway/iac";

const REPO = "yahyaAboamer/hba-platform";
const REGION = "europe-west4-drams3a";

// Keep each listed variable exactly as stored in Railway.
const keep = (...names: string[]) => Object.fromEntries(names.map((name) => [name, preserve()]));

// The application's build, start, health check and restart policy. Identical
// in both environments; previously the health check and restart policy came
// from railway.json for production and from the dashboard for staging.
const appRuntime = {
  build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
  start: "/app/docker-entrypoint.sh",
  healthcheck: "/api/health/ready",
  healthcheckTimeout: 300,
  replicas: { [REGION]: 1 },
  deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 5 },
} as const;

// The nightly database backup (ops/backup). Its restart policy is NEVER, as
// it is live today: ops/backup/railway.json (ON_FAILURE, 2 retries) was never
// read by either backup service, because Railway does not look for a config
// file inside a service's root directory.
const backupRuntime = {
  build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
  replicas: { [REGION]: 1 },
  deploy: { cronSchedule: "0 0 * * *", restartPolicyType: "NEVER" },
} as const;

const BACKUP_VARIABLES = ["ACCESS_KEY_ID", "BACKUP_KEEP", "BUCKET", "DATABASE_URL", "ENDPOINT", "REGION", "SECRET_ACCESS_KEY"];

export default defineRailway((ctx) => {
  const Postgres = postgres("Postgres", { region: REGION });
  const postgresVolume = volume("postgres-volume", {
    alerts: { usage: { "100": {}, "80": {}, "95": {} } },
    allowOnlineResize: true,
    region: REGION,
    sizeMB: 5000,
  });

  if (ctx.isEnvironment("production")) {
    const hbaPlatform = service("hba-platform", {
      source: github(REPO, { branch: "production", checkSuites: false }),
      ...appRuntime,
      domains: ["affiliate.hbawear.store"],
      env: keep(
        "APP_ENV", "BOSTA_API_KEY", "BREVO_API_KEY", "DATABASE_URL", "ESTEBDAL_API_KEY", "GO_LIVE_MONTH",
        "INBOX_CONFIRMATIONS_ENABLED", "INBOX_MEDIA_ACCESS_KEY_ID", "INBOX_MEDIA_BUCKET", "INBOX_MEDIA_ENDPOINT",
        "INBOX_MEDIA_REGION", "INBOX_MEDIA_SECRET_ACCESS_KEY", "INBOX_PAYMENT_REQUESTS_ENABLED",
        "INBOX_SEND_TO_CUSTOMERS", "MAIL_FROM_ADDRESS", "MAIL_FROM_NAME", "MAINTAINER_EMAIL", "PUBLIC_BASE_URL",
        "SENTRY_DSN", "SENTRY_FRONTEND_DSN", "SETTINGS_ENCRYPTION_KEY", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
        "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_WEBHOOK_SECRET", "TWO_STEP_ENFORCED",
      ),
    });
    const dbBackupProduction = service("db-backup-production", {
      source: github(REPO, { checkSuites: false, rootDirectory: "ops/backup" }),
      ...backupRuntime,
      env: keep(...BACKUP_VARIABLES),
    });
    return project("hba-platform", {
      resources: [
        hbaPlatform,
        dbBackupProduction,
        Postgres,
        postgresVolume,
        bucket("backups", { region: "ams" }),
        bucket("inbox-media-production", { region: "ams" }),
      ],
    });
  }

  if (ctx.isEnvironment("staging")) {
    const hbaPlatformStaging = service("hba-platform-staging", {
      source: github(REPO, { checkSuites: false }),
      ...appRuntime,
      env: keep(
        "APP_ENV", "BOSTA_API_KEY", "BREVO_API_KEY", "DATABASE_URL", "ESTEBDAL_API_KEY", "GO_LIVE_MONTH",
        "INBOX_MEDIA_ACCESS_KEY_ID", "INBOX_MEDIA_BUCKET", "INBOX_MEDIA_ENDPOINT", "INBOX_MEDIA_REGION",
        "INBOX_MEDIA_SECRET_ACCESS_KEY", "MAIL_FROM_ADDRESS", "MAIL_FROM_NAME", "MAINTAINER_EMAIL", "PUBLIC_BASE_URL",
        "SENTRY_DSN", "SENTRY_FRONTEND_DSN", "SETTINGS_ENCRYPTION_KEY", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
        "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_WEBHOOK_SECRET", "TWO_STEP_ENFORCED",
      ),
    });
    // The production service's instance in staging. It has no branch and no
    // deployment; it is listed only so that applying this file does not
    // delete it. Removing it is a separate decision.
    const hbaPlatformDormant = service("hba-platform", {
      source: github(REPO),
      replicas: { [REGION]: 1 },
      env: keep(
        "APP_ENV", "BREVO_API_KEY", "DATABASE_URL", "GO_LIVE_MONTH", "MAIL_FROM_ADDRESS", "MAIL_FROM_NAME",
        "MAINTAINER_EMAIL", "PUBLIC_BASE_URL", "SENTRY_DSN", "SENTRY_FRONTEND_DSN", "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET", "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_WEBHOOK_SECRET", "TWO_STEP_ENFORCED",
      ),
    });
    const dbBackupStaging = service("db-backup-staging", {
      source: github(REPO, { checkSuites: false, rootDirectory: "ops/backup" }),
      ...backupRuntime,
      env: keep(...BACKUP_VARIABLES),
    });
    return project("hba-platform", {
      resources: [
        hbaPlatformStaging,
        hbaPlatformDormant,
        dbBackupStaging,
        Postgres,
        postgresVolume,
        bucket("backups-staging", { region: "ams" }),
        bucket("inbox-media-staging", { region: "ams" }),
      ],
    });
  }

  // Any other environment (a PR environment, a new one) is not described
  // here. Refuse rather than return a project that would delete everything.
  throw new Error(
    `.railway/railway.ts describes only "production" and "staging", not "${ctx.environment ?? ctx.environmentName}".`,
  );
});
