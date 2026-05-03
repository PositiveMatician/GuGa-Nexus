import asyncio
from server.guga.actions import master
import json

async def test():
    print("Testing ping...")
    print(await master.run_command("ping", client="test-device"))
    
    print("\nTesting status...")
    print(await master.run_command("status", client="test-device"))
    
    print("\nTesting antigravity...")
    # This might fail in a headless environment, but syntax and async flow will be tested
    print(await master.run_command("I love antigravity", client="test-device"))
    
    print("\nTesting sendto...")
    # This will likely return a connection error if the server is off, but won't deadlock
    print(await master.run_command("sendto F hello", client="test-device"))
    
    print("\nTesting unknown...")
    print(await master.run_command("hello world", client="test-device"))

if __name__ == "__main__":
    asyncio.run(test())
