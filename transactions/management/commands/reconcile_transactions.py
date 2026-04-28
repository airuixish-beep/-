from django.core.management.base import BaseCommand

from transactions.reconciliation import ReconciliationService


class Command(BaseCommand):
    help = "Run internal transaction reconciliation"

    def handle(self, *args, **options):
        run = ReconciliationService.run_internal_check()
        self.stdout.write(
            self.style.SUCCESS(
                f"reconciliation run #{run.id} finished with {run.items.count()} issue(s)"
            )
        )
