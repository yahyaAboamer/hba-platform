-- Inbox phase 5: the shape of n8n's tables, and nothing in them.
--
-- Read-only. It returns table names, row counts, column names and types,
-- keys and indexes. No row's values, so no name, phone or message.
--
-- Run it against the Postgres service of the Railway project
-- `order-confirmation-message` (production), for example from the
-- service's Database tab, or `railway connect Postgres` in that project.
-- Paste the whole output into the session building the importer.
--
-- n8n's own tables (workflows, executions, credentials, users...) are left
-- out by name. Any app table it keeps for the chats and the sends - such as
-- `wa_sends` - is listed.

WITH n8n_own(name) AS (VALUES
  ('credentials_entity'), ('execution_entity'), ('execution_data'), ('execution_metadata'),
  ('execution_annotations'), ('execution_annotation_tags'), ('annotation_tag_entity'),
  ('workflow_entity'), ('workflows_tags'), ('workflow_statistics'), ('workflow_history'),
  ('shared_workflow'), ('shared_credentials'), ('settings'), ('user'), ('user_api_keys'),
  ('auth_identity'), ('auth_provider_sync_history'), ('invalid_auth_token'),
  ('folder'), ('folder_tag'), ('project'), ('project_relation'), ('role'), ('scope'),
  ('role_scope'), ('tag_entity'), ('variables'), ('webhook_entity'), ('migrations'),
  ('installed_packages'), ('installed_nodes'), ('event_destinations'),
  ('processed_data'), ('test_definition'), ('test_metric'), ('test_run'), ('test_case_execution'),
  ('insights_by_period'), ('insights_metadata'), ('insights_raw'), ('data_table'),
  ('data_table_column'), ('oauth_clients'), ('oauth_access_tokens'), ('oauth_refresh_tokens'),
  ('oauth_authorization_codes'), ('oauth_user_consents'), ('chat_hub_sessions'),
  ('chat_hub_messages'), ('chat_hub_agents'), ('binary_data')
),
app_tables AS (
  SELECT c.oid, c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    AND c.relname NOT IN (SELECT name FROM n8n_own)
)
SELECT line FROM (
  -- Every table, with its exact row count.
  SELECT t.relname AS table_name, 0 AS part, 0 AS pos,
         format('TABLE %s  rows=%s', t.relname,
                (xpath('/row/c/text()', query_to_xml(
                  format('SELECT count(*) AS c FROM public.%I', t.relname), false, true, '')))[1]::text)
         AS line
  FROM app_tables t
  UNION ALL
  -- Its columns.
  SELECT t.relname, 1, a.attnum,
         format('  %s %s%s%s', a.attname, format_type(a.atttypid, a.atttypmod),
                CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END,
                CASE WHEN d.adbin IS NOT NULL THEN ' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid) ELSE '' END)
  FROM app_tables t
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
  LEFT JOIN pg_attrdef d ON d.adrelid = t.oid AND d.adnum = a.attnum
  UNION ALL
  -- Its keys and checks.
  SELECT t.relname, 2, 0, format('  CONSTRAINT %s %s', k.conname, pg_get_constraintdef(k.oid))
  FROM app_tables t
  JOIN pg_constraint k ON k.conrelid = t.oid
  UNION ALL
  -- Its indexes.
  SELECT t.relname, 3, 0, '  ' || i.indexdef
  FROM app_tables t
  JOIN pg_indexes i ON i.schemaname = 'public' AND i.tablename = t.relname
) shape
ORDER BY table_name, part, pos, line;
