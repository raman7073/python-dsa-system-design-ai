# Todo API: FastAPI + PostgreSQL

A production-oriented teaching backend covering CRUD, JWT authentication,
owner authorization, CORS, encryption, pagination/sorting, and Excel import.
Python 3.10+. Swagger UI at /docs is the interactive interface; there is no separate frontend.

## Run locally (PowerShell)

Your existing environment is myenv. For a fresh checkout, create it first:
```powershell
python -m venv myenv
.\myenv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

For a new checkout only, copy .env.example to .env. Do not overwrite an existing .env.
Set POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB.
Create the named PostgreSQL database in pgAdmin if it does not already exist.
Alternatively set DATABASE_URL=sqlite:///./todo.db for local experimentation.

```powershell
.\myenv\Scripts\python.exe scripts/init_secrets.py
.\myenv\Scripts\python.exe -m alembic upgrade head
.\myenv\Scripts\python.exe -m uvicorn main:app --reload
```

The secrets script appends missing keys without printing them or replacing existing ones.
Use a random JWT secret and a separate Fernet key. If existing values are invalid,
correct them explicitly. Keep the encryption key backed up: losing it loses access to descriptions.
Open http://127.0.0.1:8000/docs.

## Try the complete flow

1. POST /auth/register with the JSON below.
2. Click **Authorize** in Swagger and enter that username/password. Leave client ID
   and client secret empty. Swagger calls /auth/token using form data and attaches
   the returned bearer token to subsequent requests.
3. POST /todos, then try GET, PATCH, PUT and DELETE using its ID.
4. GET /todos/import/template, edit the downloaded Excel file, and upload it
   through POST /todos/import.
5. Register another user and authorize as them: the first user's todos are invisible.

Registration:
```json
{"username": "alice", "password": "choose-a-long-unique-password"}
```

Create a todo:
```json
{"title": "Prepare tomorrow's meeting", "description": "Explain JWT and CORS", "completed": false}
```

Partial update:
```json
{"completed": true}
```

| Method | Endpoint | Behavior |
| --- | --- | --- |
| POST | /auth/register | Create user; password is hashed; 201 |
| POST | /auth/token | Username/password form login; 15-minute JWT |
| GET | /auth/me | Current authenticated user |
| POST | /todos | Create a todo for the current user; 201 |
| GET | /todos | Paginated list with total, offset, limit and items |
| GET | /todos/{id} | Read an owned todo |
| PUT | /todos/{id} | Replace editable fields |
| PATCH | /todos/{id} | Change only supplied fields |
| DELETE | /todos/{id} | Delete owned todo; 204 |
| GET | /todos/import/template | Download .xlsx template |
| POST | /todos/import | Atomic Excel import; 201 |
| POST | /excel/read | Upload a spreadsheet and return its rows as JSON; no database writes |
| GET | /health | Database connectivity check |

Todos and Excel endpoints require Authorization: Bearer <token>.
401 means missing/invalid/expired authentication. 404 means the todo is missing
or belongs to another user. 409 means an unavailable username. 422 means invalid
input. 413 means a size/row limit was exceeded. 415 means unsupported file extension.

PUT requires title and resets omitted description/completed to null/false.
PATCH preserves omitted fields; description can be explicitly null, but title and
completed cannot. Unknown fields are rejected, so clients cannot assign owner_id.

## Pagination and sorting

Example:
```text
GET /todos?offset=0&limit=10&sort_by=title&order=asc&completed=false
```

Response:
```json
{"items": [], "total": 0, "offset": 0, "limit": 10}
```

offset skips rows; limit caps returned rows (1-100, default 20).
total counts owned rows matching the completed filter before pagination.
Allowed sort fields: id, title, created_at, updated_at, completed.
order is asc or desc. ID breaks ties, making ordering deterministic for unchanged data.
The sort field uses an allowlist mapped to SQLAlchemy columns, never raw user SQL.
Offset is capped at 1,000,000. Large deployments should add cursor pagination:
concurrent inserts/updates can shift offset pages, and large offsets cost more.

## Excel format and validation

Use one worksheet and exactly these case-sensitive headers, in order:

| title | description | completed |
| --- | --- | --- |
| Learn FastAPI | Practice authentication | FALSE |
| Write tests | | TRUE |

title is required (1-200 characters after trimming); description is optional
(up to 5,000 characters); completed accepts booleans or Pydantic boolean forms
such as true/false and 1/0. Blank completed means false. Blank rows are skipped.
The importer rejects formulas, additional populated columns, invalid headers,
multiple worksheets, corrupt archives, and invalid data. It reports row numbers
without echoing cell contents. All rows are validated before a single transaction
saves them: one invalid row means nothing is imported.

Limits: 2 MiB file, 1,000 worksheet data rows (including blank rows between records),
100 ZIP entries, 20 MiB total uncompressed ZIP content. The application also bounds
the whole HTTP request at 3 MiB before multipart parsing. defusedxml protects XML
parsing. Uploads are processed in a worker thread and are not retained.
Uploading the same workbook twice creates duplicate todos; imports are not idempotent.

## Upload and read an Excel file

Use **POST /excel/read** with an authenticated multipart upload named `file`.
This endpoint reads a general spreadsheet; it does not require todo columns and does
not save the file or create todos. To save todos, use **POST /todos/import** instead.

In `/docs`, register and authorize, expand `/excel/read`, click **Try it out**, choose
an `.xlsx` file and click **Execute**. Or use PowerShell:

```powershell
$token = "your-access-token"
curl.exe -X POST "http://127.0.0.1:8000/excel/read" -H "Authorization: Bearer $token" -F "file=@C:/path/report.xlsx"
```

For a sheet with headers `name`, `score`, `active`, the response looks like:

```json
{
  "sheet": "Sheet1",
  "columns": ["name", "score", "active"],
  "total": 1,
  "rows": [
    {"row_number": 2, "values": {"name": "Alice", "score": 42, "active": true}}
  ]
}
```

The first row must have unique, nonempty text headers (up to 200 characters).
Surrounding header whitespace is trimmed. One worksheet, up to 50 columns and 1,000
data rows are supported. Numbers and booleans retain their JSON types, missing cells
become null, dates/times become ISO strings, and durations become strings. Blank rows
are skipped while original worksheet row numbers are retained. A headers-only sheet
returns an empty rows list. Cells are limited to 5,000 characters. Formulas, Excel error
cells, duplicate headers and populated cells without headers are rejected.
The same upload, ZIP expansion and request limits used by the todo importer apply.

## How the code fits together

```text
app/
  main.py                 # create_app(): assemble the application
  api/
    router.py             # register all routers
    dependencies.py       # request database session and authenticated user
    routes/
      auth.py
      todos.py
      excel.py
      health.py
  core/
    config.py             # environment and validated secrets
    security.py           # hashing, JWT creation, encryption
    middleware.py         # request limits and metadata
    errors.py             # shared exception handlers
  db/session.py           # SQLAlchemy engine, Base and session lifecycle
  models/                 # user.py and todo.py database models
  schemas/                # auth.py, todo.py and excel.py API contracts
  services/               # auth.py, todos.py and excel.py business operations
