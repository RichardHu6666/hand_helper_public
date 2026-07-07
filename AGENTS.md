# sign_cloud_v1 Agent Notes

Scope: applies to the entire `sign_cloud_v1` repository.

## Working boundaries

- For cloud startup and public smoke-test tasks, do not rewrite the main stream pipeline.
- Do not modify the lite SQLite vocabulary or special-case specific words just to make smoke tests pass.
- Preserve protocol compatibility for:
  - `GET /health`
  - `POST /api/v1/stream/frame`
  - `POST /api/v1/stream/frames`
- Keep support for `location=unknown`, optional `relative_motion`, and `dominant_shape=unknown` / `nondominant_shape=unknown`.
- Treat `location=unknown` during active movement as normal device-side protocol, not as a dropped required field.

## Service entrypoint

- Preferred app entrypoint is `app.main:app`.
- Preferred startup script is `scripts/run_server.sh`.
- `scripts/run_server.sh` initializes the DB, then starts `uvicorn`.
- For public cloud debugging, the service should listen on `0.0.0.0:6000`.
- Do not bind only to `127.0.0.1` when validating public access.
- Root path `/` should return HTTP 200 health-style output because the platform may probe `/`.

## Expected startup practice

- First inspect `README.md`, `scripts/run_server.sh`, and the FastAPI entrypoint before changing startup behavior.
- Prefer existing project startup commands over introducing a new process manager.
- Record or verify:
  - project directory
  - Python environment
  - startup command
  - run mode (`foreground`, `nohup`, `setsid`, `tmux`, etc.)
  - log file
  - PID
  - listening host and port
- If a detached process is required, use a stable launch method and verify the process remains alive.

## Local smoke-test order

- Validate local health first:
  - `curl -sS -i --max-time 5 http://127.0.0.1:6000/health`
- Validate root probe second:
  - `curl -sS -i --max-time 5 http://127.0.0.1:6000/`
- Validate single-frame stream API third.
- Validate batch stream API fourth.
- Use temporary test sessions such as `codex-cloud-smoke-*`.
- Do not use or pollute the default device session `esp32p4-dev-001`.

## Device-side protocol cues

- Active movement uploads should trend toward:
  - `hand_count=1`
  - `dominant_shape=five`
  - `bimanual_relation=single_hand`
  - `movement=left_right / up_down / toward_away`
  - `relative_motion` in the matching direction family
  - `location=unknown`
- If board logs show `cloud skip active no_shape_cache ...`, interpret that as shape-cache priming delay rather than cloud ingress failure.
- `left_right + unknown shape` is not ideal input and should be diagnosed as shape-quality or priming trouble, not silently treated as a generic pending state.

## Local stream smoke-test expectations

- `/api/v1/stream/frame` must not return `404`, `422`, or `500`.
- `/api/v1/stream/frames` must not return `404`, `422`, or `500`.
- Both stream endpoints should return JSON with at least `status`.
- If `processed_frames`, `first_client_seq`, or `last_client_seq` are not implemented in the current response model, record that clearly and do not treat it as a blocker for basic connectivity.

## Debug expectations

- Session debug should expose recent frame primitives with `timestamp` and `client_seq`.
- Pending states should be explainable via debug as one or more of:
  - ideal input with hold noise
  - shape unknown during active movement
  - movement jitter
  - cooldown
  - suppress
  - score, margin, or stability shortfall
- Candidate debug should surface:
  - `final_score`, `primitive_score`, `rag_score`
  - `reject_reasons`
  - `suppress_reason`
  - `shape_match`, `movement_match`, `relative_motion_match`, `location_match`
  - `unknown_count`, `conflict_count`
- Batch debug should preserve the frame that first confirmed and must not let a later pending frame hide the top-level confirmed result.

## Public verification

- Only test the public URL after local `6000` checks pass.
- Current public base URL for cloud coordination is:
  - `<YOUR_SERVER_URL>`
- Public verification order:
  - `GET /health`
  - `POST /api/v1/stream/frame`
  - `POST /api/v1/stream/frames`
- Check application logs to confirm whether public requests reached the app.

## Failure classification

- Local `/health` fails:
  - classify as application startup, port binding, or local route failure.
- Local `/health` passes but public request times out and no request appears in app logs:
  - classify as public ingress / port exposure / platform routing failure.
- Local `/health` passes, public request reaches the app, but response is `4xx` or `5xx`:
  - classify as application route or schema failure.
- Public root probe reaches `/` with `200` but public `/health` still fails:
  - treat that as ingress or external routing behavior until logs prove the request entered the app.

## Reporting expectations

- For service-lift or public-debug tasks, report exact commands used and concise raw-output summaries.
- Include the final conclusion at these layers:
  - app started or not
  - local port listening or not
  - local protocol smoke tests passed or not
  - public ingress passed or not
- When possible, include the final startup command, PID, listening address, and log file path.

