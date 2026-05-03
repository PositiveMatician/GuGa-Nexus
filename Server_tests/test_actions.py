import asyncio
from server.guga.actions import master
import json

async def test():
    print("Testing ping...")
    print(await master.run_command("ping", client="test-device", request_id=None))
    
    print("\nTesting status...")
    print(await master.run_command("status", client="test-device", request_id=None))
    
    print("\nTesting antigravity...")
    print(await master.run_command("I love antigravity", client="test-device", request_id=None))
    
    print("\nTesting sendto...")
    print(await master.run_command("sendto F hello", client="test-device", request_id=None))
    
    print("\nTesting unknown...")
    print(await master.run_command("hello world", client="test-device", request_id=None))

if __name__ == "__main__":
    asyncio.run(test())
