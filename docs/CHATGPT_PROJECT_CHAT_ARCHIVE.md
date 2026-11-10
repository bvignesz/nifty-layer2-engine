# Sync selected ChatGPT project chats into the private NIFTY website

## Supported and unsupported
- **Supported**: manually export personal ChatGPT conversations, select named trading chats or exact conversation IDs, import to a private SQLite archive, then read/search at authenticated `/chat-archive` in the existing website. Re-running an export import updates existing messages without duplicate entries.
- **Not supported**: automatically watching this ChatGPT account, full real-time two-way sync, importing all private conversations without explicit selection, or replaying chats back into ChatGPT.
- An OpenAI API assistant embedded in your website would create a **separate** new conversation. It will not automatically know all of your ChatGPT history.

Official account export instructions: https://help.openai.com/en/articles/7260999-exporting-your-chatgpt-history-and-data

## On your Android ChatGPT app
Open profile > Settings > Data controls > Export Data and confirm. Follow the email or SMS download link when ready. The official download link expires after 24 hours.

The export ZIP can contain unrelated private data including potentially sensitive chat messages, credentials or health information. **Do not upload the complete ZIP to GitHub, attach it to a public issue, or serve it through a public web route.** On your own computer, extract `conversations.json`, inspect the selected conversation titles and transfer the JSON securely to your own AWS instance (for example using SCP). If the chat contains broker tokens, passwords or OTPs, redact them before import.

## Import into isolated AWS runtime

Use a separate, restricted directory and copy only approved project conversations.

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/trading-platform-vnext-phase1
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python

mkdir -p -m 700 ~/.config/nifty-layer2/web-runtime
$PY -m nifty_l2.chat_archive \
  --db ~/.config/nifty-layer2/web-runtime/chat_archive.db \
  --export /home/ubuntu/private-import/conversations.json \
  --title-contains "NIFTY" \
  --title-contains "Trading Engine" \
  --title-contains "Scanner Project"
```

You may repeat `--conversation-id YOUR_EXACT_ID` to select exact chat IDs instead. **Only explicitly matched titles or IDs are imported**; no default import-all behavior. The importer excludes system and tool messages and drops non-text assets. It caps message sizes and writes SQLite mode `0600`.

Then open your **authenticated** NIFTY website at `https://YOUR-PRIVATE-HOST/chat-archive`. Select the imported chat and search within it. The site and exporter do not automatically synchronize new messages; repeat the export/import after meaningful updates.

## Security

- Keep your existing HTTPS and owner authentication enabled. This endpoint inherits the website's Basic Auth check; it has no unauthenticated upload or write route.
- Do not expose local preview port 8787 publicly.
- Review what you import and exclude unrelated confidential chats.
- Chat archives are copied data. Deleting a chat from ChatGPT does **not** delete the copy you explicitly imported into your own private SQLite database; you manage that copy separately.
- This archive is separate from `research.db`, `market_feed.db`, FYERS tokens, and every trading/order workflow.
