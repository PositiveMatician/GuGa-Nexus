1. Add extension based script runner like the one used in Jarvis , it allows user to run precreated scripts and nothing else

2. Create the custom domain name for the cloud tunnel , where during installation , if user selects the internet mode , user is asked for a custom domain name , the cloud tunnel is then created using that domain name. User is asked for login in cloud tunnel with steps as to how to do all the login and setup and the rest is handled by the installer 

3. Create the MCP server for the guga 

4. Concurrent interactive sessions for the same device
    Summary & Recommendation
    Mode	Thread-Safe?	Condition
    Standard (-r)	✅ Yes	Safe for all devices and concurrent runs.
    Interactive (-i)	⚠️ Partial	Safe only if targeting different device_ids.
    Ask User (--ask)	⚠️ Partial	Safe only if targeting different device_ids.
    Recommendation: If you need to support multiple concurrent interactive sessions for the same device, the server's pending_asks logic should be refactored to use a unique request_id or correlation_id instead of just the device_id.
    
    This client UI needs features like:
    i. Reply to a message , which will help in identifying which message the user is replying to
    ii. Copy message , allows the user to copy the message and paste it somewhere else 

5.  there are several other areas that are not thread-safe or concurrency-safe.

    1. Trusted Device Management
    Status: ❌ Not Thread-Safe The server stores paired devices in ~/.guga/trusted_devices.json.

    The Issue: The functions load_trusted_devices and save_trusted_device perform a "Read-Modify-Write" operation without any file locking.
    Consequence: If two devices are paired simultaneously, or if a device's token is being updated (migration) while another is being added, one request will overwrite the other, leading to lost pairing data or a corrupted JSON file.
    2. Capabilities Tracking
    Status: ❌ Not Thread-Safe The capabilities.json file tracks which components (systemd, man pages, etc.) are installed.

    The Issue: Both the CLI and the Installer read/write this file using the same "Read-Modify-Write" pattern as the trusted devices.
    Consequence: Concurrent runs of the installer or status checks could lead to inconsistent system states or corrupted capability reports.
    3. Multi-Admin Pairing Approval
    Status: ⚠️ Not Concurrency-Safe When running guga --approve --watch in multiple terminals:

    The Issue: The server doesn't "lock" a pending request when an admin starts looking at it.
    Consequence: Two admins will see the same request. If Admin A approves it, Admin B's terminal will still show the prompt. When Admin B tries to approve, the server will return a 404 Not Found error because the request was already consumed and deleted by Admin A.
    4. Cloudflare Tunnel Initialization
    Status: ⚠️ Partially Protected The tunnel_url is handled as a global variable in daemon.py.

    The Issue: While there is a basic environment variable check (GUGA_INITIALIZED) to prevent double-initialization, the actual start_cloudflare_tunnel function doesn't prevent multiple subprocesses from being spawned if called concurrently.
    Consequence: Spawning multiple tunnels would lead to port conflicts and unstable connection URLs.

    5. Installer & Uninstaller
    Status: ❌ Not Thread-Safe The guga --install-service and guga --uninstall commands modify global system files (/etc/systemd/system/guga.service, ~/.guga/.env).

    The Issue: There is no "install lock" or "mutex" to prevent these from running at the same time.
    Consequence: Running an install and uninstall simultaneously will leave the system in a "zombie" state where the service file might exist but the environment configuration is deleted.

    switching to SQLite and using Mutexes (specifically File Locks) would resolve the majority of these issues, but they solve different parts of the problem:
    
    1. Why SQLite solves the JSON issues
    Switching trusted_devices.json and capabilities.json to SQLite solves the "Read-Modify-Write" race condition because:

    Atomic Transactions: SQLite handles locking at the file level automatically. When you write, it locks the database so another thread/process cannot read a "half-written" state or overwrite your changes with stale data.
    Row-level Logic: Instead of loading the entire JSON object into memory, changing one key, and saving the whole thing back, you can update just the specific row you need.
    2. Why you need a "File Mutex" (File Lock)
    A standard Python threading.Lock only works inside a single process. Since the CLI, the Installer, and the Server are separate processes, you need a File Lock (using something like fcntl.flock on Linux or a .lock file):

    Installer/Uninstaller: A file lock like ~/.guga/install.lock would prevent two instances of the installer from running at once.
    Cloudflare Tunnel: A lock would ensure only one process manages the tunnel lifecycle.
    3. What still needs a Logic Change
    While SQLite and Locks solve the data corruption, some issues require a logic change in addition to the tools:

    Concurrent Interactive Sessions: Even with a Mutex, if the server uses pending_asks[device_id], it can still only track one question per phone. You must change the logic to use a request_id (e.g., pending_asks[request_id]) so the phone can say "I'm replying to request #102."
    Multi-Admin Approval: With SQLite, you can add a status column to the pending pairings. When one admin opens the approval screen, the server can mark that request as UNDER_REVIEW in the DB, so other admins don't try to approve the same one.
    Summary of the Fix:
    Issue	Fix
    JSON Corruption	✅ SQLite (Transactions)
    Installer Races	✅ File Lock (Cross-process Mutex)
    Interactive Sessions	✅ Logic Change (Map by Request ID, not Device ID)
    Admin Collisions	✅ SQLite (Row Status) + Logic Change
    Recommendation: If you move to SQLite, use the aiosqlite or dataset library for ease of use, and consider a simple .lock file in ~/.guga/ for the installer/service management.


    

6. The browser client needs a setting section and both browser and android needs animation and sounds. A new hide input toggle should be there for android and browser both. (reference Framework7 docs)(add the animations from the Framework7 docs)

