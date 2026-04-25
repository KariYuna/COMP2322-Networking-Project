Project: Multi-threaded Web Server
Course: COMP2322 Computer Networking
Author: LETAO XIAO (ID: 24100553D)

ENVIRONMENT
-----------
Language: Python 3.x
Libraries: Standard library only (no external packages required). HTTPServer class is NOT used.

HOW TO RUN THE SERVER
---------------------
1. Open a terminal or PowerShell in the directory containing `server.py`.
2. Execute the script using Python:
   python server.py
   (Or `python3 server.py` depending on your environment variables).
3. The server will automatically:
   - Bind to 127.0.0.1 on port 8080.
   - Create a `www/` directory if it does not exist.
   - Generate sample test files (`index.html`, `hello.txt`, `image.png`) inside the `www/` folder.
   - Create a `server.log` file in the root directory to record access statistics.

HOW TO TEST
-----------
Once the server is running, you can test it using a web browser or the `curl` command-line tool.
- Browser: Navigate to http://127.0.0.1:8080/index.html
- Terminal: curl -i http://127.0.0.1:8080/index.html

HOW TO STOP THE SERVER
----------------------
Press Ctrl+C in the terminal where the server is running to initiate a graceful shutdown.