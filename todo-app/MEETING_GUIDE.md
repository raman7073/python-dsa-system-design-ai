# Meeting guide: understand the implementation

## 1. FastAPI setup and common commands

FastAPI maps Python functions to HTTP paths. Pydantic validates input and builds
OpenAPI documentation; Uvicorn runs the ASGI application. main:app means:
import the main module and run its app object.

```powershell
python -m venv myenv
.\myenv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\myenv\Scripts\python.exe scripts/init_secrets.py
.\myenv\Scripts\python.exe -m alembic upgrade head
.\myenv\Scripts\python.exe -m uvicorn main:app --reload
.\myenv\Scripts\python.exe -m pytest -q
```

--reload restarts the development server after code changes.
GET /docs provides an interactive API client; /openapi.json describes the API.
Ordinary def routes run blocking database/Excel work in FastAPI's thread pool.
async def is useful for awaited I/O; putting blocking work inside it would block the event loop.

## 2. CRUD and database transactions

Create = POST, Read = GET, Update = PUT/PATCH, Delete = DELETE.
POST returns 201; DELETE returns 204 with no body.
PUT replaces all editable fields. PATCH changes only supplied fields.
For example, PATCH {"completed": true} leaves the title and description unchanged.

SQLAlchemy models describe stored rows; Pydantic schemas describe API inputs/outputs.
They are deliberately different: the database stores password hashes and encrypted
descriptions, while API responses never expose password hashes.
db.add stages changes; db.commit commits a transaction; db.refresh reloads a row.
An exception causes rollback and the request's session is always closed.
Alembic records schema versions so changes are explicit and repeatable.

## 3. Authentication, authorization and CORS

Authentication asks: Who are you?
Registration hashes a password using Argon2. Login verifies that hash and issues a JWT.
The client sends Authorization: Bearer <token>. The server verifies the fixed HS256
algorithm, signature, expiry, issuer, audience and subject, then loads the user.

Authorization asks: May you access this todo?
Every todo query includes owner_id == current_user.id. A user's ID comes from the
verified identity, never from client JSON. Another user's todo returns 404.
There is no admin role in this app; ownership is the authorization policy.

A JWT is signed, not encrypted. Its payload can be decoded by anyone holding it.
The signature detects modification; it does not hide content. Never put passwords
or private todo descriptions inside token claims. A stolen valid bearer token grants
access until expiry, so HTTPS and careful client storage are necessary.
See the [official FastAPI JWT tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/).

CORS controls which browser origins may read API responses.
An origin includes scheme, hostname and port: localhost:3000 and localhost:5173 differ.
A browser may send an OPTIONS preflight before a request containing Authorization.
The configured middleware permits explicit origins, methods and headers.
CORS does not authenticate callers and does not block curl or other servers.
Our bearer header flow does not use cookies, so allow_credentials is false.
See [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).

## 4. Hashing, signing, encryption and decryption

| Technique | Purpose | Example in this app |
| --- | --- | --- |
| Password hashing | Check a password without storing a recoverable copy | Argon2 password_hash |
| Signing | Detect changes and establish authenticity | HS256 JWT signature |
| Encryption | Hide recoverable information using a secret key | Fernet todo description |
| Decryption | Recover encrypted information with its key | Owner's response description |
| Encoding | Represent bytes in another format; no secrecy | Base64 portions of JWT |

Passwords are hashed because the application only needs to check them, never recover them.
Descriptions are encrypted because users need to read the original text later.
Writing a todo encrypts the description before storage; reading checks ownership before
decrypting it. A raw database row contains ciphertext, while the owner's API response
contains readable text. The JWT secret and encryption key are separate.

Fernet provides authenticated symmetric encryption: it detects tampering as well as
hiding content. Keep keys separate from database backups and plan key rotation.
Replacing the encryption key without re-encrypting data makes old descriptions unreadable.
See [Fernet documentation](https://cryptography.io/en/latest/fernet/).

## 5. Pagination and sorting

Returning every row wastes memory, bandwidth and database time.
For page 3 with page size 10, offset = (3 - 1) * 10 = 20 and limit = 10.
This app returns items plus total so a frontend can calculate page counts.
All filters, counts and rows are scoped to the authenticated owner.

Example: /todos?offset=20&limit=10&sort_by=created_at&order=desc
The server allows only known sort fields and adds ID as a tie-breaker.
For large or frequently changing datasets, cursor pagination is usually a better next step.

## 6. Excel upload and import

The browser sends multipart/form-data containing a file.
The server checks file size/type, ZIP expansion, worksheet structure and each data row.
Validation happens before any database insert. The full import uses one transaction.
If row 5 has an empty title, the response reports row 5 and inserts nothing.
This prevents half-imported files that are difficult to correct or retry.
openpyxl reads the spreadsheet; defusedxml hardens XML parsing as recommended in
[openpyxl's security notes](https://openpyxl.readthedocs.io/en/stable/).

## A 10-minute demo

1. Start Uvicorn and open /docs. Show the generated request schemas.
2. Register Alice and authorize. Create two todos; show the returned IDs.
3. PATCH one todo to completed and explain why its other fields remain.
4. List with limit=1 and sort_by=title. Explain items versus total.
5. Register Bob and authorize. Show Alice's ID returns 404.
6. Authorize Alice again. Download and import the Excel template.
7. Upload a workbook with one invalid row. Show that the total did not increase.
8. Open app/core/security.py and explain hash, token signature, encrypt and decrypt.
9. Run pytest and discuss the difference between SQLite behavior tests and
   deployment/PostgreSQL integration testing.

## Project structure and the Excel reader

Start at `app/main.py`: it creates the FastAPI application and wires together routers,
middleware and exception handlers. `app/api/routes/` translates HTTP requests into
calls to `app/services/`. Services enforce business rules and control database writes.
`app/models/` defines persisted tables; `app/schemas/` defines validated API contracts.
`app/api/dependencies.py` supplies the authenticated user and a request-scoped session.
This separation lets an endpoint change without mixing routing, security and parsing
in one large file. The root `main.py` simply preserves your existing startup command.

To demonstrate reading a file, authorize and call `POST /excel/read` in Swagger with
an `.xlsx` upload. Any valid named columns are supported. The response includes the
sheet name, column names, row count and values with their original row numbers.
This operation makes no database changes. `POST /todos/import` uses the same reader,
then validates the todo columns and inserts the todos in one transaction.

