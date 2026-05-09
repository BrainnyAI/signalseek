"""Cron pipeline: scan Reddit → score mentions → dispatch alerts."""
import sys
sys.path.insert(0, '/root/signalseek')

from monitor import scan_all_keywords
from scorer import score_and_update_mentions
from alerts import dispatch_unread_mentions

print("=== SignalSeek Pipeline ===")
print("1. Scanning Reddit...")
scan_stats = scan_all_keywords()
print(f"   Scanned: {scan_stats['scanned']} keywords, {scan_stats['new_mentions']} new mentions, {scan_stats['errors']} errors")

print("2. Scoring mentions...")
scored = score_and_update_mentions()
print(f"   Scored: {scored} mentions")

print("3. Dispatching alerts...")
alert_stats = dispatch_unread_mentions()
print(f"   Dispatched: {alert_stats['total']} total, {alert_stats['sent_telegram']} sent, {alert_stats['errors']} errors")

print("=== Pipeline Complete ===")
