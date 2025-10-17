# watchfiles (recommended)
watchfiles --ignore ".venv|.git" "python main.py"

# entr (macOS)
fd -e py | entr -r python main.py

# nodemon
nodemon --ext py --exec "python main.py"