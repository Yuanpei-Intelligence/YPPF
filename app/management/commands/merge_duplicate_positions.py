from django.core.management.base import BaseCommand
from django.db import transaction
from app.models import NaturalPerson, Organization, Position
from collections import defaultdict


class Command(BaseCommand):
    help = 'Merge duplicate Position objects by keeping the one with minimum position value'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING(
                'DRY RUN MODE - No changes will be made'))

        if not dry_run:
            # Wrap the entire operation in a single transaction to avoid race conditions
            with transaction.atomic():
                self._process_duplicates(dry_run)
        else:
            # For dry run, we don't need transaction protection
            self._process_duplicates(dry_run)

    def _process_duplicates(self, dry_run):
        """Process duplicate positions within a transaction"""
        # Find duplicates based on (person, org, semester, year)
        duplicates = self.find_duplicates()

        if not duplicates:
            self.stdout.write(self.style.SUCCESS(
                'No duplicate Position objects found.'))
            return

        self.stdout.write(
            f'Found {len(duplicates)} groups of duplicate Position objects.')

        total_merged = 0
        total_deleted = 0

        for group_key, positions in duplicates.items():
            if len(positions) <= 1:
                continue

            # Format group key for user-friendly display
            person_id, org_id, semester, year = group_key
            person = NaturalPerson.objects.get(id=person_id)
            org = Organization.objects.get(id=org_id)

            group_display = f"{person} in {org} ({year} {semester})"
            self.stdout.write(f'\nProcessing group: {group_display}')
            self.stdout.write(f'  Found {len(positions)} duplicate positions')

            # Sort by position value to find the minimum
            positions_sorted = sorted(positions, key=lambda p: p.pos)

            # Check if any of the positions to be deleted are admin positions
            admin_positions_to_delete = [
                pos for pos in positions_sorted[1:] if pos.is_admin]
            if admin_positions_to_delete:
                self.stdout.write(
                    self.style.ERROR(
                        f'  ERROR: Found {len(admin_positions_to_delete)} admin positions to delete!'
                    )
                )
                self.stdout.write(
                    self.style.ERROR(
                        f'  Rolling back entire transaction to avoid deleting admin positions.'
                    )
                )
                raise ValueError(
                    f'Cannot delete admin positions for {group_display}. '
                    f'Found {len(admin_positions_to_delete)} admin positions that would be deleted.'
                )

            keep_position = positions_sorted[0]
            delete_positions = positions_sorted[1:]

            self.stdout.write(
                f'  Keeping position ID {keep_position.id} with pos={keep_position.pos}'
            )
            self.stdout.write(
                f'  Deleting {len(delete_positions)} duplicate positions'
            )

            if not dry_run:
                try:
                    # Delete the duplicate positions
                    for pos in delete_positions:
                        pos.delete()
                        total_deleted += 1
                    total_merged += 1

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'  Error processing group {group_key}: {e}')
                    )
                    # Re-raise to rollback the entire transaction
                    raise
            else:
                total_deleted += len(delete_positions)
                total_merged += 1

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDRY RUN SUMMARY: Would merge {total_merged} groups and delete {total_deleted} duplicate positions'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSUCCESS: Merged {total_merged} groups and deleted {total_deleted} duplicate positions'
                )
            )

    def find_duplicates(self) -> dict[tuple[int, int, str, int], list[Position]]:
        """Find groups of duplicate Position objects based on (person, org, semester, year)
        
        Returns a dictionary that maps (person_id, org_id, semester, year) to a list of Position objects.
        """
        duplicates = defaultdict(list)

        # Get all positions and group them by the unique constraint fields
        positions = Position.objects.all()

        for position in positions:
            group_key = (
                position.person_id,
                position.org_id,
                position.semester,
                position.year
            )
            duplicates[group_key].append(position)

        # Filter to only groups with more than one position
        return {k: v for k, v in duplicates.items() if len(v) > 1}
