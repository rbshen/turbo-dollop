from contextlib import asynccontextmanager

from fastapi import FastAPI

from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Fathom", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
