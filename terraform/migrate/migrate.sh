#!/usr/bin/env bash
# Copies the Railway database into this stack's database on the shared RDS
# instance, then proves the copy matches table by table. Runs as a one-off ECS
# task (migrate.tf), because the RDS instance is only reachable from inside the
# VPC. See terraform/README.md, "Migrating from Railway".
#
#   MODE=rehearse  copy and compare; mismatches are reported but don't fail,
#                  since the live site may still be writing (now playing).
#   MODE=final     the same, with the Railway backend stopped: any mismatch
#                  fails the task, and success marks the database as migrated.
#
# Each run drops and recreates the target database, so rehearsals can repeat.
# A database marked as migrated is refused unless FORCE_REMIGRATE=yes: after
# the cutover it holds the only up-to-date copy.
set -euo pipefail

: "${MODE:=rehearse}"
case "$MODE" in rehearse|final) ;; *) echo "MODE must be rehearse or final, got '$MODE'" >&2; exit 2 ;; esac

# Same text form of every timestamp on both sides, so the checksums compare.
export PGTZ=UTC PGCONNECT_TIMEOUT=15

# w_notes keeps its URL in SQLAlchemy's asyncpg form; libpq wants the plain one.
master="${MASTER_URL/postgresql+asyncpg:\/\//postgresql://}"
target="postgresql://${DB_NAME}:${DB_PASSWORD}@${DB_HOST}:5432/${DB_NAME}"

echo "== mode:   $MODE"
echo "== source: Postgres $(psql "$SOURCE_URL" -XAtc 'show server_version')"
echo "== target: Postgres $(psql "$master" -XAtc 'show server_version')"
echo "== client: $(pg_dump --version)"

marker=$(psql "$master" -XAtc "select coalesce(shobj_description(oid, 'pg_database'), '') from pg_database where datname = '${DB_NAME}'")
if [[ "$marker" == migrated-final* && "${FORCE_REMIGRATE:-}" != "yes" ]]; then
  echo "!! ${DB_NAME} is marked '${marker}'. It is the live database now; refusing to overwrite it." >&2
  echo "!! Set FORCE_REMIGRATE=yes only if you mean to throw away everything written since." >&2
  exit 1
fi

echo "== recreating database ${DB_NAME}"
psql "$master" -X -q -v ON_ERROR_STOP=1 -v db="$DB_NAME" -v pw="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'db')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db') \gexec
ALTER ROLE :"db" WITH LOGIN PASSWORD :'pw';
-- Postgres 16: naming another role as a database's owner needs the creator to
-- be able to SET ROLE to it, which creating the role doesn't grant by itself.
GRANT :"db" TO CURRENT_USER WITH SET TRUE;
DROP DATABASE IF EXISTS :"db" WITH (FORCE);
CREATE DATABASE :"db" OWNER :"db";
-- Only the portfolio role (and the master) may connect to it.
REVOKE CONNECT, TEMPORARY ON DATABASE :"db" FROM PUBLIC;
SQL

# Extensions need the master's rights to create, so they're made here and their
# lines are dropped from the dump (the dump's own COMMENT ON EXTENSION would fail
# for a non-owner).
exts=$(psql "$SOURCE_URL" -XAtc "select extname from pg_extension where extname <> 'plpgsql' order by 1")
for e in $exts; do
  echo "== extension $e"
  psql "${master%/*}/${DB_NAME}" -X -q -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS \"$e\""
done

echo "== copying"
# --no-owner/--no-privileges: everything ends up owned by the portfolio role.
# transaction_timeout is a Postgres 17+ setting newer pg_dumps emit, which 16
# rejects. One transaction: the restore lands whole or not at all.
pg_dump "$SOURCE_URL" --format=plain --no-owner --no-privileges \
  | sed -E '/^(SET transaction_timeout|CREATE EXTENSION|COMMENT ON EXTENSION)/d' \
  | psql "$target" -X -q -v ON_ERROR_STOP=1 --single-transaction > /dev/null

echo "== verifying"
tables_sql="select quote_ident(schemaname) || '.' || quote_ident(tablename) from pg_tables
             where schemaname not in ('pg_catalog', 'information_schema') order by 1"
src_tables=$(psql "$SOURCE_URL" -XAtc "$tables_sql")
dst_tables=$(psql "$target" -XAtc "$tables_sql")
if [[ "$src_tables" != "$dst_tables" ]]; then
  echo "!! table lists differ" >&2
  diff <(echo "$src_tables") <(echo "$dst_tables") >&2 || true
  exit 1
fi

# Row count plus an order-independent checksum of every row's text form.
mismatches=0
for t in $src_tables; do
  q="select count(*) || ' ' || coalesce(md5(string_agg(md5(x::text), '' order by md5(x::text))), '-') from $t x"
  a=$(psql "$SOURCE_URL" -XAtc "$q")
  b=$(psql "$target" -XAtc "$q")
  if [[ "$a" == "$b" ]]; then
    printf '   ok        %-40s %s rows\n' "$t" "${a%% *}"
  else
    printf '   MISMATCH  %-40s source %s rows, target %s rows\n' "$t" "${a%% *}" "${b%% *}"
    mismatches=$((mismatches + 1))
  fi
done

# Sequences, so new rows don't collide with copied ids.
seq_sql="select schemaname || '.' || sequencename || '=' || coalesce(last_value::text, 'unused') from pg_sequences order by 1"
if [[ "$(psql "$SOURCE_URL" -XAtc "$seq_sql")" != "$(psql "$target" -XAtc "$seq_sql")" ]]; then
  echo "   MISMATCH  sequences"
  mismatches=$((mismatches + 1))
else
  echo "   ok        sequences"
fi

# Fresh planner statistics; quiet about the shared catalogs it may not touch.
psql "$target" -X -q -c "SET client_min_messages = error" -c "ANALYZE"

if (( mismatches > 0 )); then
  if [[ "$MODE" == "final" ]]; then
    echo "!! $mismatches mismatch(es). Something wrote to Railway during the copy; stop it and run again." >&2
    exit 1
  fi
  echo "== $mismatches mismatch(es); expected in a rehearsal only for tables the live site writes to (now playing)."
  exit 0
fi

if [[ "$MODE" == "final" ]]; then
  psql "$master" -X -q -v ON_ERROR_STOP=1 \
    -c "COMMENT ON DATABASE \"${DB_NAME}\" IS 'migrated-final $(date -u +%FT%TZ)'"
  echo "== final copy verified and marked"
else
  echo "== rehearsal copy verified"
fi
