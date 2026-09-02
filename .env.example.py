GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.6-flash
# Cheaper model used only for translating an already-stored recipe
# into another language. Fill in with whichever cheap Gemini model
# you want to use, then add its pricing snapshot to app/pricing/gemini.py.
GEMINI_TRANSLATION_MODEL=your_cheap_model_here

TESTER_KEYS=abc123,def456,ghi789,jkl012,mno345

DAILY_USER_LIMIT=10
DAILY_GLOBAL_LIMIT=50

REDIS_URL=rediss://default:PASSWORD@HOST:PORT

DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DB