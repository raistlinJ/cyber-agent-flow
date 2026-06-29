import asyncio
import asyncssh
import subprocess
import time

async def run_client():
    server = subprocess.Popen(["./start_server.sh", "--port", "2233", "--password", "admin", "--model", "qwen3-coder"])
    time.sleep(3)
    try:
        async with asyncssh.connect('localhost', port=2233, username='kali', password='admin', known_hosts=None) as conn:
            result = await conn.run('run "tell me a joke"')
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            print(f"EXIT CODE: {result.exit_status}")
    finally:
        server.terminate()

asyncio.run(run_client())
