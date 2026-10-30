#!/bin/sh
# One backup (TCK-1406): the database (pg_dump, custom format) and the stored files (a tar of
# the storage volume), named by time, then backups older than BACKUP_KEEP_DAYS are deleted.
set -eu
dir=/backups
stamp=$(date -u +%Y%m%d-%H%M%S)
mkdir -p "$dir"
pg_dump --format=custom --file="$dir/db-$stamp.dump.part" "$PGDATABASE"
mv "$dir/db-$stamp.dump.part" "$dir/db-$stamp.dump"
tar -czf "$dir/storage-$stamp.tar.gz.part" -C /storage .
mv "$dir/storage-$stamp.tar.gz.part" "$dir/storage-$stamp.tar.gz"
find "$dir" -maxdepth 1 \( -name 'db-*.dump' -o -name 'storage-*.tar.gz' \) \
  -mtime +"${BACKUP_KEEP_DAYS:-7}" -delete
echo "backup $stamp: $(du -h "$dir/db-$stamp.dump" | cut -f1) database, $(du -h "$dir/storage-$stamp.tar.gz" | cut -f1) files"
