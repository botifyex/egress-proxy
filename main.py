import uvicorn
from fastapi import Depends, FastAPI, Request, Response

from src.auth import verify_key
from src.client import Client
from src.config import settings
from src.forward import Forward

app = FastAPI(dependencies=[Depends(verify_key)])


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def forward(path: str, request: Request) -> Response:
    async with Client() as client:
        return await Forward(request, settings.proxy.header).to(client, path)


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.server.host, port=settings.server.port)
