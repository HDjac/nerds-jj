#!/usr/bin/env python3

import argparse
import csv
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

CSV_FIELDS = [
    "identifier",
    "participant_id",
    "developer",
    "condition",
    "assigned_at",
]

AI_CONDITION = "AI"
NON_AI_CONDITION = "NON_AI"

MIN_ID = 1
MAX_ID = 1023


def read_existing_rows(csv_file: Path) -> List[Dict[str, str]]:
    if not csv_file.exists() or csv_file.stat().st_size == 0:
        return []

    with csv_file.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            return []

        missing_fields = set(CSV_FIELDS) - set(reader.fieldnames)
        if missing_fields:
            raise ValueError(
                "CSV file is missing required columns: "
                + ", ".join(sorted(missing_fields))
            )

        return list(reader)


def normalize_boolean(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def count_developer_conditions(rows: List[Dict[str, str]]) -> tuple[int, int]:
    ai_count = 0
    non_ai_count = 0

    for row in rows:
        if not normalize_boolean(row.get("developer", "")):
            continue

        condition = row.get("condition", "").strip().upper()

        if condition == AI_CONDITION:
            ai_count += 1
        elif condition == NON_AI_CONDITION:
            non_ai_count += 1

    return ai_count, non_ai_count


def assign_condition(is_developer: bool, existing_rows: List[Dict[str, str]]) -> str:
    # Current rule:
    # Developers are balanced across AI/NON_AI.
    # Non-developers are assigned to AI.
    if not is_developer:
        return AI_CONDITION

    ai_count, non_ai_count = count_developer_conditions(existing_rows)

    if ai_count < non_ai_count:
        return AI_CONDITION

    if non_ai_count < ai_count:
        return NON_AI_CONDITION

    return random.choice([AI_CONDITION, NON_AI_CONDITION])


def collect_existing_ids(rows: List[Dict[str, str]]) -> Set[int]:
    existing_ids: Set[int] = set()

    for row in rows:
        raw_id = row.get("participant_id", "").strip()

        if not raw_id:
            continue

        try:
            participant_id = int(raw_id)
        except ValueError:
            continue

        if MIN_ID <= participant_id <= MAX_ID:
            existing_ids.add(participant_id)

    return existing_ids


def generate_participant_id(condition: str, existing_ids: Set[int]) -> int:
    # Keep current NERDS rule:
    # AI = even PID, NON_AI = odd PID.
    required_parity = 0 if condition == AI_CONDITION else 1

    available_ids = [
        participant_id
        for participant_id in range(MIN_ID, MAX_ID + 1)
        if participant_id % 2 == required_parity
        and participant_id not in existing_ids
    ]

    if not available_ids:
        raise RuntimeError(
            f"No unused participant IDs remain for the {condition} condition."
        )

    return random.choice(available_ids)


def find_existing_assignment(
    identifier: str,
    rows: List[Dict[str, str]],
) -> Dict[str, str] | None:
    normalized_identifier = identifier.strip().lower()

    for row in rows:
        if row.get("identifier", "").strip().lower() == normalized_identifier:
            return row

    return None


def write_header_if_needed(csv_file: Path) -> None:
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    if not csv_file.exists() or csv_file.stat().st_size == 0:
        with csv_file.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()


def append_assignment(csv_file: Path, assignment: Dict[str, str]) -> None:
    write_header_if_needed(csv_file)

    with csv_file.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writerow(assignment)


def add_url_param(base_url: str, participant_id: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}participant_id={participant_id}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or reuse a study PID and consent-link assignment."
    )

    parser.add_argument(
        "identifier",
        help="QuestionPro screening response ID or other unique screening identifier.",
    )

    parser.add_argument(
        "developer",
        choices=["0", "1"],
        help="1 if participant is a developer; 0 otherwise.",
    )

    parser.add_argument(
        "--csv",
        default="study-data/participant_assignments.csv",
        help="Path to participant assignment CSV.",
    )

    parser.add_argument(
        "--consent-url",
        required=True,
        help="Base QuestionPro consent form URL.",
    )

    args = parser.parse_args()

    csv_file = Path(args.csv)
    identifier = args.identifier.strip()
    is_developer = args.developer == "1"

    if not identifier:
        raise SystemExit("Error: identifier cannot be empty.")

    rows = read_existing_rows(csv_file)
    existing = find_existing_assignment(identifier, rows)

    if existing is not None:
        participant_id = existing["participant_id"]
        condition = existing["condition"]

        print("Existing assignment found.")
    else:
        condition = assign_condition(is_developer, rows)
        existing_ids = collect_existing_ids(rows)
        participant_id = str(generate_participant_id(condition, existing_ids))

        assignment = {
            "identifier": identifier,
            "participant_id": participant_id,
            "developer": "1" if is_developer else "0",
            "condition": condition,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }

        append_assignment(csv_file, assignment)

        print("Created assignment.")

    consent_link = add_url_param(args.consent_url, participant_id)

    print(f"Identifier:   {identifier}")
    print(f"Participant:  {participant_id}")
    print(f"Developer:    {1 if is_developer else 0}")
    print(f"Condition:    {condition}")
    print(f"Consent URL:  {consent_link}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())