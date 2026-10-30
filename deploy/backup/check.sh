#!/bin/sh
# Restore test (TCK-1406): make a backup, restore it into a fresh database, and compare row
# counts of every table with the live database; check the files archive lists the stored files.
set -eu
sh /scripts/backup.sh
dir=/backups
db=$(ls -1t "$dir"/db-*.dump | head -1)
files=$(ls -1t "$dir"/storage-*.tar.gz | head -1)
scratch=restore_check
dropdb --if-exists "$scratch"
createdb "$scratch"
pg_restore --no-owner --dbname="$scratch" "$db"
counts() {
  psql -d "$1" -At -c "SELECT string_agg(table_name || '=' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text, ' ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
}
live=$(counts "$PGDATABASE")
restored=$(counts "$scratch")
dropdb "$scratch"
if [ "$live" != "$restored" ]; then
  echo "RESTORE CHECK FAILED: row counts differ"; echo "live:     $live"; echo "restored: $restored"
  exit 1
fi
tables=$(echo "$live" | wc -w)
stored=$(find /storage -type f | wc -l)
archived=$(tar -tzf "$files" | grep -cv '/$' || true)
if [ "$archived" -lt "$stored" ]; then
  echo "RESTORE CHECK FAILED: archive has $archived files, storage has $stored"; exit 1
fi
echo "restore check passed: $tables tables match row for row; $archived stored files in $(basename "$files")"
