"""Fix f-string syntax errors in quote_extractor.py"""

PATH = "/root/csl-bot/csl-doc-tracker/quote_extractor.py"

with open(PATH) as f:
    content = f.read()

# Fix .msg f-string: {msg.subject or } -> {msg.subject or ''}
content = content.replace(
    'body = f"Subject: {msg.subject or }\\nFrom: {msg.sender or }\\nDate: {msg.date or }\\n\\n{msg.body or }"',
    "body = f\"Subject: {msg.subject or ''}\\nFrom: {msg.sender or ''}\\nDate: {msg.date or ''}\\n\\n{msg.body or ''}\""
)

# Fix .eml f-string: msg.get(subject, ) -> msg.get('subject', '')
content = content.replace(
    'body = f"Subject: {msg.get(subject, )}\\nFrom: {msg.get(from, )}\\nDate: {msg.get(date, )}\\n\\n"',
    "body = f\"Subject: {msg.get('subject', '')}\\nFrom: {msg.get('from', '')}\\nDate: {msg.get('date', '')}\\n\\n\""
)

with open(PATH, "w") as f:
    f.write(content)

# Verify it parses
import py_compile
try:
    py_compile.compile(PATH, doraise=True)
    print("Fixed and verified - no syntax errors!")
except py_compile.PyCompileError as e:
    print(f"Still has errors: {e}")
