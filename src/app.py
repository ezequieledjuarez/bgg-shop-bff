from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="BGG Shop BFF")

# Configuración de orígenes permitidos
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_auth_header(request, call_next):
    auth = request.headers.get("authorization")
    if auth:
        # mask token for logs
        parts = auth.split()
        token_preview = parts[0] + " " + (parts[1][:10] + '...' if len(parts) > 1 else '')
    else:
        token_preview = None
    print(f"BFF Incoming Authorization: {token_preview}")
    response = await call_next(request)
    return response