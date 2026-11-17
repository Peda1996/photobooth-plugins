#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  cat >&2 <<'EOF'
Usage:
  photobooth_print.sh <printer-name> <file> [options]

Examples:
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg --format 4x6
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg --format 2x6-strip
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg --format 6x8-div2
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg --format 4x6 --clear-queue
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg --format 4x6 --scale fill
  photobooth_print.sh Dai_Nippon_Printing_DS40 photo.jpg --list-formats

Options:
  --format <name>        Named format, e.g. 4x6, 2x6-strip, 5x7, 6x6, 6x8
  --media <ppd-value>    Raw CUPS media/PageSize value, e.g. w288h432
  --orientation <num>    3=portrait, 4=landscape. Default: 4
  --scale <mode>         fit-to-page, fill, none. Default: fit-to-page
  --position <name>      center, top, bottom, left, right. Default: center
  --clear-queue          Cancel all existing jobs before printing
  --ttl <seconds>        Job expires if not printed within this time (e.g. printer unplugged). Default: 300
  --list-formats         Show known DS40 format aliases
EOF
  exit 1
fi

PRINTER_NAME="$1"
FILE="$2"
shift 2

LOG="/var/log/photobooth-print.log"

# Defaults for DS40 4x6 photo paper
FORMAT="4x6"
MEDIA=""
ORIENTATION="4"       # 4 = landscape
SCALE="fit-to-page"
POSITION="center"
CLEAR_QUEUE="false"
JOB_TTL="300"        # seconds; stale jobs are cancelled by CUPS instead of printing later
LIST_FORMATS="false"

ts() { date -Is; }
log() { echo "$(ts) $*" >> "$LOG"; }

print_formats() {
  cat <<'EOF'
Known DS40 format aliases:

  4x6              -> w288h432
  2x6-strip        -> w288h432-div2

  5x7              -> w360h504
  5x7-div2         -> w360h504-div2

  6x6              -> w432h432

  6x8              -> w432h576
  6x8-div2         -> w432h576-div2
  6x8-div4         -> w432h576-div4
  6x8-6x6-2x6      -> w432h576-w432h432_w432h144

  6x9              -> w432h648

Notes:
  The right side is the exact PageSize value reported by your DS40 driver.
  For your current 4x6 media, use: --format 4x6
  For strips from 4x6 media, try: --format 2x6-strip
EOF
}

media_from_format() {
  case "$1" in
    4x6|4x6-photo|postcard)
      echo "w288h432"
      ;;
    2x6|2x6-strip|strip|strips|photostrip)
      echo "w288h432-div2"
      ;;

    5x7)
      echo "w360h504"
      ;;
    5x7-div2|5x7-strip)
      echo "w360h504-div2"
      ;;

    6x6|square)
      echo "w432h432"
      ;;

    6x8)
      echo "w432h576"
      ;;
    6x8-div2)
      echo "w432h576-div2"
      ;;
    6x8-div4)
      echo "w432h576-div4"
      ;;
    6x8-6x6-2x6|6x6-plus-2x6)
      echo "w432h576-w432h432_w432h144"
      ;;

    6x9)
      echo "w432h648"
      ;;

    raw:*)
      echo "${1#raw:}"
      ;;

    *)
      echo "ERROR: Unknown format '$1'" >&2
      echo "Run with --list-formats to see known aliases." >&2
      exit 3
      ;;
  esac
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --format)
      FORMAT="$2"
      shift 2
      ;;
    --media)
      MEDIA="$2"
      shift 2
      ;;
    --orientation)
      ORIENTATION="$2"
      shift 2
      ;;
    --scale)
      SCALE="$2"
      shift 2
      ;;
    --position)
      POSITION="$2"
      shift 2
      ;;
    --clear-queue)
      CLEAR_QUEUE="true"
      shift
      ;;
    --ttl)
      JOB_TTL="$2"
      shift 2
      ;;
    --list-formats)
      LIST_FORMATS="true"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [ "$LIST_FORMATS" = "true" ]; then
  print_formats
  exit 0
fi

if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE" >&2
  log "ERROR file not found: $FILE"
  exit 2
fi

# If no raw --media was provided, resolve --format to real CUPS PageSize/media value.
if [ -z "$MEDIA" ]; then
  MEDIA="$(media_from_format "$FORMAT")"
fi

recover_printer() {
  cupsenable "$PRINTER_NAME" 2>/dev/null || true
  cupsaccept "$PRINTER_NAME" 2>/dev/null || true

  if [ "$CLEAR_QUEUE" = "true" ]; then
    cancel -a "$PRINTER_NAME" 2>/dev/null || true
  fi
}

status_snapshot() {
  lpstat -p "$PRINTER_NAME" -l 2>/dev/null || true
  lpstat -o "$PRINTER_NAME" 2>/dev/null || true
}

scale_options() {
  case "$SCALE" in
    fit-to-page|fit)
      echo "-o fit-to-page"
      ;;
    fill)
      echo "-o print-scaling=fill"
      ;;
    none|off|no)
      echo ""
      ;;
    *)
      echo "ERROR: Unknown scale mode '$SCALE'. Use fit-to-page, fill, or none." >&2
      exit 4
      ;;
  esac
}

log "PRINT request: printer=$PRINTER_NAME file=$FILE format=$FORMAT media=$MEDIA orientation=$ORIENTATION scale=$SCALE position=$POSITION clear_queue=$CLEAR_QUEUE"

log "Status before recover:"
status_snapshot >> "$LOG"

recover_printer

log "Status after recover:"
status_snapshot >> "$LOG"

# --- guard: do not queue a job while the printer is unplugged or reports an error (cover open, media empty, jam ...).
# otherwise the job waits in CUPS and prints later, all at once, when the printer is back.
USB_ID="1343:0003"   # Citizen CX / DNP DS40
BAD_REASONS='media-empty|media-jam|media-needed|cover-open|door-open|input-tray-missing|marker-supply-empty|other-error|paused'

usb_present() {
  lsusb -d "$USB_ID" >/dev/null 2>&1
}

state_reasons() {
  lpoptions -p "$PRINTER_NAME" 2>/dev/null | tr ' ' '\n' | grep '^printer-state-reasons=' || true
}

refresh_printer_status() {
  # asks the printer for its current state; the DS40 reports cover/media state only on request
  printf '#CUPS-COMMAND\nReportLevels\n' | lp -d "$PRINTER_NAME" -o raw -s >/dev/null 2>&1 || true
}

printer_ready() {
  if ! usb_present; then
    log "BLOCKED: printer $PRINTER_NAME not found on USB ($USB_ID), no job created"
    return 1
  fi
  if state_reasons | grep -Eq "$BAD_REASONS"; then
    refresh_printer_status
    sleep 6
    if state_reasons | grep -Eq "$BAD_REASONS"; then
      log "BLOCKED: printer reports $(state_reasons), no job created"
      return 1
    fi
  fi
  return 0
}

if ! printer_ready; then
  echo "Printer not ready, job not created" >&2
  exit 5
fi

SCALE_OPTS="$(scale_options)"

set +e

# shellcheck disable=SC2086
lp -d "$PRINTER_NAME" \
  -o media="$MEDIA" \
  -o orientation-requested="$ORIENTATION" \
  $SCALE_OPTS \
  -o position="$POSITION" \
  -o job-cancel-after="$JOB_TTL" \
  "$FILE"

LP_EXIT=$?
set -e

log "lp exit=$LP_EXIT"
exit "$LP_EXIT"