migrations/               # Alembic schema history
scripts/                  # local setup utilities
tests/                    # fixtures, API tests, Excel tests and migration tests
main.py                   # compatibility entry point
```

| File | Responsibility |
| --- | --- |
| app/main.py | Application factory, middleware and router registration |
| app/api/routes/ | HTTP request handling and response contracts |
| app/api/dependencies.py | JWT verification, user lookup and request session injection |
| app/services/ | Business rules, ownership queries and transaction boundaries |
| app/schemas/ | Request/response validation |
| app/models/ | SQLAlchemy tables, ownership, timestamps and index |
| app/db/session.py | Connection pool, request sessions and rollback |
| app/core/ | Settings, cryptography, middleware and exception handling |
| migrations/ | Versioned schema changes |
| tests/ | Isolated endpoint and migration tests |

Flow: request -> middleware -> schema validation + authentication dependencies ->
router -> service -> database -> response serialization -> response middleware.
Routers handle HTTP inputs; services hold the operations that can be reused by other
entry points. Services currently own SQLAlchemy queries and commits; there is no
additional repository abstraction for these simple operations. Excel parsing is shared
by the read endpoint and the importer so their file validation does not drift apart.
`create_app()` lets each test use a fresh app with isolated dependency overrides.
The old `uvicorn main:app --reload` command still works; the canonical command is:

```powershell
.\myenv\Scripts\python.exe -m uvicorn app.main:app --reload
```
Database sessions are closed automatically and rolled back when an exception occurs.
Successful responses expose X-Request-ID and X-Process-Time. Request logs contain
method/path/status, not passwords, tokens, bodies or query strings. Configure the
todo.api logger at INFO in your deployment to collect access metadata.

## Existing data and API changes

The old unauthenticated todos table remains untouched, including any plaintext
descriptions it already contains. New records use users and task_items.
Legacy rows are not exposed because there is no trustworthy owner mapping.
To migrate them later, explicitly decide who owns each row and encrypt descriptions
during a reviewed migration. No existing records are automatically assigned.

GET /todos now returns a pagination object instead of a bare list.
All todo operations now require login. The educational /add route was removed.
Startup no longer creates tables automatically; run Alembic first.

## Tests and migrations

```powershell
.\myenv\Scripts\python.exe -m pytest -q
.\myenv\Scripts\python.exe -m alembic current
.\myenv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
```

Review generated migrations before running upgrade head. The migration configuration
excludes the preserved legacy todos table from automatic deletion proposals.
Tests use isolated SQLite and test-only random secrets; they never access your PostgreSQL data.
PostgreSQL integration and deployment load tests remain separate checks.

## Production deployment scope

This is a stronger engineering foundation, not a certification of production readiness.
Use HTTPS, a secret manager, restricted database credentials, backups with restore drills,
and a deployment migration step. Store secrets outside source control.
Configure CORS_ORIGINS as exact frontend origins, separated by commas.
Run without --reload in deployment.

Before public exposure, configure shared rate limiting for registration/login and imports
at your reverse proxy/API gateway, request timeouts, monitoring, and dependency scanning.
Add account recovery/verification and a revocation or refresh-token strategy if required.
Tokens currently expire after 15 minutes; there is no server-side logout/revocation.
Removing a token on the client does not invalidate a stolen copy.
Database failures return a generic 503; encryption-key/data corruption failures are not
silently ignored. Encryption protects database contents, not an attacker controlling the
running application or its keys. Titles and metadata are not encrypted.

See [MEETING_GUIDE.md](MEETING_GUIDE.md) for explanations and a demo script.

