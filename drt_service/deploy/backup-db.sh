#!/usr/bin/env bash
# SQLite 온라인 백업 (1단계 배포용)
#
# cron 등록 예 (매일 새벽 4시):
#   0 4 * * * /srv/drt_service/deploy/backup-db.sh >> /var/log/drt-backup.log 2>&1
#
# .backup 명령은 서버가 돌아가는 중에도 일관된 스냅샷을 만든다.
# 파일을 그냥 cp 하면 WAL 때문에 깨진 사본이 나올 수 있다.
set -euo pipefail

DB="${DRT_DB:-/srv/drt_service/db.sqlite3}"
DEST="${DRT_BACKUP_DIR:-/var/backups/drt}"
KEEP_DAYS="${DRT_BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${DEST}/db-${STAMP}.sqlite3"

mkdir -p "$DEST"
sqlite3 "$DB" ".backup '${OUT}'"
gzip -f "$OUT"
echo "$(date -Is) 백업 완료: ${OUT}.gz ($(du -h "${OUT}.gz" | cut -f1))"

# 오래된 백업 정리
find "$DEST" -name 'db-*.sqlite3.gz' -mtime "+${KEEP_DAYS}" -delete

# S3로도 보내려면 주석을 해제한다.
# aws s3 cp "${OUT}.gz" "s3://${DRT_BACKUP_BUCKET}/drt/"
