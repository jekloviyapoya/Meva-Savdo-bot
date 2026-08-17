"""Litsenziya botini ishga tushirish: python run_license_bot.py"""
import asyncio

from app.license_bot.main import main

if __name__ == "__main__":
    asyncio.run(main())
