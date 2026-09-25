# adobe-downloader

Python CLI for downloading, transforming and managing Adobe Analytics report data.
Full documentation is in [`user-docs/`](user-docs/).

## Adobe credentials and the local broker

The tool holds no Adobe credentials. Every API call goes to a local **credential broker**
(`broker/adobe_broker.py`). The broker reads the OAuth Server-to-Server credentials from
your OS keychain, gets and refreshes the IMS access token in memory, and forwards requests
to `analytics.adobe.io` with the auth headers added. It listens on `127.0.0.1` only and
never logs or returns the secret, the token or request headers.

### 1. Store the credentials in the keychain (one-off)

Install the broker's extra dependency, then set each entry. `keyring set` prompts for the
value without echoing it, so it never lands in your shell history:

```powershell
pip install -e ".[broker]"

python -m keyring set adobe-downloader-broker client_id
python -m keyring set adobe-downloader-broker client_secret
python -m keyring set adobe-downloader-broker org_id        # e.g. ABC123@AdobeOrg
python -m keyring set adobe-downloader-broker company_id    # global company ID
```

The values come from your project in the Adobe Developer Console (OAuth Server-to-Server
credential). On Windows they are stored in Credential Manager; on macOS, in Keychain. To
rotate the secret, run the `client_secret` line again and restart the broker.

### 2. Start the broker

Run it yourself in a separate terminal and leave it running:

```powershell
python broker/adobe_broker.py              # http://127.0.0.1:8765
python broker/adobe_broker.py --port 9000  # optional: different port
```

It fetches a token at startup and exits with a short message if an entry is missing or
Adobe rejects the credentials. Each request is logged as a single line
(`GET /reports -> 200`). Stop it with Ctrl+C.

### 3. Run the tool

`adobe-downloader` talks to `http://127.0.0.1:8765` by default. If you changed the port, set
`ADOBE_API_BASE_URL` (e.g. `$env:ADOBE_API_BASE_URL = "http://127.0.0.1:9000"`). Check it
works with:

```powershell
adobe-downloader list-rsids --client Legend
```

Start the broker yourself rather than asking Claude to. `.claude/settings.json` blocks
Claude from running or editing the broker, reading keychain entries and dumping
environment variables.
