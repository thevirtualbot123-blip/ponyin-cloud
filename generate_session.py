"""
generate_session.py — Jalankan SEKALI untuk buat session permanent.
Setelah ini, tidak akan pernah minta OTP lagi selama pakai string yang sama.
"""
import asyncio
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


async def main():
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("Install dulu: pip install telethon")
        return

    api_id   = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    phone    = os.getenv("TELEGRAM_PHONE", "").strip()

    if not api_id or not api_hash:
        print("❌ Set TELEGRAM_API_ID dan TELEGRAM_API_HASH di .env dulu!")
        return

    if not phone:
        phone = input("Masukkan nomor HP (format: +628xxx): ").strip()

    print(f"\nLogin dengan nomor: {phone}")
    print("Kamu akan terima OTP di Telegram...\n")

    # StringSession kosong = fresh login
    client = TelegramClient(StringSession(), int(api_id), api_hash)

    await client.start(phone=phone)

    # Simpan session sebagai string
    session_string = client.session.save()

    print("\n" + "="*60)
    print("✅ SESSION BERHASIL DIBUAT!")
    print("="*60)
    print("\nCopy baris ini ke file .env kamu:")
    print(f"\nTG_SESSION_STRING={session_string}\n")
    print("="*60)
    print("PENTING: Setelah ini agent tidak akan minta OTP lagi!")
    print("Jangan share session string ini ke siapapun.")

    # Simpan ke file juga
    with open(".env.session", "w") as f:
        f.write(f"TG_SESSION_STRING={session_string}\n")
    print("\nJuga tersimpan di file: .env.session")
    print("Copy isi file itu ke .env kamu.\n")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
