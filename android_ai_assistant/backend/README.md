# WorldLogicLine Assistant backend

Production architecture: Android client -> HTTPS API -> stateful agent -> PostgreSQL.

The agent runtime is designed around a persistent/stateful framework rather than storing the AI brain in the APK. Long-term memory is server-side and survives phone replacement.

Required production boundaries:
- authentication per employee
- tenant/company isolation
- encrypted transport
- secrets only on server
- PostgreSQL backups
- audit logging
- model provider configurable by environment

The Android app must never contain an LLM provider secret.
