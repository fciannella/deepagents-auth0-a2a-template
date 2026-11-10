# Durable container state

Choose transactional database storage for multi-instance workloads. This
optional R2 pattern is for modest existing SQLite runtimes with a single
container writer. Container disks are ephemeral; an R2 object is a checkpoint,
not a live shared database file. Never run multiple writers against one key.

## Private storage contract

With `--r2-bucket`, the scaffold binds `JOURNAL` and registers an outbound HTTP
interceptor for `storage.internal`. Inside the container:

| Operation | Request | Expected result |
|---|---|---|
| Restore | `GET http://storage.internal/runtime.sqlite` | 200 SQLite bytes, or 404 for a new database |
| Checkpoint | `PUT http://storage.internal/runtime.sqlite` | 204 after storing the body |

The key is `runtime.sqlite` in that project's bucket. Public requests never
dispatch to the storage entrypoint. No R2 API credential is needed in the
container. Keep public app paths such as `/runtime.sqlite` unavailable too.

The interceptor uses `ctx.exports.StorageBridge({})`, including the options
object. Register before startup and when a Durable Object is reconstructed
around a running container; otherwise reloads can break checkpoint requests.

## Runtime adapter

Restore before launching database consumers. A missing object may initialize
a database. Auth failures, 5xx responses, network failures, and corruption must
fail startup; silently treating them as empty storage loses apparent history.

For each checkpoint:

1. Use SQLite's online backup API. Copying only a `.sqlite` file can miss
   committed WAL transactions.
2. Write a temporary destination. Make it standalone with
   `PRAGMA journal_mode=DELETE` on the backup connection, close it, restrict
   permissions, and atomically replace the upload file.
3. Upload and require success. Record checkpoint status without recording
   journal content or tokens.

Serialize checkpoints so an old background upload cannot overwrite a final
shutdown upload. Back up periodically and on graceful shutdown. Stop accepting
work, drain/terminate database consumers, join the checkpoint worker with an
adequate deadline, then perform the final backup. SIGTERM must reach the
supervisor rather than being swallowed by a shell.

Pick and document an interval; the earlier trial used 30 seconds. Abrupt failure
can lose changes since the last successful checkpoint, longer than the nominal
interval if uploads fail. Persist all required state, including replay protection
when present. SQLite checkpoints do not preserve arbitrary filesystem tool
outputs or application secrets.

## Verification

Test a committed WAL row through backup/restore, 404 initialization, corruption
rejection, and storage-unavailable startup. Then test an actual restart through
Worker/R2 bindings. Use synthetic entries and inspect restored values, not only
object existence. Downloaded checkpoints may contain private data; keep them
out of source control and public paths.

[R2 documentation](https://developers.cloudflare.com/r2/)
