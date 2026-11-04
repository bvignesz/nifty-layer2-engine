# Connect FYERS from this environment

The helper is ready at `scripts/fyers_connect.py`. It implements the documented OAuth login, verifies the token with the Profile API, and tests one NIFTY quote. It does not start the collector, modify the SQLite database, schedule tasks, train ML, or place orders. Its only API operations are token exchange, profile read, and quote read.

## 1. Replace the exposed app credentials

Log in to the [FYERS API dashboard](https://fyers.in/web/api-dashboard/user-apps). Revoke the exposed credentials/tokens and create a fresh **non-trading app** for this research engine. FYERS documents this app type as data-only, with no order placement and no static-IP requirement. The new App ID and App Secret appear in the dashboard. Select the permissions required for Profile, Quotes/market data, Historical data and option-chain access where the dashboard exposes permission settings. Account/plan entitlement still determines which data calls work. [Official app setup](https://fyers.in/api-docs/v3/getting-started/create-an-app/individual-app/).

Use this FYERS-recommended redirect URL in the app configuration:

```text
https://trade.fyers.in/api-login/redirect-uri/index.html
```

An existing registered HTTPS redirect you control is also supported. The URL entered in the helper must match the dashboard exactly. The helper does not require a public callback server or an open inbound VPS port: you copy the completed redirect URL back into the terminal. [Redirect and OAuth requirements](https://fyers.in/api-docs/v3/api/authentication/individual-app/generate-auth-code/).

## 2. Open the VPS terminal as ubuntu

Use your SSH app or Hostinger browser terminal. If it opens as root, switch first:

```bash
sudo -iu ubuntu
```

Then run:

```bash
cd /home/ubuntu/nifty-layer2-engine
.venv/bin/python scripts/fyers_connect.py login
```

The helper uses Python's standard library; no additional installation is needed in this prepared checkout. The optional FYERS SDK 3.2.1 is also installed for future integration, but the helper uses documented REST directly to avoid SDK request-log files.

## 3. Complete browser login

Enter the complete new App ID, then the new App Secret at the hidden terminal prompt. Press Enter to accept the default redirect if it matches your app.

The helper prints a FYERS login link. Open it in Android Chrome or another browser. Complete login/consent on FYERS' site. Your account login, OTP and PIN belong on FYERS' site, not in this script or chat.

After redirection, copy the **entire final address** from the browser address bar, including `auth_code` and `state`. Return to the waiting VPS terminal, paste it at the hidden prompt and press Enter. Nothing will appear as you paste: that is expected.

The helper checks redirect identity and random OAuth state, exchanges the authorization code, verifies authentication with Profile, then saves the token. It prints a success line only after the Profile API succeeds. App Secret, auth code, access token and account profile are not printed or logged. The App Secret is not saved. [Token exchange](https://fyers.in/api-docs/v3/api/authentication/individual-app/validate-auth-code/), [Profile token verification](https://fyers.in/api-docs/v3/api/account/profile).

Token file for ubuntu:

```text
/home/ubuntu/.config/nifty-layer2/fyers-token.json
```

It is outside the repository, written atomically with mode 0600 inside a 0700 directory. It contains the access token, App ID, redirect and creation time. It is still a secret file; do not paste or upload it. Refresh tokens returned by FYERS are not retained or used.

## 4. Test actual data access

```bash
.venv/bin/python scripts/fyers_connect.py check
```

Expected shape of output, with an actual FYERS price in place of the placeholder:

```text
FYERS authentication: OK
NIFTY quote: <actual returned price>
Market-data access: OK (quote freshness has not been validated)
Collector remains stopped. No orders were placed.
```

This verifies account authentication and the quote call only. An after-hours quote may be the last available market price. It does not prove live freshness, futures availability, option-chain entitlement or readiness of the nine-check collector.

FYERS documents daily access-token expiry. Repeat `login` after expiry or token revocation; do not create retry loops. Login always asks for the app secret again. [Expiry documentation](https://fyers.in/api-docs/v3/api/authentication/individual-app/validate-auth-code/).

## Troubleshooting

- Missing token file: complete `login` as the same ubuntu user who runs `check`.
- Authentication codes -8/-15/-16/-17: check the new App ID and repeat login with a fresh code/token.
- Redirect/state failure: use the same login attempt and exact registered redirect; do not paste only the auth code.
- Profile succeeds but quote fails: review market-data permissions/plan and report only the error code.
- HTTP 429: stop and wait according to FYERS limits; do not repeatedly run login/check.
- Browser callback has no auth_code/state: inspect the FYERS app configuration and login result before retrying.

[Official troubleshooting](https://fyers.in/api-docs/v3/getting-started/guides/troubleshooting-guide/).

## Verification status

Helper tests validate callback state/redirect matching, private token-file permissions, authentication verification before saving, non-disclosure of secrets in output, and read-only connection checks with mocked responses. The full suite passed 24 tests after adding this helper. No real account login or quote request has been made by the agent; the user must complete the interactive flow before connection can be claimed.
