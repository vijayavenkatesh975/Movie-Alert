"""Quick diagnostic tool to test Telegram Bot connectivity and send message to admin."""

import httpx
from ticketnotify.config import settings


def run_bot_connectivity():
    print("=" * 60)
    print("  🤖 Testing Telegram Bot Token & API Connectivity...")
    print("=" * 60)

    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    try:
        with httpx.Client(timeout=15.0) as client:
            # 1. getMe
            resp = client.get(f"{url}/getMe")
            if resp.status_code != 200:
                print(f"❌ Failed to reach bot API. HTTP {resp.status_code}: {resp.text}")
                return False

            data = resp.json().get("result", {})
            print(f"✅ Bot API Connection Successful!")
            print(f"   • Bot ID:       {data.get('id')}")
            print(f"   • Bot Name:     {data.get('first_name')}")
            print(f"   • Bot Username: @{data.get('username')}")
            print(f"   • Direct Link:  https://t.me/{data.get('username')}")
            print()

            # 2. Send message to Admin
            admin_id = settings.ADMIN_ID
            msg_payload = {
                "chat_id": admin_id,
                "text": (
                    "🎬 *TicketNotify Bot is online and fully operational!*\n\n"
                    "All features have been successfully updated:\n"
                    "• Multi-Platform Monitoring (BMS, PVR INOX, District, Ticketnew)\n"
                    "• Intelligent Theatre Selection (1-50 km radius)\n"
                    "• Exact Seat Preference Engine (1-10 seats, zones, categories)\n"
                    "• Instant Alert Speed Tiers (Hot 1-3s, Normal 10-15s, Passive)\n"
                    "• Discovery: Now Showing & Coming Soon\n\n"
                    "Type /start or /track to begin!"
                ),
                "parse_mode": "Markdown",
            }
            send_resp = client.post(f"{url}/sendMessage", json=msg_payload)
            if send_resp.status_code == 200:
                print(f"✅ Successfully sent direct Telegram message to admin (ID: {admin_id})!")
            else:
                print(f"⚠️ Telegram returned status {send_resp.status_code}: {send_resp.text}")

            print("=" * 60)
            return True

    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False


if __name__ == "__main__":
    run_bot_connectivity()
