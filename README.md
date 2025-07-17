# Crypto News Telegram Bot

A FastAPI-based Telegram bot that delivers personalized crypto news, price alerts, and market intelligence.

## Features

- Real-time price alerts and monitoring
- Personalized news aggregation
- Portfolio tracking
- Smart notifications
- Premium features for subscribed users

## Tech Stack

- FastAPI
- Prisma ORM
- PostgreSQL
- Telegram Bot API
- Python 3.9+

## Prerequisites

- Python 3.9+
- PostgreSQL
- Telegram Bot Token

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd crypto-news-bot
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
- Copy `.env.example` to `.env`
- Fill in required environment variables

5. Initialize database:
```bash
prisma db push
```

6. Run the application:
```bash
uvicorn app.main:app --reload
```

## Project Structure

```
├── app/
│   ├── api/              # API routes
│   ├── core/             # Core functionality
│   ├── models/           # Pydantic models
│   ├── services/         # Business logic
│   ├── utils/            # Utility functions
│   └── main.py          # FastAPI application
├── prisma/              # Prisma schema and migrations
├── tests/              # Test files
├── .env               # Environment variables
├── requirements.txt   # Python dependencies
└── README.md         # Project documentation
```

## API Documentation

Once the application is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT 