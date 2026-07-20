from django.core.management.base import BaseCommand
from roster.models import StaffMember


class Command(BaseCommand):
    help = "デモ用の担当者10名を登録します"

    def handle(self, *args, **options):
        for index in range(1, 11):
            StaffMember.objects.get_or_create(
                name=f"担当者{index}",
                defaults={"display_order": index},
            )
        self.stdout.write(self.style.SUCCESS("デモ担当者を登録しました。"))
