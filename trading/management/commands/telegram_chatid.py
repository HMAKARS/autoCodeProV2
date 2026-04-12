"""텔레그램 봇의 chat_id를 조회하는 관리 명령어.

사용법:
  1. 텔레그램에서 봇에게 /start 또는 아무 메시지 전송
  2. python manage.py telegram_chatid
"""

from django.core.management.base import BaseCommand

from trading.telegram_bot import get_chat_id, send_message


class Command(BaseCommand):
    help = "텔레그램 봇에 전송된 메시지에서 chat_id를 조회합니다."

    def handle(self, *args, **options):
        self.stdout.write("텔레그램 chat_id 조회 중...")

        chat_id = get_chat_id()
        if chat_id:
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ Chat ID: {chat_id}\n\n"
                f".env 파일에 다음을 추가하세요:\n"
                f"TELEGRAM_CHAT_ID={chat_id}"
            ))
            send_message("🔔 알림 봇 연결 성공!")
        else:
            self.stdout.write(self.style.ERROR(
                "\n❌ chat_id를 찾을 수 없습니다.\n\n"
                "1. 텔레그램에서 봇을 찾아 /start 메시지를 보내세요\n"
                "2. 다시 이 명령어를 실행하세요"
            ))
