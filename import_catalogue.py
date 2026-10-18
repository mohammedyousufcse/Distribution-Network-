#!/usr/bin/env python3
"""
CLI Tool for IncuBrix Catalogue Import
Advanced Level Requirement:
Imports, de-duplicates, checks reachability, and reports row-by-row validation errors
for 1,000+ destination records in under 5 minutes.

Usage:
    python import_catalogue.py --csv data/destinations_sample_1000.csv --output-report import_report.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from app.services.catalogue_import_service import catalogue_import_service


def main() -> None:
    parser = argparse.ArgumentParser(description="IncuBrix CSV Destination Catalogue Importer")
    parser.add_argument("--csv", type=str, required=True, help="Path to input CSV file")
    parser.add_argument("--output-report", type=str, default="import_report.json", help="Path to output JSON report")
    parser.add_argument("--mock-reachability", action="store_true", help="Use fast reachability mock mode for benchmark runs")
    parser.add_argument("--skip-reachability", action="store_true", help="Skip network reachability probes")

    args = parser.parse_args()
    csv_path = Path(args.csv)

    if not csv_path.exists():
        print(f"Error: CSV file '{csv_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"=== IncuBrix Destination Catalogue Importer ===")
    print(f"Reading CSV: {csv_path}")
    print(f"Output Report: {args.output_report}")
    print("-" * 50)

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        csv_content = f.read()

    start_time = time.perf_counter()
    report = asyncio.run(
        catalogue_import_service.import_csv_content(
            csv_text=csv_content,
            filename=csv_path.name,
            check_reachability=not args.skip_reachability,
            mock_reachability=args.mock_reachability,
        )
    )
    total_time = round(time.perf_counter() - start_time, 2)

    with open(args.output_report, "w", encoding="utf-8") as out_f:
        json.dump(report, out_f, indent=2)

    print(f"Total Rows Processed : {report['total_rows_processed']}")
    print(f"Imported / Valid     : {report['imported_count']}")
    print(f"Duplicates Caught    : {report['duplicate_count']}")
    print(f"Invalid Rows         : {report['invalid_count']}")
    print(f"Unreachable Hosts    : {report['unreachable_count']}")
    print(f"Elapsed Time         : {total_time}s (Limit: <300s)")
    print(f"Saved audit report   : {args.output_report}")
    print("-" * 50)

    if total_time > 300:
        print("WARNING: Import took longer than the 5-minute threshold!", file=sys.stderr)
        sys.exit(1)

    print("Catalogue import benchmark SUCCESS!")
    sys.exit(0)


if __name__ == "__main__":
    main()
