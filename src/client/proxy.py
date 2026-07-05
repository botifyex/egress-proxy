from typing import Self

from src.client.base import Body, Client, Headers, Method, Params


class ForwardProxy:
    def __init__(self, base: str, key: str, header: str) -> None:
        self._proxy = type("ForwardProxy", (Client,), {"base": base})()
        self._key = key
        self._header = header

    async def __aenter__(self) -> Self:
        await self._proxy.__aenter__()
        return self

    async def __aexit__(self, *error: object) -> None:
        await self._proxy.__aexit__(*error)

    def target(self, url: str) -> str:
        return f"/{url}"

    def authenticated(self, headers: Headers | None) -> Headers:
        merged = dict(headers or {})
        merged[self._header] = self._key
        return merged

    async def get(
        self,
        url: str,
        *,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Body | None:
        return await self._proxy.get(
            self.target(url), params=params, headers=self.authenticated(headers)
        )

    async def post(
        self,
        url: str,
        *,
        body: Body | None = None,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Body | None:
        return await self._proxy.post(
            self.target(url),
            body=body,
            params=params,
            headers=self.authenticated(headers),
        )

    async def put(
        self,
        url: str,
        *,
        body: Body | None = None,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Body | None:
        return await self._proxy.put(
            self.target(url),
            body=body,
            params=params,
            headers=self.authenticated(headers),
        )

    async def patch(
        self,
        url: str,
        *,
        body: Body | None = None,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Body | None:
        return await self._proxy.patch(
            self.target(url),
            body=body,
            params=params,
            headers=self.authenticated(headers),
        )

    async def delete(
        self,
        url: str,
        *,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Body | None:
        return await self._proxy.delete(
            self.target(url), params=params, headers=self.authenticated(headers)
        )

    async def request(
        self,
        method: Method,
        url: str,
        *,
        params: Params | None = None,
        body: Body | None = None,
        headers: Headers | None = None,
    ) -> Body | None:
        response = await self._proxy.request(
            method,
            self.target(url),
            params=params,
            body=body,
            headers=self.authenticated(headers),
        )
        return self._proxy.payload(response)
