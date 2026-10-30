#!/bin/sh
# Put a backup back (TCK-1406): `make restore STAMP=20261030-203000`. The app is stopped first
# by make. Replaces the database and the stored files with the backup's.
set -eu
stamp="${1:?usage: restore.sh <stamp>, e.g. 20261030-203000 (see the backups folder)}"
db="/backups/db-$stamp.dump"
files="/backups/storage-$stamp.tar.gz"
[ -f "$db" ] && [ -f "$files" ] || { echo "no backup $stamp in the backups folder"; exit 1; }
pg_restore --clean --if-exists --dbname="$PGDATABASE" "$db"
find /storage -mindepth 1 -delete
tar -xzf "$files" -C /storage
echo "restored backup $stamp"
