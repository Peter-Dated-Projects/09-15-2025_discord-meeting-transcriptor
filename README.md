# Discord Meeting Transcriptor 🎙️

A powerful Discord bot that automatically records voice channel meetings and provides real-time transcription, intelligent summaries, and interactive note-taking powered by RAG (Retrieval-Augmented Generation).

## ✨ Features

- 🎤 **Real-time Transcription** - Converts voice conversations to text as they happen
- 👥 **Speaker Identification** - Distinguishes between different speakers
- 📝 **Meeting Summaries** - Automatically generates concise summaries
- 🤖 **AI-Powered Q&A** - Ask questions about meeting content using RAG
- 💾 **PostgreSQL Storage** - Persistent storage for transcripts and metadata
- 🔍 **Semantic Search** - Find relevant information across all meetings
- 📊 **Interactive Notes** - Generate structured notes from conversations

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))
- PostgreSQL database (optional, for persistent storage)

### Installation

```bash
# Clone the repository
git clone https://github.com/Peter-Dated-Projects/09-15-2025_discord-meeting-transcriptor.git
cd 09-15-2025_discord-meeting-transcriptor

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env and add your DISCORD_API_TOKEN
```

### Running the Bot

```bash
# Basic run
python main.py

# Development mode (auto-reload on file changes)
make dev
```

## 📚 Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Complete development setup guide, tool installation, and workflow
- **[AGENT.md](AGENT.md)** - Testing strategy, dependencies explanation, and code guidelines
- **[Makefile](Makefile)** - Available commands (`make help` to see all)

## 🛠️ Development

### Setup Development Environment

```bash
# Install development dependencies
make install-dev

# Set up pre-commit hooks
make pre-commit-install

# Run all quality checks
make check-all
```

### Common Commands

```bash
make format          # Auto-format code
make lint            # Check code quality
make type-check      # Run type checking
make test            # Run tests
make test-cov        # Tests with coverage report
make dev             # Run bot with auto-reload
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed setup instructions.

## 🧪 Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
pytest tests/unit/test_rag.py
```

See [AGENT.md](AGENT.md) for testing strategy and guidelines.

## 📁 Project Structure

```
.
├── main.py                      # Bot entry point
├── cogs/                        # Discord command modules
│   ├── general.py               # General commands
│   └── voice.py                 # Voice-related commands
├── source/                      # Core business logic
│   ├── services/                # Service layer
│   │   ├── transcribe.py        # Audio transcription
│   │   └── rag.py               # RAG/LLM operations
│   └── server/                  # External service handlers
│       ├── postgresql.py        # Database handler
│       └── vectordb.py          # Vector database handler
└── tests/                       # Test suite
    ├── unit/                    # Unit tests
    └── integration/             # Integration tests
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file with:

```env
# Required
DISCORD_API_TOKEN=your_discord_bot_token

# Optional (for database features)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=discord_transcriptor
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
```

See [.env.example](.env.example) for all available options.

## 🤝 Contributing

We welcome contributions! Here's how to get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run quality checks (`make check-all`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

Please read [DEVELOPMENT.md](DEVELOPMENT.md) and [AGENT.md](AGENT.md) for code style guidelines and testing requirements.

## 📋 Tech Stack

- **Discord.py** - Discord bot framework
- **PostgreSQL + asyncpg** - Database and async driver
- **Python 3.13** - Core language
- **Ruff + Black** - Code formatting and linting
- **MyPy** - Static type checking
- **Pytest** - Testing framework

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- [Discord.py Documentation](https://discordpy.readthedocs.io/)
- [Development Guide](DEVELOPMENT.md)
- [Agent Documentation](AGENT.md)

## 📞 Support

For questions or issues:
- Open an issue on GitHub
- Check [DEVELOPMENT.md](DEVELOPMENT.md) for setup help
- Review [AGENT.md](AGENT.md) for testing and architecture info

---

**Note:** This bot is currently in active development. Some features may be incomplete or subject to change.

