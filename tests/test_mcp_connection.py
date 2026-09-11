"""通过临时回环 HTTP 服务验证真实 SSE 握手，不操作游戏实例。"""

import asyncio
import socket
import unittest

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.sse import sse_client
from starlette.applications import Starlette


class TestMcpConnection(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_and_mounted_transport(self):
        from mcp_server_sse import app, configure_auth
        from module.webui import mcp_auth

        for mounted in (False, True):
            with self.subTest(mounted=mounted):
                configure_auth('test-only-merge-key', public_bind=False)
                application = Starlette() if mounted else app
                if mounted:
                    application.mount('/mcp', app)
                sock = socket.socket()
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(
                    application, lifespan='off', log_config=None, access_log=False))
                task = asyncio.create_task(server.serve(sockets=[sock]))
                try:
                    async with asyncio.timeout(10):
                        while not server.started:
                            if task.done():
                                await task
                                self.fail('临时服务未启动')
                            await asyncio.sleep(0.01)
                    path = '/mcp/sse' if mounted else '/sse'
                    base = f'http://127.0.0.1:{port}'
                    async with httpx.AsyncClient() as client:
                        response = await client.get(base + path)
                        self.assertEqual(response.status_code, 401)
                    # URL 凭据只用于建立 SSE；后续 POST 由真实会话 ID 鉴权。
                    async with asyncio.timeout(15):
                        async with sse_client(base + path + '?key=test-only-merge-key') as streams:
                            async with ClientSession(*streams) as session:
                                result = await session.initialize()
                                self.assertEqual(result.serverInfo.name, 'AzurPilot-MCP')
                                tools = await session.list_tools()
                                self.assertGreaterEqual(len(tools.tools), 18)
                finally:
                    server.should_exit = True
                    await asyncio.wait_for(task, timeout=10)
                    sock.close()
                    mcp_auth._reset()


if __name__ == '__main__':
    unittest.main()
