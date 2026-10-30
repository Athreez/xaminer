#!/bin/sh
# Runs backup.sh every night at BACKUP_HOUR (UTC, default 20:30 UTC = 02:00 in India).
set -u
hour="${BACKUP_HOUR:-20}"
minute="${BACKUP_MINUTE:-30}"
echo "nightly backups at $(printf '%02d:%02d' "$hour" "$minute") UTC, kept ${BACKUP_KEEP_DAYS:-7} days"
while true; do
  now=$(date -u +%s)
  next=$(date -u -d "@$now" +%Y-%m-%d)
  target=$(date -u -d "$next $hour:$minute:00" +%s)
  [ "$target" -le "$now" ] && target=$((target + 86400))
  sleep $((target - now))
  sh /scripts/backup.sh || echo "backup failed" >&2
done
