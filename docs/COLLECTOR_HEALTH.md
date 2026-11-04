# AWS collector health check

The monitor reads systemd state and the existing SQLite database without modifying either. It checks the latest `scheduled_research` event and reports JSON with `OK`, `WARN`, `FAIL`, or `WAITING_OUTSIDE_REGULAR_WINDOW`. It does **not** check FYERS exchange quote freshness, whether the data is usable for ML, or whether a session is a special exchange holiday.

## Test and install on AWS

From `/home/ubuntu/nifty-layer2-engine` on the `feat/xgboost-phase1-dataset` branch:

```bash
git pull origin feat/xgboost-phase1-dataset
.venv/bin/python -m pytest -q tests/test_collector_health.py tests/test_ml_dataset.py
.venv/bin/python -m nifty_l2.collector_health
sudo cp deploy/nifty-collector-health.service /etc/systemd/system/
sudo cp deploy/nifty-collector-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nifty-collector-health.timer
systemctl list-timers --all nifty-collector-health.timer
```

Timer runs every weekday at **09:45 Asia/Kolkata**. It is separate from the existing collector and never restarts it. A nonzero exit status causes a failed one-shot audit, which is visible in the journal. Review:

```bash
sudo journalctl -u nifty-collector-health.service -n 50 -l --no-pager
```

The 09:45 check only detects stored event activity. `WARN` does not necessarily mean FYERS failed: exchange holidays, unusual sessions, authentication errors, or no persisted events can produce it. `OK` does not establish market data freshness or signal validity. A timer will not deliver a ChatGPT or Telegram notification; it writes a local journal entry. To disable:

```bash
sudo systemctl disable --now nifty-collector-health.timer
```
